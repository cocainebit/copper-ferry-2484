from datetime import timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from desktop_service.billing import apply_event
from desktop_service.config import settings
from desktop_service.db import Computer, Credential, Entitlement, Ledger, Run, TrialIntent, Workspace, now
from desktop_service.entitlements import PaymentProof, activate, balance, charge, validate_payment
from desktop_service.security import seal, unseal


def test_upload_requires_control_and_writes_home(client, db, monkeypatch):
    from unittest.mock import AsyncMock

    from desktop_service import runtime

    computer = Computer(
        workspace_id="w",
        name="Upload desktop",
        request_id="upload-computer",
        status="running",
        sandbox_id="sandbox-upload",
        controller="local-user",
    )
    db.add(computer)
    db.commit()
    monkeypatch.setattr(runtime, "tool", AsyncMock(return_value='{"name":"note.txt","size":5}'))
    response = client.post(
        f"/v1/computers/{computer.id}/upload",
        json={"path": "notes/note.txt", "data": "aGVsbG8="},
    )
    assert response.status_code == 200
    assert response.json() == {"name": "note.txt", "size": 5}
    runtime.tool.assert_awaited_once_with(
        "sandbox-upload", "write_file", {"path": "notes/note.txt", "data": "aGVsbG8="}
    )


def test_upload_rejects_non_controller_and_invalid_payload(client, db):
    computer = Computer(
        workspace_id="w",
        name="Upload desktop",
        request_id="upload-computer-2",
        status="running",
        sandbox_id="sandbox-upload",
        controller="agent",
    )
    db.add(computer)
    db.commit()
    assert client.post(f"/v1/computers/{computer.id}/upload", json={"path": "a", "data": "YQ=="}).status_code == 409
    assert client.post(f"/v1/computers/{computer.id}/upload", json={"path": "../a", "data": "YQ=="}).status_code == 409


def create(client, key="unique-request-1"):
    return client.post("/v1/workspaces/w/computers", json={"name": "My computer"}, headers={"Idempotency-Key": key})


def test_auth_required(client):
    assert client.get("/v1/workspaces", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_workspace_isolation(client):
    assert client.get("/v1/workspaces/other/computers").status_code == 403
    assert client.get("/v1/workspaces/other/entitlements").status_code == 403
    assert client.post("/v1/workspaces/other/billing/topup").status_code == 403


def test_create_idempotent(client, db):
    a = create(client)
    b = create(client)
    assert a.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert len(db.scalars(select(Computer)).all()) == 1


def test_quota(client):
    assert create(client, "request-number-1").status_code == 201
    assert create(client, "request-number-2").status_code == 201
    assert create(client, "request-number-3").status_code == 409


def test_start_one_per_workspace(client):
    a = create(client, "request-number-1").json()["id"]
    b = create(client, "request-number-2").json()["id"]
    assert client.post(f"/v1/computers/{a}/actions/start").status_code == 200
    assert client.post(f"/v1/computers/{b}/actions/start").status_code == 409


def test_takeover_waits_for_tool_boundary(client, db):
    cid = create(client).json()["id"]
    db.get(Computer, cid).status = "running"
    r = Run(computer_id=cid, prompt="hi", request_id="run-request-1", status="running", lease="worker")
    db.add(r)
    db.commit()
    response = client.post(f"/v1/computers/{cid}/actions/take-control")
    assert response.json()["controller"] == "pending:local-user"
    db.expire_all()
    assert db.get(Run, r.id).status == "paused"


def test_task_requires_connected_key(client, db):
    cid = create(client).json()["id"]
    db.get(Computer, cid).status = "running"
    db.commit()
    r = client.post(
        f"/v1/computers/{cid}/runs", json={"prompt": "hello"}, headers={"Idempotency-Key": "task-request-1"}
    )
    assert r.status_code == 409 and "Anthropic" in r.json()["detail"]


def test_task_idempotency(client, db):
    cid = create(client).json()["id"]
    db.get(Computer, cid).status = "running"
    db.add(Credential(workspace_id="w", encrypted_key=seal("fake-key"), suffix="-key"))
    db.commit()
    kwargs = {"json": {"prompt": "hello"}, "headers": {"Idempotency-Key": "task-request-1"}}
    a = client.post(f"/v1/computers/{cid}/runs", **kwargs)
    b = client.post(f"/v1/computers/{cid}/runs", **kwargs)
    assert a.status_code == 201 and a.json()["id"] == b.json()["id"]


def test_approval_is_bound_to_run(client, db):
    cid = create(client).json()["id"]
    db.get(Computer, cid).status = "running"
    r = Run(
        computer_id=cid,
        prompt="hello",
        request_id="request123",
        status="awaiting_approval",
        approval={"action": "Send a message"},
    )
    db.add(r)
    db.commit()
    assert client.post(f"/v1/runs/{r.id}/approve").status_code == 200
    db.refresh(r)
    assert r.approval["decision"] == "approve"
    assert client.post(f"/v1/runs/{r.id}/approve").status_code == 409


def test_no_checkout_without_launch_gate(client):
    assert client.post("/v1/workspaces/w/billing/subscription").status_code == 503


def test_credits_exactly_once(db):
    w = db.get(Workspace, "w")
    w.included = 1
    assert charge(db, w, "computer", 123)
    assert charge(db, w, "computer", 123)
    assert not charge(db, w, "computer", 124)
    db.commit()
    assert w.included == 0
    assert len(db.scalars(select(Ledger)).all()) == 1


def test_invoice_duplicate_and_old_period(db, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings(), "stripe_subscription_price", "price_subscription")
    monkeypatch.setattr(
        "stripe.Subscription.retrieve",
        lambda _: SimpleNamespace(
            status="active",
            customer="cus_test",
            items={"data": [{"quantity": 1, "price": {"id": "price_subscription"}}]},
        ),
    )
    w = db.get(Workspace, "w")
    w.customer_id = "cus_test"
    w.included = 0
    db.commit()
    ev = {
        "id": "evt_1",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_1",
                "customer": "cus_test",
                "subscription": "sub_test",
                "billing_reason": "subscription_cycle",
                "lines": {"data": [{"period": {"end": 2000000000}}]},
            }
        },
    }
    apply_event(db, ev)
    db.commit()
    assert w.included == 6000
    w.included = 5990
    db.commit()
    apply_event(db, ev)
    db.commit()
    assert w.included == 5990
    ev["id"] = "evt_old"
    ev["data"]["object"]["id"] = "in_old"
    ev["data"]["object"]["lines"]["data"][0]["period"]["end"] = 1900000000
    apply_event(db, ev)
    db.commit()
    assert w.included == 5990


def test_encrypted_secret():
    v = seal("a-secret-api-key")
    assert "a-secret-api-key" not in v and unseal(v) == "a-secret-api-key"


def test_unconfigured_trial_never_returns_payment_address(client):
    r = client.post(
        "/v1/trials/intents", json={"workspace_id": "w", "service": "agent-desktop", "wallet": "wallet12345"}
    )
    assert r.status_code == 503 and "recipient" not in r.json()


@pytest.fixture
def intent(db, monkeypatch):
    s = settings()
    monkeypatch.setattr(s, "trial_chain", "chain-test")
    monkeypatch.setattr(s, "trial_token", "token-test")
    monkeypatch.setattr(s, "trial_recipient", "treasury")
    monkeypatch.setattr(s, "trial_decimals", 9)
    i = TrialIntent(
        workspace_id="w",
        user_id="local-user",
        service="agent-desktop",
        wallet="wallet-test",
        chain="chain-test",
        nonce="nonce",
        message="message",
        created_at=now() - timedelta(minutes=1),
        verified_at=now(),
        expires_at=now() + timedelta(minutes=29),
    )
    db.add(i)
    db.commit()
    return i


@pytest.fixture
def proof():
    return PaymentProof(
        chain="chain-test",
        transaction_id="tx-123456",
        token="token-test",
        sender="wallet-test",
        recipient="treasury",
        amount_atomic=10**9,
        balance_after_atomic=10000 * 10**9,
        successful=True,
        finalized=True,
        direct_transfer=True,
        block_time=int(now().replace(tzinfo=timezone.utc).timestamp()),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_atomic", 10**9 - 1),
        ("amount_atomic", 10**9 + 1),
        ("balance_after_atomic", 10000 * 10**9 - 1),
        ("sender", "attacker"),
        ("recipient", "attacker"),
        ("token", "fake-token"),
        ("chain", "wrong-chain"),
        ("successful", False),
        ("finalized", False),
        ("direct_transfer", False),
        ("block_time", 1),
    ],
)
def test_reject_invalid_proofs(intent, proof, field, value):
    with pytest.raises(HTTPException):
        validate_payment(proof.model_copy(update={field: value}), intent)


def test_float_token_quantities_rejected(proof):
    with pytest.raises(ValidationError):
        PaymentProof.model_validate({**proof.model_dump(), "amount_atomic": 1e9})


def test_trial_exactly_seven_days_idempotent(db, intent, proof):
    before = now()
    e = activate(db, intent, proof)
    assert before + timedelta(days=7) <= e.expires_at <= now() + timedelta(days=7)
    assert e.remaining == 600 and activate(db, intent, proof).id == e.id
    assert len(db.scalars(select(Entitlement)).all()) == 1


def test_expired_trial_cannot_be_reset(db, intent, proof):
    e = activate(db, intent, proof)
    e.expires_at = now() - timedelta(days=1)
    db.commit()
    with pytest.raises(HTTPException):
        activate(db, intent, proof.model_copy(update={"transaction_id": "new-transaction"}))


def test_trial_credits_expire(db, intent, proof):
    e = activate(db, intent, proof)
    w = db.get(Workspace, "w")
    w.subscription = "inactive"
    db.flush()
    assert balance(db, w) == 600
    e.expires_at = now() - timedelta(seconds=1)
    db.flush()
    assert balance(db, w) == 0


def test_cross_account_replay(db, intent, proof):
    activate(db, intent, proof)
    intent.user_id = "another-user"
    intent.workspace_id = "other"
    with pytest.raises(HTTPException):
        activate(db, intent, proof)


def test_late_invoice_cannot_reactivate_canceled_subscription(db, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "stripe.Subscription.retrieve", lambda _: SimpleNamespace(status="canceled", customer="cus_test")
    )
    w = db.get(Workspace, "w")
    w.customer_id = "cus_test"
    w.subscription = "canceled"
    w.included = 0
    db.commit()
    apply_event(
        db,
        {
            "id": "late",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_late",
                    "customer": "cus_test",
                    "subscription": "sub_test",
                    "billing_reason": "subscription_cycle",
                    "lines": {"data": [{"period": {"end": 2000000000}}]},
                }
            },
        },
    )
    db.commit()
    assert w.subscription == "canceled" and w.included == 0


@pytest.mark.parametrize("action", ["stop", "delete"])
def test_stop_and_delete_retain_inflight_lease(client, db, action):
    cid = create(client).json()["id"]
    db.get(Computer, cid).status = "running"
    r = Run(computer_id=cid, prompt="hi", request_id="run123456", status="running", lease="inflight")
    db.add(r)
    db.commit()
    response = (
        client.delete(f"/v1/computers/{cid}?confirm=My%20computer")
        if action == "delete"
        else client.post(f"/v1/computers/{cid}/actions/stop")
    )
    assert response.status_code == 200
    db.refresh(r)
    assert r.lease == "inflight"


def test_start_reports_offline_worker(client, db):
    from desktop_service.db import ServiceHeartbeat

    cid = create(client).json()["id"]
    db.delete(db.get(ServiceHeartbeat, "desktop-worker"))
    db.commit()
    result = client.post(f"/v1/computers/{cid}/actions/start")
    assert result.status_code == 503
    db.refresh(db.get(Computer, cid))
    assert db.get(Computer, cid).status == "stopped"


def test_create_saves_selected_resources(client, db):
    from desktop_service.feature_models import DesktopProfile

    response = client.post(
        "/v1/workspaces/w/computers",
        json={"name": " Small ", "cpu": 1, "memory_gib": 2},
        headers={"Idempotency-Key": "resource-create-001"},
    )
    assert response.status_code == 201
    profile = db.get(DesktopProfile, response.json()["id"])
    assert (profile.cpu, profile.memory_gib) == (1, 2)
    assert response.json()["name"] == "Small"


@pytest.mark.parametrize(
    "body", [{"name": "   "}, {"name": "Invalid", "cpu": 8}, {"name": "Invalid", "memory_gib": 32}]
)
def test_create_rejects_invalid_configuration(client, db, body):
    response = client.post("/v1/workspaces/w/computers", json=body, headers={"Idempotency-Key": "invalid-create-001"})
    assert response.status_code == 422
    assert db.scalar(select(Computer)) is None

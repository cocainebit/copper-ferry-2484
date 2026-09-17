"""Invoice lifecycle tests use a fake external rail; no real funds or RPC calls."""

import base64
import json
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from desktop_service import crypto_payments as api
from desktop_service.config import settings
from desktop_service.crypto_models import PaymentInvoice
from desktop_service.db import Member, now
from desktop_service.payment_models import PlatformEntry
from desktop_service.platform_credits import available, grant


@pytest.fixture
def rail(db, monkeypatch):
    network, asset, recipient = "eip155:84532", "0x" + "1" * 40, "0x" + "2" * 40

    def quote(amount):
        return dict(
            scheme="exact",
            network=network,
            asset=asset,
            payTo=recipient,
            amount=str(amount),
            maxTimeoutSeconds=300,
            extra={"name": "USDC", "version": "2"},
        )

    def validate(payload, requirements):
        if payload.get("nonce") != requirements["extra"]["invoiceNonce"]:
            raise ValueError("Wrong nonce")
        return {"payer": "0x" + "3" * 40}

    fake = SimpleNamespace(
        configuration_status=lambda: dict(
            enabled=True, network=network, asset=asset, recipient=recipient, test_network=True
        ),
        payment_requirements=quote,
        validate_payload=validate,
        verify=AsyncMock(return_value={"isValid": True}),
        settle=AsyncMock(return_value={"transaction": "0x" + "4" * 64}),
        reconcile=AsyncMock(return_value=None),
        current_block=AsyncMock(return_value=100),
    )
    monkeypatch.setattr(api, "rail", lambda: fake)
    monkeypatch.setattr(api, "Session", sessionmaker(db.bind, expire_on_commit=False))
    config = settings().model_copy(
        update={
            "platform_service_prices": {"render": 1000},
            "platform_service_tokens": {"render": "render-secret", "cubicle": "desktop-secret"},
        }
    )
    monkeypatch.setattr(api, "settings", lambda: config)
    from desktop_service import platform_credits

    monkeypatch.setattr(platform_credits, "settings", lambda: config)
    return fake


def create(client, key="invoice-one", wid="w", amount=1000000):
    return client.post(
        f"/v1/workspaces/{wid}/payments/invoices", json={"amount_micro_usdc": amount}, headers={"Idempotency-Key": key}
    )


def authorization(invoice, nonce=None):
    payload = {
        "nonce": nonce or invoice["payment_required"]["accepts"][0]["extra"]["invoiceNonce"],
        "payload": {"authorization": {"validBefore": str(int(time.time()) + 240)}},
    }
    return {"PAYMENT-SIGNATURE": base64.b64encode(json.dumps(payload).encode()).decode()}


def receipt(invoice):
    quote = invoice["payment_required"]["accepts"][0]
    return dict(
        transaction="0x" + "4" * 64,
        payer="0x" + "3" * 40,
        network=quote["network"],
        amount=quote["amount"],
        asset=quote["asset"],
        recipient=quote["payTo"],
        nonce=quote["extra"]["invoiceNonce"],
        block=101,
        block_hash="0x" + "5" * 64,
    )


def test_invoice_permissions_idempotency_and_challenge(client, db, rail):
    response = create(client)
    assert response.status_code == 201
    invoice = response.json()
    assert create(client).json()["id"] == invoice["id"]
    assert create(client, amount=2000000).status_code == 409
    assert create(client, wid="other").status_code == 403
    response = client.post(f"/v1/payment-invoices/{invoice['id']}/pay")
    assert response.status_code == 402
    assert json.loads(base64.b64decode(response.headers["payment-required"])) == response.json()
    assert available(db, "w") == 0
    rail.settle.assert_not_called()


def test_member_can_read_but_cannot_create_or_pay(client, db, rail):
    invoice = create(client).json()
    db.scalar(select(Member).where(Member.workspace_id == "w")).role = "member"
    db.commit()
    assert client.get("/v1/workspaces/w/payments").status_code == 200
    assert client.get(f"/v1/payment-invoices/{invoice['id']}").status_code == 200
    assert create(client, key="another-invoice").status_code == 403
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 403


@pytest.mark.parametrize(
    "header", ["not-base64!", "W10=", "bnVsbA==", "x" * 24001], ids=["invalid-base64", "list", "null", "oversized"]
)
def test_malformed_authorization_never_settles(client, rail, header):
    invoice = create(client).json()
    assert (
        client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers={"PAYMENT-SIGNATURE": header}).status_code
        == 400
    )
    rail.verify.assert_not_called()
    rail.settle.assert_not_called()


def test_wrong_nonce_and_cross_invoice_proof_rejected(client, db, rail):
    first = create(client).json()
    second = create(client, key="second-invoice").json()
    response = client.post(f"/v1/payment-invoices/{second['id']}/pay", headers=authorization(first))
    assert response.status_code == 400
    db.add(Member(workspace_id="other", user_id="local-user", email="you@localhost", role="owner"))
    db.commit()
    other = create(client, wid="other").json()
    assert client.post(f"/v1/payment-invoices/{other['id']}/pay", headers=authorization(first)).status_code == 400
    assert available(db, "other") == 0
    rail.settle.assert_not_called()


def test_credit_only_after_independent_receipt_and_retry_once(client, db, rail):
    invoice = create(client).json()
    response = client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice))
    assert response.status_code == 202
    assert available(db, "w") == 0
    rail.reconcile.return_value = receipt(invoice)
    response = client.get(f"/v1/payment-invoices/{invoice['id']}")
    assert response.json()["status"] == "paid"
    db.expire_all()
    assert available(db, "w") == 1000000
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 200
    assert db.scalar(select(func.count()).select_from(PlatformEntry)) == 1
    rail.settle.assert_awaited_once()
    assert db.get(PaymentInvoice, invoice["id"]).signed_payload is None


def test_uncertain_settlement_persists_and_never_resubmits(client, db, rail):
    rail.settle.side_effect = TimeoutError("lost response")
    invoice = create(client).json()
    for _ in range(3):
        assert (
            client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
        )
    db.expire_all()
    stored = db.get(PaymentInvoice, invoice["id"])
    assert stored.status == "settlement_pending" and stored.signed_payload
    assert invoice["payment_required"]["accepts"][0]["extra"]["invoiceNonce"] not in stored.signed_payload
    assert available(db, "w") == 0
    rail.settle.assert_awaited_once()


def test_expired_invoice_rejected(client, db, rail):
    invoice = create(client).json()
    db.get(PaymentInvoice, invoice["id"]).expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 409
    rail.settle.assert_not_called()


def test_service_secret_cannot_charge_other_service(client, db, rail):
    grant(db, "w", 10000, "test-grant", "test")
    db.commit()
    body = {"workspace_id": "w", "service": "cubicle", "units": 1}
    headers = {"Authorization": "Bearer render-secret", "Idempotency-Key": "usage-request"}
    assert client.post("/internal/platform/usage", json=body, headers=headers).status_code == 401
    body["service"] = "render"
    assert client.post("/internal/platform/usage", json=body, headers=headers).status_code == 200
    assert client.post("/internal/platform/usage", json=body, headers=headers).status_code == 200
    db.expire_all()
    assert available(db, "w") == 9000
    body["units"] = 2
    assert client.post("/internal/platform/usage", json=body, headers=headers).status_code == 409


def test_concurrent_receipt_recovery_credits_once(client, db, rail):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    invoice = create(client).json()
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
    barrier = Barrier(4)

    def recover(_):
        with api.Session() as session:
            row = session.get(PaymentInvoice, invoice["id"])
            barrier.wait(timeout=5)
            api.attach_receipt(session, row, receipt(invoice))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(recover, range(4)))
    db.expire_all()
    assert available(db, "w") == 1000000
    assert db.scalar(select(func.count()).select_from(PlatformEntry)) == 1


def test_verification_rejection_does_not_settle_or_credit(client, db, rail):
    rail.verify.return_value = {"isValid": False}
    invoice = create(client).json()
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
    rail.settle.assert_not_called()
    assert available(db, "w") == 0


def test_settle_response_alone_does_not_grant_and_no_credentials_leak(client, db, rail):
    invoice = create(client).json()
    rail.settle.return_value = {"success": True, "transaction": "0x" + "4" * 64}
    response = client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice))
    assert response.status_code == 202
    assert available(db, "w") == 0
    public_invoice = client.get(f"/v1/payment-invoices/{invoice['id']}").json()
    assert not ({"signed_payload", "payload_digest", "request_id"} & public_invoice.keys())


def test_paid_response_header_and_exact_grant(client, db, rail):
    invoice = create(client, amount=2000000).json()
    rail.reconcile.return_value = receipt(invoice)
    response = client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice))
    assert response.status_code == 200
    payment_response = json.loads(base64.b64decode(response.headers["payment-response"]))
    assert payment_response["success"] is True
    assert payment_response["transaction"] == receipt(invoice)["transaction"]
    db.expire_all()
    assert available(db, "w") == 2000000


def test_authorization_durably_saved_before_network_call(client, db, rail):
    invoice = create(client).json()

    async def verify(payload, quote):
        with api.Session() as session:
            row = session.get(PaymentInvoice, invoice["id"])
            assert row.status == "settlement_pending"
            assert row.signed_payload and row.payload_digest and row.submitted_at
            assert row.settlement_from_block == 100
            assert available(session, "w") == 0
        raise TimeoutError("simulate provider loss")

    rail.verify.side_effect = verify
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
    rail.settle.assert_not_called()


def test_configuration_change_rejects_old_invoice(client, rail):
    invoice = create(client).json()
    previous = rail.configuration_status()
    rail.configuration_status = lambda: {**previous, "recipient": "0x" + "9" * 40}
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 409
    rail.settle.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "999999"),
        ("nonce", "0x" + "f" * 64),
        ("recipient", "0x" + "8" * 40),
        ("network", "eip155:1"),
        ("payer", "0x" + "7" * 40),
    ],
)
def test_receipt_binding_mismatch_never_credits(client, db, rail, field, value):
    invoice = create(client).json()
    rail.reconcile.return_value = {**receipt(invoice), field: value}
    response = client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice))
    assert response.status_code == 202
    assert available(db, "w") == 0


def test_finalized_unused_expiry_releases_pending_invoice(client, db, rail):
    rail.expired_unsettled = AsyncMock(return_value=True)
    invoice = create(client).json()
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
    result = client.get(f"/v1/payment-invoices/{invoice['id']}")
    assert result.json()["status"] == "failed"
    assert available(db, "w") == 0
    assert create(client, key="after-unused-expiry").status_code == 201
    rail.settle.assert_awaited_once()


def test_pending_invoice_blocks_second_payment_request(client, rail):
    invoice = create(client).json()
    assert client.post(f"/v1/payment-invoices/{invoice['id']}/pay", headers=authorization(invoice)).status_code == 202
    assert create(client, key="unsafe-second-invoice").status_code == 409

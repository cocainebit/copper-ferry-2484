from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from desktop_service import runtime
from desktop_service.api_keys import ApiKey
from desktop_service.db import Computer, Member, now
from desktop_service.main import app


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Live", request_id="key-001", status="running", sandbox_id="sb")
    db.add(c)
    db.commit()
    return c


def make_key(client, scopes=None, **extra):
    body = {"name": "agent key", **({"scopes": scopes} if scopes else {}), **extra}
    response = client.post("/v1/workspaces/w/api-keys", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def as_key(token):
    return TestClient(app, headers={"Authorization": "Bearer " + token})


def test_create_list_revoke_and_one_time_reveal(client, db):
    created = make_key(client, ["read", "control"])
    assert created["key"].startswith("cbk_") and created["scopes"] == ["read", "control"]
    listed = client.get("/v1/workspaces/w/api-keys").json()
    assert listed[0]["prefix"] == created["prefix"] and "key" not in listed[0]
    assert db.scalar(select(ApiKey)).key_hash != created["key"]
    revoked = client.delete(f"/v1/api-keys/{created['id']}").json()
    assert revoked["revoked_at"]
    assert as_key(created["key"]).get("/v1/workspaces").status_code == 401


def test_scope_normalization_and_validation(client):
    assert make_key(client, ["manage"])["scopes"] == ["read", "manage"]
    assert client.post("/v1/workspaces/w/api-keys", json={"name": "bad", "scopes": ["admin"]}).status_code == 422
    assert client.post("/v1/workspaces/w/api-keys", json={"name": "  ", "scopes": ["read"]}).status_code == 422


def test_key_is_workspace_scoped_and_acts_as_creator(client, db, running):
    token = make_key(client, ["read"])["key"]
    key = as_key(token)
    workspaces = key.get("/v1/workspaces").json()
    assert [w["id"] for w in workspaces] == ["w"]
    assert key.get("/v1/workspaces/w/computers").status_code == 200
    assert key.get(f"/v1/computers/{running.id}").json()["name"] == "Live"
    assert key.get("/v1/workspaces/other/computers").status_code == 403


def test_read_key_cannot_control_or_manage(client, db, running, monkeypatch):
    monkeypatch.setattr(runtime, "tool", AsyncMock(return_value="ok"))
    key = as_key(make_key(client, ["read"])["key"])
    assert key.post(f"/v1/computers/{running.id}/click", json={"x": 1, "y": 2}).status_code == 403
    assert key.post(f"/v1/computers/{running.id}/actions/stop").status_code == 403
    assert key.patch(f"/v1/computers/{running.id}", json={"name": "x"}).status_code == 403
    runtime.tool.assert_not_awaited()


def test_control_key_drives_but_cannot_manage(client, db, running, monkeypatch):
    monkeypatch.setattr(runtime, "tool", AsyncMock(return_value="ok"))
    key = as_key(make_key(client, ["control"])["key"])
    assert key.post(f"/v1/computers/{running.id}/click", json={"x": 1, "y": 2}).status_code == 200
    assert key.post(f"/v1/computers/{running.id}/actions/stop").status_code == 403
    assert (
        key.post(
            "/v1/workspaces/w/computers", json={"name": "New"}, headers={"Idempotency-Key": "key-create-001"}
        ).status_code
        == 403
    )


def test_manage_key_creates_and_stops_but_never_touches_session_only_routes(client, db, running):
    key = as_key(make_key(client, ["manage"])["key"])
    created = key.post(
        "/v1/workspaces/w/computers", json={"name": "From key"}, headers={"Idempotency-Key": "key-create-002"}
    )
    assert created.status_code == 201
    assert key.post(f"/v1/computers/{running.id}/actions/stop").status_code == 200
    assert key.patch(f"/v1/computers/{running.id}", json={"name": "Renamed by key"}).status_code == 200
    assert key.get("/v1/workspaces/w/api-keys").status_code == 403
    assert key.post("/v1/workspaces/w/api-keys", json={"name": "escalate"}).status_code == 403
    assert key.put("/v1/workspaces/w/credential", json={"key": "sk-ant-" + "x" * 30}).status_code == 403
    assert key.post("/v1/workspaces/w/invitations", json={"email": "a@b.co"}).status_code == 403
    assert key.post(f"/v1/computers/{running.id}/viewer-ticket").status_code == 403


def test_expired_key_and_member_revocation_close_access(client, db, running):
    token = make_key(client, ["read"], expires_in_days=1)["key"]
    key = as_key(token)
    assert key.get("/v1/workspaces").status_code == 200
    row = db.scalar(select(ApiKey))
    row.expires_at = now() - timedelta(minutes=1)
    db.commit()
    assert key.get("/v1/workspaces").status_code == 401
    row.expires_at = None
    db.commit()
    assert key.get("/v1/workspaces/w/computers").status_code == 200
    db.delete(db.scalar(select(Member).where(Member.workspace_id == "w")))
    db.commit()
    assert key.get("/v1/workspaces/w/computers").status_code == 403


def test_key_creation_is_owner_and_session_only(client, db):
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert client.post("/v1/workspaces/w/api-keys", json={"name": "nope"}).status_code == 403
    assert client.get("/v1/workspaces/w/api-keys").status_code == 403


def test_key_limit(client):
    for index in range(20):
        make_key(client, ["read"], name=f"key {index}")
    assert client.post("/v1/workspaces/w/api-keys", json={"name": "one too many"}).status_code == 409

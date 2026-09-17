import asyncio
import base64
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import db as models
from desktop_service import runtime, secrets_vault, worker
from desktop_service.db import Computer, Event, Member
from desktop_service.feature_models import DesktopProfile
from desktop_service.secrets_vault import Secret


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Live", request_id="secret-001", status="running", sandbox_id="sb")
    db.add(c)
    db.commit()
    return c


def put(client, name, value, wid="w"):
    return client.put(f"/v1/workspaces/{wid}/secrets/{name}", json={"value": value})


def test_crud_never_returns_values(client, db):
    assert put(client, "API_TOKEN", "s3cr3t-value").status_code == 200
    assert put(client, "API_TOKEN", "rotated").status_code == 200
    listed = client.get("/v1/workspaces/w/secrets").json()
    assert [s["name"] for s in listed] == ["API_TOKEN"]
    assert "rotated" not in client.get("/v1/workspaces/w/secrets").text
    stored = db.scalar(select(Secret))
    assert "rotated" not in stored.encrypted_value
    assert client.delete("/v1/workspaces/w/secrets/API_TOKEN").status_code == 200
    assert client.delete("/v1/workspaces/w/secrets/API_TOKEN").status_code == 404
    assert client.get("/v1/workspaces/w/secrets").json() == []


@pytest.mark.parametrize("name", ["lower", "1BAD", "HOME", "PATH", "VNC_PASSWORD", "A" * 65, "WITH-DASH", "SP ACE"])
def test_name_validation(client, name):
    assert put(client, name, "x").status_code == 422


def test_owner_only_and_workspace_scoped(client, db):
    assert put(client, "X", "1", wid="other").status_code == 403
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert put(client, "X", "1").status_code == 403
    assert client.get("/v1/workspaces/w/secrets").status_code == 200


def test_limit(client):
    for index in range(secrets_vault.MAX_SECRETS):
        assert put(client, f"S_{index}", "v").status_code == 200
    assert put(client, "ONE_MORE", "v").status_code == 409


def test_env_file_quotes_values_safely():
    text = secrets_vault.env_file({"B": "it's $HOME `x`", "A": "plain"})
    assert text == "export A='plain'\nexport B='it'\\''s $HOME `x`'\n"


def test_injection_targets_tmpfs_and_respects_allowlist(client, db, running, monkeypatch):
    put(client, "ALPHA", "alpha-value")
    put(client, "BETA", "beta-value")
    execute = AsyncMock(return_value="")
    monkeypatch.setattr(runtime, "execute", execute)
    count = asyncio.run(secrets_vault.inject(db, running))
    db.commit()
    assert count == 2
    script = execute.await_args.args[1]
    assert execute.await_args.args[0] == "sb"
    assert "/dev/shm/cubicle/secrets.env" in script and "chmod 600" in script
    payload = script.split("printf %s ", 1)[1].split(" |", 1)[0]
    assert base64.b64decode(payload).decode() == "export ALPHA='alpha-value'\nexport BETA='beta-value'\n"
    assert "alpha-value" not in script
    events = [e.text for e in db.scalars(select(Event).where(Event.computer_id == running.id))]
    assert events == ["2 secrets available to shells and the agent"]
    assert db.get(DesktopProfile, running.id).secrets_injected_at
    response = client.put(f"/v1/computers/{running.id}/secrets", json={"names": ["BETA"]})
    assert response.json() == {"allowlist": ["BETA"], "names": ["BETA"]}
    asyncio.run(secrets_vault.inject(db, running))
    payload = execute.await_args.args[1].split("printf %s ", 1)[1].split(" |", 1)[0]
    assert base64.b64decode(payload).decode() == "export BETA='beta-value'\n"
    assert client.get(f"/v1/computers/{running.id}/secrets").json()["names"] == ["BETA"]


def test_refresh_requires_running_owner(client, db, running, monkeypatch):
    monkeypatch.setattr(runtime, "execute", AsyncMock(return_value=""))
    put(client, "TOKEN", "t")
    assert client.post(f"/v1/computers/{running.id}/secrets/refresh").json() == {"injected": 1}
    running.status = "stopped"
    running.sandbox_id = None
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/secrets/refresh").status_code == 409
    running.workspace_id = "other"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/secrets/refresh").status_code == 403


def test_worker_injects_at_boot_and_survives_failure(client, db, monkeypatch):
    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "create", AsyncMock(return_value="booted"))
    execute = AsyncMock(return_value="")
    monkeypatch.setattr(runtime, "execute", execute)
    put(client, "BOOT_SECRET", "boot-value")
    c = Computer(workspace_id="w", name="Boot", request_id="boot-001", status="starting")
    db.add(c)
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert c.status == "running" and c.sandbox_id == "booted"
    assert execute.await_args.args[0] == "booted"
    assert "boot-value" not in "".join(e.text for e in db.scalars(select(Event)))
    # A failing injection reports itself but does not block the boot.
    monkeypatch.setattr(runtime, "execute", AsyncMock(side_effect=RuntimeError("execd down")))
    second = Computer(workspace_id="other", name="Boot 2", request_id="boot-002", status="starting")
    db.add(second)
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert second.status == "running"
    assert any(
        "could not be injected" in e.text for e in db.scalars(select(Event).where(Event.computer_id == second.id))
    )


def test_entrypoint_installs_profile_hook_without_values():
    entry = runtime.desktop_entrypoint("1440x900", False)[2]
    assert "/etc/profile.d/cubicle-secrets.sh" in entry
    assert secrets_vault.PROFILE_HOOK in entry

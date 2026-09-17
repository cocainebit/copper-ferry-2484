import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import feature_runtime, runtime
from desktop_service.config import settings
from desktop_service.db import Computer
from desktop_service.feature_models import DesktopProfile


def create(client, key, **body):
    return client.post("/v1/workspaces/w/computers", json={"name": "Box", **body}, headers={"Idempotency-Key": key})


def test_catalog_lists_unavailable_options_with_reasons(client, monkeypatch):
    body = client.get("/v1/platform/capabilities").json()
    oses = {o["id"]: o for o in body["operating_systems"]}
    assert oses["linux"]["available"] and not oses["windows"]["available"] and not oses["macos"]["available"]
    assert "KVM" in oses["windows"]["reason"] and "Apple hardware" in oses["macos"]["reason"]
    assert body["gpu"] == {
        "available": False,
        "max_per_computer": 0,
        "reason": "No GPU host is configured on this deployment",
        "linux_only": True,
    }
    assert body["capabilities"]["windows"]["terminal"] is False and body["capabilities"]["linux"]["terminal"]
    monkeypatch.setattr(settings(), "windows_enabled", True)
    monkeypatch.setattr(settings(), "gpu_enabled", True)
    body = client.get("/v1/platform/capabilities").json()
    assert {o["id"]: o["available"] for o in body["operating_systems"]} == {
        "linux": True,
        "windows": True,
        "macos": False,
    }
    assert body["gpu"]["available"] and body["gpu"]["max_per_computer"] == 1


def test_creation_fails_closed_for_unavailable_hardware(client, db, monkeypatch):
    assert create(client, "prov-mac-1", os="macos").status_code == 409
    assert create(client, "prov-win-1", os="windows", storage_gib=100).status_code == 409
    assert create(client, "prov-gpu-1", gpu=1).status_code == 409
    assert db.scalar(select(Computer)) is None
    monkeypatch.setattr(settings(), "windows_enabled", True)
    monkeypatch.setattr(settings(), "gpu_enabled", True)
    assert create(client, "prov-win-2", os="windows", storage_gib=20).status_code == 422
    assert create(client, "prov-win-3", os="windows", storage_gib=100, memory_gib=2).status_code == 422
    assert create(client, "prov-win-4", os="windows", storage_gib=100, gpu=1).status_code == 422
    assert create(client, "prov-gpu-2", gpu=2).status_code == 422
    windows = create(client, "prov-win-5", os="windows", storage_gib=100)
    assert windows.status_code == 201
    profile = db.get(DesktopProfile, windows.json()["id"])
    assert (profile.os, profile.gpu) == ("windows", 0)


def test_gpu_reaches_opensandbox_resources(client, db, monkeypatch):
    monkeypatch.setattr(settings(), "gpu_enabled", True)
    created = create(client, "prov-gpu-3", gpu=1).json()
    assert feature_runtime.resource_for(created["id"]) == {"cpu": "2", "memory": "4Gi", "gpu": "1"}


def test_windows_sandbox_uses_opensandbox_windows_profile(db, monkeypatch):
    c = Computer(workspace_id="w", name="Win", request_id="prov-win-rt")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, os="windows", cpu=2, memory_gib=4, storage_gib=100))
    db.commit()
    sandbox = type("Sandbox", (), {"id": "win-sandbox", "close": AsyncMock()})()
    create_call = AsyncMock(return_value=sandbox)
    monkeypatch.setattr(runtime.Sandbox, "create", create_call)
    assert asyncio.run(runtime.create(c.id, "password")) == "win-sandbox"
    kwargs = create_call.await_args.kwargs
    assert kwargs["image"] == settings().windows_image
    assert (kwargs["platform"].os, kwargs["platform"].arch) == ("windows", "amd64")
    assert kwargs["resource"] == {"cpu": "2", "memory": "4G", "disk": "100G"}
    assert kwargs["env"] == {"VERSION": settings().windows_version}
    assert kwargs["volumes"][0].mount_path == "/storage" and kwargs["volumes"][0].pvc.claim_name == f"desktop-{c.id}"
    assert "entrypoint" not in kwargs


def test_windows_routes_refuse_linux_only_features(client, db, monkeypatch):
    c = Computer(
        workspace_id="w",
        name="Win",
        request_id="prov-win-routes",
        status="running",
        sandbox_id="sb",
        controller="local-user",
    )
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, os="windows", storage_gib=100))
    db.commit()
    tool = AsyncMock()
    monkeypatch.setattr(runtime, "tool", tool)
    monkeypatch.setattr(runtime, "execute", AsyncMock())
    for method, path, body in [
        ("post", f"/v1/computers/{c.id}/click", {"x": 1, "y": 1}),
        ("post", f"/v1/computers/{c.id}/bash", {"command": "dir"}),
        ("post", f"/v1/computers/{c.id}/terminal-ticket", None),
        ("post", f"/v1/computers/{c.id}/audio-ticket", None),
        ("post", f"/v1/computers/{c.id}/screens", {}),
        ("post", f"/v1/computers/{c.id}/apps/firefox/install", None),
        ("post", f"/v1/computers/{c.id}/secrets/refresh", None),
    ]:
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 409 and "Windows" in response.json()["detail"], path
    run = client.post(f"/v1/computers/{c.id}/runs", json={"prompt": "hi"}, headers={"Idempotency-Key": "win-run-1"})
    assert run.status_code == 409
    tool.assert_not_awaited()
    assert client.post(f"/v1/computers/{c.id}/viewer-ticket").status_code == 200


def test_worker_skips_linux_guest_setup_for_windows(db, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    monkeypatch.setattr(worker, "Session", models.Session)
    c = Computer(workspace_id="w", name="Win", request_id="prov-win-worker", status="starting")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, os="windows", storage_gib=100))
    db.commit()
    monkeypatch.setattr(worker.runtime, "create", AsyncMock(return_value="win-sb"))
    inject, screens = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker.secrets_vault, "inject", inject)
    monkeypatch.setattr(worker.screens, "start_all", screens)
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, c.id).status == "running"
    inject.assert_not_awaited() and screens.assert_not_awaited()
    stop, snapshot = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker.runtime, "stop", stop)
    monkeypatch.setattr(worker.runtime, "save_system", snapshot)
    computer = db.get(Computer, c.id)
    computer.status = "stopping"
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, c.id).status == "stopped"
    stop.assert_awaited_once_with("win-sb")
    snapshot.assert_not_awaited()


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_capability_matrix_is_complete(os_name):
    from desktop_service.providers import LINUX_CAPABILITIES, capabilities

    assert set(capabilities(os_name)) == set(LINUX_CAPABILITIES)


def test_windows_automations_are_lifecycle_only(client, db):
    c = Computer(workspace_id="w", name="Win auto", request_id="prov-win-auto")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, os="windows", storage_gib=100))
    db.commit()
    command = {"name": "x", "trigger": {"kind": "webhook"}, "action": {"kind": "command", "command": "dir"}}
    watcher = {"name": "x", "trigger": {"kind": "process", "process": "explorer"}, "action": {"kind": "stop"}}
    nightly = {"name": "x", "trigger": {"kind": "schedule", "cron": "0 22 * * *"}, "action": {"kind": "stop"}}
    assert client.post(f"/v1/computers/{c.id}/automations", json=command).status_code == 409
    assert client.post(f"/v1/computers/{c.id}/automations", json=watcher).status_code == 409
    assert client.post(f"/v1/computers/{c.id}/automations", json=nightly).status_code == 201

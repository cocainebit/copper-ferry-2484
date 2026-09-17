import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from desktop_service import db as models
from desktop_service import feature_runtime, features
from desktop_service.db import Computer, Member
from desktop_service.feature_models import DesktopProfile, DesktopTemplate, FeatureJob


@pytest.fixture
def fc(db):
    app = FastAPI()
    app.include_router(features.router)
    app.dependency_overrides[models.database] = lambda: db
    return TestClient(
        app, headers={"Authorization": "Bearer local-development-only", "Idempotency-Key": "feature-request-001"}
    )


@pytest.fixture
def source(db):
    c = Computer(workspace_id="w", name="Source", request_id="source-001", system_snapshot_id="saved-source")
    db.add(c)
    db.commit()
    return c


def test_profile_denies_member_and_other_workspace(fc, db, source):
    assert fc.put(f"/v1/computers/{source.id}/profile", json={"cpu": 1, "memory_gib": 2}).status_code == 200
    assert feature_runtime.resource_for(source.id) == {"cpu": "1", "memory": "2Gi"}
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert fc.put(f"/v1/computers/{source.id}/profile", json={"cpu": 2, "memory_gib": 4}).status_code == 403
    assert fc.get(f"/v1/computers/{source.id}/profile").status_code == 200
    source.workspace_id = "other"
    db.commit()
    assert fc.get(f"/v1/computers/{source.id}/profile").status_code == 403


def test_resources_reject_running_and_out_of_plan(fc, db, source):
    assert fc.put(f"/v1/computers/{source.id}/profile", json={"cpu": 8, "memory_gib": 32}).status_code == 422
    source.status = "running"
    db.commit()
    assert fc.put(f"/v1/computers/{source.id}/profile", json={"cpu": 1, "memory_gib": 2}).status_code == 409
    assert fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"}).status_code == 409


def test_clone_idempotency_and_independent_resources(fc, db, source, monkeypatch):
    materialize = AsyncMock(return_value="independent-snapshot")
    monkeypatch.setattr(feature_runtime, "materialize", materialize)
    db.add(DesktopProfile(computer_id=source.id, cpu=1, memory_gib=2))
    db.commit()
    first = fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"})
    assert first.status_code == 202
    assert fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"}).json()["id"] == first.json()["id"]
    assert db.get(Computer, source.id).status == "customizing"
    target = db.get(Computer, first.json()["target_id"])
    assert target.id != source.id and target.status == "copying"
    asyncio.run(features.process_one())
    db.expire_all()
    assert target.status == "stopped" and source.status == "stopped"
    assert target.system_snapshot_id == "independent-snapshot"
    assert source.system_snapshot_id == "saved-source"
    assert feature_runtime.resource_for(target.id) == {"cpu": "1", "memory": "2Gi"}
    materialize.assert_awaited_once_with("saved-source", source_id=source.id, target_id=target.id)


def test_failed_clone_preserves_source_and_consumes_quota(fc, db, source, monkeypatch):
    monkeypatch.setattr(feature_runtime, "materialize", AsyncMock(side_effect=RuntimeError("private-provider-error")))
    result = fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"}).json()
    asyncio.run(features.process_one())
    db.expire_all()
    target = db.get(Computer, result["target_id"])
    assert target.status == "copy_failed"
    assert source.status == "stopped" and source.system_snapshot_id == "saved-source"
    assert "private-provider" not in target.error
    assert (
        fc.post(
            f"/v1/computers/{source.id}/clone",
            json={"name": "Another"},
            headers={"Idempotency-Key": "another-request-001"},
        ).status_code
        == 409
    )


def test_template_omits_home_and_instantiation_is_independent(fc, db, source, monkeypatch):
    materialize = AsyncMock(side_effect=["template-own-snapshot", "consumer-own-snapshot"])
    monkeypatch.setattr(feature_runtime, "materialize", materialize)
    result = fc.post(f"/v1/computers/{source.id}/templates", json={"name": "Tools"}).json()
    asyncio.run(features.process_one())
    db.expire_all()
    template = db.get(DesktopTemplate, result["template_id"])
    assert template.status == "ready"
    materialize.assert_awaited_with("saved-source", source_id=None, target_id=None)
    listed = fc.get("/v1/workspaces/w/templates").json()
    assert listed[0]["includes_home"] is False and "snapshot_id" not in listed[0]
    created = fc.post(
        f"/v1/templates/{template.id}/computers", json={"name": "Fresh"}, headers={"Idempotency-Key": "instantiate-001"}
    )
    assert created.status_code == 202
    # A template is protected from deletion until its consumers are materialized.
    assert fc.delete(f"/v1/templates/{template.id}", headers={"Idempotency-Key": "deletion-001"}).status_code == 409
    asyncio.run(features.process_one())
    db.expire_all()
    target = db.get(Computer, created.json()["target_id"])
    assert target.system_snapshot_id == "consumer-own-snapshot"
    assert template.snapshot_id == "template-own-snapshot"
    materialize.assert_awaited_with("template-own-snapshot", source_id=None, target_id=target.id)


def test_template_cross_workspace_and_quota(fc, db, source):
    t = DesktopTemplate(workspace_id="other", name="Private", status="ready", snapshot_id="secret")
    db.add(t)
    db.commit()
    assert fc.post(f"/v1/templates/{t.id}/computers", json={"name": "Stolen"}).status_code == 403
    assert fc.get("/v1/workspaces/other/templates").status_code == 403
    for n in range(5):
        db.add(DesktopTemplate(workspace_id="w", name=f"Template {n}"))
    db.commit()
    assert fc.post(f"/v1/computers/{source.id}/templates", json={"name": "Too many"}).status_code == 409


def test_copy_adapter_never_shares_source_home(monkeypatch):
    class Helper:
        id = "helper"
        commands = type("Commands", (), {"run": AsyncMock(return_value=type("Result", (), {"error": None})())})()
        kill = AsyncMock()
        close = AsyncMock()

    helper = Helper()
    create = AsyncMock(return_value=helper)
    monkeypatch.setattr(feature_runtime.Sandbox, "create", create)
    monkeypatch.setattr(feature_runtime.runtime, "save_system", AsyncMock(return_value="new-snapshot"))
    assert asyncio.run(feature_runtime.materialize("old-snapshot", "source-id", "target-id")) == "new-snapshot"
    volumes = create.call_args.kwargs["volumes"]
    assert volumes[0].pvc.claim_name == "desktop-source-id" and volumes[0].read_only
    assert volumes[1].pvc.claim_name == "desktop-target-id" and not volumes[1].read_only
    assert volumes[0].pvc.claim_name != volumes[1].pvc.claim_name
    command = helper.commands.run.call_args.args[0]
    assert "20971520" in command and "cp -a -- /mnt/source/. /mnt/target/" in command
    assert "find /mnt/source" not in command
    helper.kill.assert_awaited_once()


def test_stale_interrupted_copy_releases_source_only_after_helper_expiry(fc, db, source):
    from datetime import timedelta

    result = fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"}).json()
    j = db.get(FeatureJob, result["id"])
    j.status = "running"
    db.commit()
    asyncio.run(features.process_one())
    db.expire_all()
    assert source.status == "customizing"
    j.created_at = models.now() - timedelta(minutes=21)
    db.commit()
    asyncio.run(features.process_one())
    db.expire_all()
    assert source.status == "stopped" and j.status == "failed"


def test_template_delete_targets_only_its_snapshot(fc, db, monkeypatch):
    t = DesktopTemplate(workspace_id="w", name="Tools", status="ready", snapshot_id="template-image")
    db.add(t)
    db.add(
        Computer(
            workspace_id="w", name="Existing consumer", request_id="consumer", system_snapshot_id="independent-image"
        )
    )
    db.commit()
    deletion = AsyncMock()
    monkeypatch.setattr(features.runtime, "delete_system", deletion)
    first = fc.delete(f"/v1/templates/{t.id}")
    assert first.status_code == 202
    assert fc.delete(f"/v1/templates/{t.id}").json()["id"] == first.json()["id"]
    asyncio.run(features.process_one())
    db.expire_all()
    assert t.status == "deleted"
    deletion.assert_awaited_once_with("template-image")
    assert (
        db.scalar(select(Computer).where(Computer.request_id == "consumer")).system_snapshot_id == "independent-image"
    )


def test_failed_copy_closes_helper_without_saving_snapshot(monkeypatch):
    helper = type(
        "Helper",
        (),
        {
            "id": "helper",
            "commands": type(
                "Commands", (), {"run": AsyncMock(return_value=type("Result", (), {"error": "copy error"})())}
            )(),
            "kill": AsyncMock(),
            "close": AsyncMock(),
        },
    )()
    monkeypatch.setattr(feature_runtime.Sandbox, "create", AsyncMock(return_value=helper))
    save = AsyncMock()
    monkeypatch.setattr(feature_runtime.runtime, "save_system", save)
    with pytest.raises(RuntimeError, match="Home copy failed"):
        asyncio.run(feature_runtime.materialize("old", "source", "target"))
    save.assert_not_awaited()
    helper.kill.assert_awaited_once()
    helper.close.assert_awaited_once()


@pytest.mark.parametrize("action", ["start", "stop", "take-control", "resume", "heartbeat"])
def test_copy_failed_cannot_bypass_protection_with_any_action(client, db, source, action):
    source.status = "copy_failed"
    db.commit()
    result = client.post(f"/v1/computers/{source.id}/actions/{action}")
    assert result.status_code == 409
    db.refresh(source)
    assert source.status == "copy_failed"


def test_copy_failed_can_be_deleted(client, db, source):
    source.status = "copy_failed"
    db.commit()
    assert client.delete(f"/v1/computers/{source.id}", params={"confirm": source.name}).status_code == 200
    db.refresh(source)
    assert source.status == "deleting"


def test_crypto_prepaid_access_allows_second_saved_computer(fc, db, source):
    from desktop_service.db import Workspace
    from desktop_service.platform_credits import grant

    workspace = db.get(Workspace, "w")
    workspace.subscription = "inactive"
    workspace.included = 0
    grant(db, "w", 1_000_000, "crypto-feature-fixture", "test funding")
    db.commit()
    response = fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Prepaid copy"})
    assert response.status_code == 202


@pytest.mark.parametrize("overrides,expected", [({}, (2, 4)), ({"cpu": 1, "memory_gib": 2}, (1, 2))])
def test_template_resource_selection(fc, db, overrides, expected):
    template = DesktopTemplate(
        workspace_id="w", name="Ready", status="ready", snapshot_id="snapshot", cpu=2, memory_gib=4
    )
    db.add(template)
    db.commit()
    response = fc.post(f"/v1/templates/{template.id}/computers", json={"name": "Custom", **overrides})
    assert response.status_code == 202
    profile = db.get(DesktopProfile, response.json()["target_id"])
    assert (profile.cpu, profile.memory_gib) == expected


def test_resolution_validation_and_preservation(fc, db, source):
    endpoint = f"/v1/computers/{source.id}/profile"
    assert fc.put(endpoint, json={"cpu": 1, "memory_gib": 2, "resolution": "1920x1080"}).status_code == 200
    assert fc.get(endpoint).json()["resolution"] == "1920x1080"
    assert fc.put(endpoint, json={"cpu": 2, "memory_gib": 4}).json()["resolution"] == "1920x1080"
    assert fc.put(endpoint, json={"resolution": "9000x9000"}).status_code == 422
    source.status = "running"
    db.commit()
    assert fc.put(endpoint, json={"resolution": "1280x720"}).status_code == 409


def test_clone_and_template_preserve_resolution(fc, db, source):
    db.add(DesktopProfile(computer_id=source.id, resolution="1280x720"))
    db.commit()
    result = fc.post(f"/v1/computers/{source.id}/clone", json={"name": "Copy"}).json()
    assert db.get(DesktopProfile, result["target_id"]).resolution == "1280x720"
    source.status = "stopped"
    db.commit()
    result = fc.post(
        f"/v1/computers/{source.id}/templates",
        json={"name": "Template"},
        headers={"Idempotency-Key": "resolution-template"},
    ).json()
    assert db.get(DesktopTemplate, result["template_id"]).resolution == "1280x720"


def test_resolution_upgrade_preserves_legacy_rows(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text

    from desktop_service import upgrade

    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.db"))
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE desktop_profiles (computer_id VARCHAR PRIMARY KEY, cpu INTEGER, memory_gib INTEGER)")
        )
        connection.execute(text("INSERT INTO desktop_profiles VALUES ('legacy', 1, 2)"))
        connection.execute(
            text(
                "CREATE TABLE desktop_templates (id VARCHAR PRIMARY KEY, workspace_id VARCHAR, name VARCHAR, status VARCHAR, snapshot_id VARCHAR, cpu INTEGER, memory_gib INTEGER, created_at DATETIME)"
            )
        )
        connection.execute(text("INSERT INTO desktop_templates (id, cpu, memory_gib) VALUES ('template', 2, 4)"))
    monkeypatch.setattr(upgrade, "engine", engine)
    upgrade.upgrade()
    upgrade.upgrade()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT cpu, memory_gib, resolution FROM desktop_profiles")).one() == (
            1,
            2,
            "1440x900",
        )
        assert connection.execute(text("SELECT resolution FROM desktop_templates")).scalar() == "1440x900"
    engine.dispose()

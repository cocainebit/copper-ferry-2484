import asyncio
import json
import subprocess
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from desktop_service import db as models
from desktop_service import feature_runtime, features, template_registry
from desktop_service.db import Computer, Member
from desktop_service.feature_models import DesktopProfile, DesktopTemplate, FeatureJob
from desktop_service.secrets_vault import Secret
from desktop_service.security import seal
from desktop_service.template_registry import TemplateSpec, build_script, digest, ordered_apps


@pytest.fixture
def rc(db):
    app = FastAPI()
    app.include_router(template_registry.router)
    app.include_router(features.router)
    app.dependency_overrides[models.database] = lambda: db
    return TestClient(app, headers={"Authorization": "Bearer local-development-only"})


def publish(rc, name, spec, key):
    return rc.post(
        "/v1/workspaces/w/template-definitions", json={"name": name, "spec": spec}, headers={"Idempotency-Key": key}
    )


def test_starters_are_valid_specs(rc):
    starters = rc.get("/v1/template-starters").json()
    assert {s["id"] for s in starters} >= {"web-research", "python-data", "agent-dev", "office"}
    for starter in starters:
        assert starter["digest"] == digest(TemplateSpec(**starter["spec"]))


def test_digest_is_canonical_and_versions_are_immutable(rc, db):
    first = publish(rc, "Research", {"apps": ["firefox"], "packages": ["jq"]}, "publish-0001")
    assert first.status_code == 202 and first.json()["built"]
    v1 = first.json()["template"]
    assert v1["version"] == 1 and v1["status"] == "building" and v1["definition_id"] == v1["id"]
    same = publish(rc, "Research", {"packages": ["jq"], "apps": ["firefox"]}, "publish-0002")
    assert not same.json()["built"] and same.json()["template"]["id"] == v1["id"]
    changed = publish(rc, "Research", {"apps": ["firefox"], "packages": ["jq", "pandoc"]}, "publish-0003").json()
    assert changed["built"] and changed["template"]["version"] == 2
    assert changed["template"]["definition_id"] == v1["id"] and changed["template"]["digest"] != v1["digest"]
    replay = publish(rc, "Research", {"apps": ["vlc"]}, "publish-0003").json()
    assert replay["template"]["id"] == changed["template"]["id"]
    jobs = db.scalars(select(FeatureJob).where(FeatureJob.kind == "build")).all()
    assert len(jobs) == 2
    listed = rc.get("/v1/workspaces/w/template-definitions").json()
    assert [(d["name"], [v["version"] for v in d["versions"]]) for d in listed] == [("Research", [2, 1])]
    detail = rc.get(f"/v1/templates/{v1['id']}").json()
    assert detail["spec"]["apps"] == ["firefox"] and detail["build_log"] == ""


@pytest.mark.parametrize(
    "spec",
    [
        {"apps": ["not-an-app"]},
        {"packages": ["bad name; rm -rf /"]},
        {"files": [{"path": "/home/desktop/.bashrc", "content": "x"}]},
        {"files": [{"path": "relative/path", "content": "x"}]},
        {"files": [{"path": "/etc/../root/x", "content": "x"}]},
        {"env": {"HOME": "/tmp"}},
        {"env": {"lower": "x"}},
        {"requires_secrets": ["PATH"]},
        {"run": ["   "]},
        {"cpu": 8},
    ],
)
def test_spec_validation(spec):
    with pytest.raises(ValidationError):
        TemplateSpec(**spec)


def test_publish_is_owner_only(rc, db):
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert publish(rc, "Nope", {}, "publish-owner").status_code == 403
    assert rc.get("/v1/workspaces/w/template-definitions").status_code == 200


def test_prerequisites_are_pulled_in_order():
    assert ordered_apps(["openclaw", "vscode"]) == ["nodejs", "openclaw", "vscode"]
    assert ordered_apps(["nodejs", "openclaw"]) == ["nodejs", "openclaw"]


def test_build_script_is_valid_shell_and_contains_every_part():
    spec = TemplateSpec(
        apps=["openclaw"],
        packages=["jq"],
        files=[{"path": "/etc/cubicle/it's.conf", "content": "a='b' $HOME", "mode": "0600"}],
        run=["echo 'hello' > /opt/marker"],
        startup=["xterm -e htop"],
        env={"GREETING": "it's here"},
    )
    script = build_script("Box", 3, spec)
    assert subprocess.run(["sh", "-n"], input=script, text=True).returncode == 0
    assert script.index("nodesource") < script.index("npm install -g openclaw")
    assert "apt-get install -y --no-install-recommends jq" in script
    assert "/etc/xdg/autostart/cubicle-startup.desktop" in script and "/opt/cubicle/startup.sh" in script
    assert "sh -euc 'echo '\"'\"'hello'\"'\"' > /opt/marker'" in script
    assert script.rstrip().endswith("echo '== build complete'")
    assert json.dumps({"name": "Box", "version": 3, "digest": digest(spec)}) not in script  # base64 encoded


def test_worker_builds_version_and_records_log(rc, db, monkeypatch):
    build = AsyncMock(return_value=("built-snapshot", "== packages\n== build complete"))
    monkeypatch.setattr(feature_runtime, "build", build)
    v = publish(rc, "Tools", {"packages": ["jq"]}, "publish-build").json()["template"]
    asyncio.run(features.process_one())
    db.expire_all()
    t = db.get(DesktopTemplate, v["id"])
    assert t.status == "ready" and t.snapshot_id == "built-snapshot" and "build complete" in t.build_log
    assert "apt-get install -y --no-install-recommends jq" in build.await_args.args[0]


def test_failed_build_keeps_log_and_can_be_retried(rc, db, monkeypatch):
    monkeypatch.setattr(
        feature_runtime, "build", AsyncMock(side_effect=feature_runtime.BuildFailed("E: Unable to locate package"))
    )
    v = publish(rc, "Broken", {"packages": ["does-not-exist"]}, "publish-fail").json()["template"]
    asyncio.run(features.process_one())
    db.expire_all()
    t = db.get(DesktopTemplate, v["id"])
    assert t.status == "failed" and "Unable to locate" in t.build_log and t.snapshot_id is None
    assert rc.post(f"/v1/templates/{t.id}/rebuild", headers={"Idempotency-Key": "rebuild-01"}).status_code == 202
    db.expire_all()
    assert t.status == "building"
    assert rc.post(f"/v1/templates/{t.id}/rebuild", headers={"Idempotency-Key": "rebuild-02"}).status_code == 409


def test_required_secrets_gate_instantiation(rc, db):
    t = DesktopTemplate(
        workspace_id="w",
        name="Agent box",
        status="ready",
        snapshot_id="snap",
        definition_id="def",
        version=1,
        requires_secrets=["ANTHROPIC_API_KEY"],
        storage_gib=50,
    )
    db.add(t)
    db.commit()
    create = lambda key: rc.post(  # noqa: E731
        f"/v1/templates/{t.id}/computers", json={"name": "From def"}, headers={"Idempotency-Key": key}
    )
    blocked = create("instantiate-1")
    assert blocked.status_code == 409 and "ANTHROPIC_API_KEY" in blocked.json()["detail"]
    assert rc.get(f"/v1/templates/{t.id}").json()["missing_secrets"] == ["ANTHROPIC_API_KEY"]
    db.add(Secret(workspace_id="w", name="ANTHROPIC_API_KEY", encrypted_value=seal("sk"), created_by="local-user"))
    db.commit()
    created = create("instantiate-2")
    assert created.status_code == 202
    assert db.get(DesktopProfile, created.json()["target_id"]).storage_gib == 50


def test_definition_versions_do_not_consume_snapshot_template_quota(rc, db):
    source = Computer(workspace_id="w", name="Src", request_id="quota-src", system_snapshot_id="saved")
    db.add(source)
    for n in range(5):
        db.add(DesktopTemplate(workspace_id="w", name=f"Built {n}", definition_id=f"d{n}", version=1, status="ready"))
    db.commit()
    response = rc.post(
        f"/v1/computers/{source.id}/templates", json={"name": "Saved"}, headers={"Idempotency-Key": "quota-save-1"}
    )
    assert response.status_code == 202


def test_definition_limit(rc, db):
    for n in range(template_registry.MAX_DEFINITIONS):
        db.add(DesktopTemplate(workspace_id="w", name=f"Def {n}", definition_id=f"d{n}", version=1, status="ready"))
    db.commit()
    assert publish(rc, "One too many", {}, "publish-limit").status_code == 409
    assert publish(rc, "Def 0", {"packages": ["jq"]}, "publish-new-version").status_code == 202

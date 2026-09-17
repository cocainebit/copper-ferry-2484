import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import apps, runtime
from desktop_service.apps import AppInstall
from desktop_service.db import Computer, Event, Member, now


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Live", request_id="apps-001", status="running", sandbox_id="sb-apps")
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def execute(monkeypatch):
    fake = AsyncMock(return_value="")
    monkeypatch.setattr(runtime, "execute", fake)
    return fake


def test_catalog_is_public_and_consistent(client):
    body = client.get("/v1/apps").json()
    ids = [a["id"] for a in body]
    assert "vscode" in ids and "firefox" in ids and len(ids) == len(set(ids))
    for app in apps.CATALOG:
        assert app["install"] and app["check"]
        for requirement in app.get("requires", []):
            assert requirement in apps.BY_ID
    assert next(a for a in body if a["id"] == "openclaw")["requires"] == ["nodejs"]
    assert "install" not in body[0] and "check" not in body[0]


def test_install_runs_detached_recipe_and_worker_mirrors_completion(client, db, running, execute):
    response = client.post(f"/v1/computers/{running.id}/apps/firefox/install")
    assert response.status_code == 202
    install_id = response.json()["id"]
    command = execute.await_args.args[1]
    assert execute.await_args.args[0] == "sb-apps"
    assert f"/opt/cubicle/apps/{install_id}.sh" in command and "nohup sh -c" in command
    assert "apt-get install -y --no-install-recommends firefox-esr" in command
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/install").status_code == 409
    listed = {a["id"]: a for a in client.get(f"/v1/computers/{running.id}/apps").json()}
    assert listed["firefox"]["install"]["status"] == "installing" and listed["vscode"]["install"] is None
    execute.return_value = "Reading package lists...\nSetting up firefox-esr\n__CUBICLE_EXIT__=0\n\n__POLL__\n0\n"
    asyncio.run(apps.poll(db, running))
    row = db.get(AppInstall, install_id)
    assert row.status == "installed" and "Setting up firefox-esr" in row.log
    assert any(e.text == "Firefox ESR installed" for e in db.scalars(select(Event)))
    assert execute.await_args.args[1] == apps.poll_command(install_id)


def test_poll_throttles_and_reports_failures(db, running, execute):
    row = AppInstall(computer_id=running.id, app_id="gimp", status="installing", updated_at=now())
    db.add(row)
    db.commit()
    asyncio.run(apps.poll(db, running))
    execute.assert_not_awaited()
    row.updated_at = now() - timedelta(seconds=6)
    db.commit()
    execute.return_value = "E: Unable to locate package\n__POLL__\n100\n"
    asyncio.run(apps.poll(db, running))
    db.refresh(row)
    assert row.status == "failed" and "status 100" in row.error
    assert any("GIMP install failed" in e.text for e in db.scalars(select(Event)))


def test_prerequisites_owner_and_running_rules(client, db, running, execute):
    assert client.post(f"/v1/computers/{running.id}/apps/openclaw/install").status_code == 409
    db.add(AppInstall(computer_id=running.id, app_id="nodejs", status="installed"))
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/apps/openclaw/install").status_code == 202
    assert client.post(f"/v1/computers/{running.id}/apps/nope/install").status_code == 404
    running.status = "stopped"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/install").status_code == 409
    running.status = "running"
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/install").status_code == 403
    assert client.get(f"/v1/computers/{running.id}/apps").status_code == 200


def test_launch_remove_and_check(client, db, running, execute):
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/launch").status_code == 409
    db.add(AppInstall(computer_id=running.id, app_id="firefox", status="installed"))
    db.add(AppInstall(computer_id=running.id, app_id="nodejs", status="installed"))
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/launch").status_code == 200
    assert "runuser -u desktop" in execute.await_args.args[1] and "firefox-esr" in execute.await_args.args[1]
    assert client.post(f"/v1/computers/{running.id}/apps/nodejs/launch").status_code == 404
    execute.return_value = "firefox=ok\nnodejs=missing\n"
    assert client.post(f"/v1/computers/{running.id}/apps/check").json() == {"checked": 2, "missing": ["nodejs"]}
    latest = apps.current(db, running.id)
    assert latest["nodejs"].status == "failed" and latest["firefox"].status == "installed"
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/remove").status_code == 202
    assert "apt-get remove -y firefox-esr" in execute.await_args.args[1]
    assert apps.current(db, running.id)["firefox"].status == "removing"
    assert client.post(f"/v1/computers/{running.id}/apps/firefox/launch").status_code == 409


def test_poll_command_never_fails_while_running():
    command = apps.poll_command("abc")
    assert command.rstrip().endswith("; true")


def test_worker_keeps_metering_when_app_polling_fails(db, running, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "keep_alive", AsyncMock())
    monkeypatch.setattr(apps, "poll", AsyncMock(side_effect=RuntimeError("1")))
    running.metered_at = now() - timedelta(minutes=2)
    running.last_active = now()
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert running.status == "running" and running.error is None
    assert running.metered_at > now() - timedelta(minutes=1)

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from desktop_service import automations, runtime
from desktop_service.automations import Action, Automation, AutomationRun, Trigger
from desktop_service.cron import Cron, CronError
from desktop_service.db import Computer, Credential, Event, Member, Run, now
from desktop_service.security import seal


@pytest.fixture
def computer(db):
    c = Computer(workspace_id="w", name="Auto", request_id="auto-001", status="running", sandbox_id="sb-auto")
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def execute(monkeypatch):
    fake = AsyncMock(return_value="")
    monkeypatch.setattr(runtime, "execute", fake)
    return fake


def create(client, cid, **body):
    payload = {"name": "Job", **body}
    return client.post(f"/v1/computers/{cid}/automations", json=payload)


def tick():
    asyncio.run(automations.tick())


# Cron ------------------------------------------------------------------------------------------------


def test_cron_fields_steps_lists_and_names():
    cron = Cron("*/15 9-17 * * mon-fri")
    assert cron.next_after(datetime(2026, 9, 18, 17, 50)) == datetime(2026, 9, 21, 9, 0)  # Fri evening to Mon
    assert Cron("0 0 1,15 * *").next_after(datetime(2026, 9, 2)) == datetime(2026, 9, 15)
    assert Cron("30 2 * * 7").next_after(datetime(2026, 9, 17)) == datetime(2026, 9, 20, 2, 30)  # Sunday as 7
    assert Cron("0 12 29 feb *").next_after(datetime(2026, 3, 1)) == datetime(2028, 2, 29, 12, 0)


def test_cron_day_of_month_or_weekday_rule_and_time_zone():
    cron = Cron("0 8 1 * mon")
    # 2026-09-21 is a Monday and not the 1st: matches because either field may match.
    assert cron.next_after(datetime(2026, 9, 19)) == datetime(2026, 9, 21, 8, 0)
    sao_paulo = Cron("0 9 * * *", "America/Sao_Paulo")  # UTC-3
    assert sao_paulo.next_after(datetime(2026, 9, 17, 11, 0)) == datetime(2026, 9, 17, 12, 0)


@pytest.mark.parametrize("expression", ["* * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "5-1 * * * *", "x * * * *"])
def test_cron_rejects_invalid(expression):
    with pytest.raises(CronError):
        Cron(expression)


def test_trigger_validation():
    with pytest.raises(ValidationError):
        Trigger(kind="schedule", cron="* * * * *")  # every minute is too frequent
    with pytest.raises(ValidationError):
        Trigger(kind="schedule", cron="0 9 * * *", timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Trigger(kind="interval", every_minutes=1)
    with pytest.raises(ValidationError):
        Trigger(kind="file", path="/etc/passwd")
    with pytest.raises(ValidationError):
        Trigger(kind="process", process="bad name;")
    with pytest.raises(ValidationError):
        Action(kind="command", command="  ")
    assert Trigger(kind="schedule", cron="*/5 * * * *").cron == "*/5 * * * *"


# API -------------------------------------------------------------------------------------------------


def test_crud_owner_only_and_limits(client, db, computer):
    body = {"trigger": {"kind": "interval", "every_minutes": 30}, "action": {"kind": "command", "command": "date"}}
    created = create(client, computer.id, **body)
    assert created.status_code == 201 and created.json()["next_fire_at"]
    aid = created.json()["id"]
    assert client.get(f"/v1/computers/{computer.id}/automations").json()[0]["id"] == aid
    assert client.patch(f"/v1/automations/{aid}", json={"enabled": False}).json()["enabled"] is False
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert create(client, computer.id, **body).status_code == 403
    assert client.get(f"/v1/computers/{computer.id}/automations").status_code == 200
    membership.role = "owner"
    db.commit()
    for _ in range(automations.MAX_PER_COMPUTER - 1):
        assert create(client, computer.id, **body).status_code == 201
    assert create(client, computer.id, **body).status_code == 409
    assert client.delete(f"/v1/automations/{aid}").json() == {"ok": True}
    computer.workspace_id = "other"
    db.commit()
    assert client.get(f"/v1/computers/{computer.id}/automations").status_code == 403


def test_webhook_token_is_shown_once_and_required(client, db, computer):
    body = {"trigger": {"kind": "webhook"}, "action": {"kind": "command", "command": "echo hook"}}
    created = create(client, computer.id, **body).json()
    token = created["webhook_token"]
    assert token.startswith("cbh_") and created["webhook_path"] == f"/v1/hooks/{created['id']}"
    assert "webhook_token" not in client.get(f"/v1/computers/{computer.id}/automations").json()[0]
    from fastapi.testclient import TestClient

    from desktop_service.main import app

    anonymous = TestClient(app)
    assert anonymous.post(f"/v1/hooks/{created['id']}").status_code == 404
    assert anonymous.post(f"/v1/hooks/{created['id']}", headers={"X-Cubicle-Token": "cbh_wrong"}).status_code == 404
    first = anonymous.post(
        f"/v1/hooks/{created['id']}", headers={"X-Cubicle-Token": token, "Idempotency-Key": "delivery-1"}
    )
    assert first.status_code == 202 and first.json()["reason"] == "Webhook call"
    repeat = anonymous.post(
        f"/v1/hooks/{created['id']}", headers={"X-Cubicle-Token": token, "Idempotency-Key": "delivery-1"}
    )
    assert repeat.status_code == 202 and repeat.json()["id"] == first.json()["id"]  # retries replay
    burst = anonymous.post(
        f"/v1/hooks/{created['id']}", headers={"X-Cubicle-Token": token, "Idempotency-Key": "delivery-2"}
    )
    assert burst.status_code == 429
    assert len(db.scalars(select(AutomationRun)).all()) == 1


# Worker ----------------------------------------------------------------------------------------------


def test_schedule_fires_latest_slot_once_without_backfill(client, db, computer, execute):
    body = {"trigger": {"kind": "interval", "every_minutes": 10}, "action": {"kind": "stop"}}
    aid = create(client, computer.id, **body).json()["id"]
    a = db.get(Automation, aid)
    a.next_fire_at = now() - timedelta(minutes=35)  # three and a half intervals missed
    db.commit()
    tick()
    db.expire_all()
    runs = db.scalars(select(AutomationRun)).all()
    assert len(runs) == 1 and runs[0].status == "succeeded"
    assert a.next_fire_at > now()
    assert db.get(Computer, computer.id).status == "stopping"
    tick()
    assert len(db.scalars(select(AutomationRun)).all()) == 1


def test_command_runs_detached_and_captures_exit(client, db, computer, execute):
    body = {"trigger": {"kind": "webhook"}, "action": {"kind": "command", "command": "echo hi"}}
    aid = create(client, computer.id, **body).json()["id"]
    run = client.post(f"/v1/automations/{aid}/run").json()
    tick()
    command = execute.await_args.args[1]
    assert f"/opt/cubicle/automations/{run['id']}.sh" in command and ". /etc/profile" in command
    assert db.get(AutomationRun, run["id"]).status == "running"
    execute.return_value = "hi\n__CUBICLE_EXIT__=0\n__POLL__\n0\n"
    tick()
    db.expire_all()
    r = db.get(AutomationRun, run["id"])
    assert r.status == "succeeded" and "hi" in r.output and r.finished_at
    second = client.post(f"/v1/automations/{aid}/run").json()
    execute.return_value = ""
    tick()
    execute.return_value = "boom\n__POLL__\n2\n"
    tick()
    db.expire_all()
    failed = db.get(AutomationRun, second["id"])
    assert failed.status == "failed" and failed.error == "Exit status 2"


def test_stopped_computer_is_started_when_allowed_otherwise_skipped(client, db, computer, execute):
    computer.status, computer.sandbox_id = "stopped", None
    db.commit()
    body = {"trigger": {"kind": "webhook"}, "action": {"kind": "command", "command": "date"}}
    skipped = create(client, computer.id, **body).json()["id"]
    starter = create(client, computer.id, start_if_stopped=True, **body).json()["id"]
    first = client.post(f"/v1/automations/{skipped}/run").json()
    second = client.post(f"/v1/automations/{starter}/run").json()
    tick()
    db.expire_all()
    assert db.get(AutomationRun, first["id"]).status == "skipped"
    waiting = db.get(AutomationRun, second["id"])
    assert waiting.status == "waiting_computer" and db.get(Computer, computer.id).status == "starting"
    computer = db.get(Computer, computer.id)
    computer.status, computer.sandbox_id = "running", "sb-started"
    db.commit()
    tick()
    db.expire_all()
    assert db.get(AutomationRun, second["id"]).status == "running"
    assert execute.await_args.args[0] == "sb-started"


def test_agent_task_creates_run_and_tracks_completion(client, db, computer, execute):
    body = {"trigger": {"kind": "webhook"}, "action": {"kind": "agent_task", "prompt": "Summarize the news"}}
    aid = create(client, computer.id, **body).json()["id"]
    missing_key = client.post(f"/v1/automations/{aid}/run").json()
    tick()
    db.expire_all()
    assert "Anthropic" in db.get(AutomationRun, missing_key["id"]).error
    db.add(Credential(workspace_id="w", encrypted_key=seal("sk-ant-test"), suffix="test"))
    db.commit()
    run = client.post(f"/v1/automations/{aid}/run").json()
    tick()
    db.expire_all()
    r = db.get(AutomationRun, run["id"])
    task = db.get(Run, r.run_id)
    assert r.status == "running" and task.prompt == "Summarize the news" and task.status == "queued"
    task.status = "completed"
    db.commit()
    tick()
    db.expire_all()
    assert db.get(AutomationRun, run["id"]).status == "succeeded"


def test_file_watch_needs_baseline_then_fires_on_change(client, db, computer, execute):
    body = {"trigger": {"kind": "file", "path": "Inbox/new.csv"}, "action": {"kind": "command", "command": "wc -l"}}
    aid = create(client, computer.id, **body).json()["id"]
    execute.return_value = "absent"
    tick()
    assert "stat -c %Y:%s /home/desktop/Inbox/new.csv" in execute.await_args_list[0].args[1]
    assert not db.scalars(select(AutomationRun)).all()
    a = db.get(Automation, aid)
    a.watched_at = now() - timedelta(minutes=1)
    db.commit()
    execute.return_value = "1789000000:120"
    tick()
    db.expire_all()
    runs = db.scalars(select(AutomationRun)).all()
    assert len(runs) == 1 and runs[0].reason == "Inbox/new.csv changed"


def test_process_watch_fires_when_process_stops(client, db, computer, execute):
    body = {"trigger": {"kind": "process", "process": "chromium"}, "action": {"kind": "command", "command": "true"}}
    aid = create(client, computer.id, **body).json()["id"]
    execute.return_value = "running"
    tick()
    a = db.get(Automation, aid)
    a.watched_at = now() - timedelta(minutes=1)
    db.commit()
    execute.return_value = "stopped"
    tick()
    db.expire_all()
    assert db.scalar(select(AutomationRun)).reason == "chromium stopped"


def test_timeouts_and_isolation(client, db, computer, execute):
    body = {"trigger": {"kind": "webhook"}, "action": {"kind": "command", "command": "sleep 999"}, "timeout_minutes": 1}
    aid = create(client, computer.id, **body).json()["id"]
    run = client.post(f"/v1/automations/{aid}/run").json()
    tick()
    r = db.get(AutomationRun, run["id"])
    r.started_at = now() - timedelta(minutes=2)
    db.commit()
    tick()
    db.expire_all()
    assert db.get(AutomationRun, run["id"]).error == "Timed out after 1 minutes"
    execute.side_effect = RuntimeError("execd unavailable")
    broken = client.post(f"/v1/automations/{aid}/run").json()
    tick()
    db.expire_all()
    assert db.get(AutomationRun, broken["id"]).status == "failed"
    assert any("Automation Job failed" in e.text for e in db.scalars(select(Event)))

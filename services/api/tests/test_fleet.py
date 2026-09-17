import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import automations, runtime
from desktop_service.automations import Automation, AutomationRun
from desktop_service.config import settings
from desktop_service.db import Computer, Event, Ledger, Member, Run, Workspace, now
from desktop_service.feature_models import DesktopProfile


def make(db, name, status="stopped", wid="w", labels=None):
    c = Computer(workspace_id=wid, name=name, request_id="fleet-" + name, status=status, labels=labels)
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, cpu=1, memory_gib=2))
    db.commit()
    return c


def test_overview_filters_and_real_usage(client, db):
    a = make(db, "Research box", status="running", labels=["research", "prod"])
    b = make(db, "Build box", labels=["ci"])
    for minute in range(3):
        db.add(Ledger(id=f"usage:{a.id}:{minute}", workspace_id="w", amount=-1, reason="computer-minute"))
    old = Ledger(id=f"usage:{b.id}:1", workspace_id="w", amount=-1, reason="computer-minute")
    old.created_at = now() - timedelta(days=2)
    db.add(old)
    db.commit()
    body = client.get("/v1/workspaces/w/fleet").json()
    summary = body["summary"]
    assert summary["by_status"] == {"running": 1, "stopped": 1}
    assert summary["usage_24h_minutes"] == 3 and summary["labels"] == ["ci", "prod", "research"]
    assert summary["limits"] == {"plan": "paid", "saved": 2, "running": 1}
    assert summary["host"]["max_desktops"] == settings().max_desktops
    rows = {c["name"]: c for c in body["computers"]}
    assert rows["Research box"]["usage_24h_minutes"] == 3 and rows["Build box"]["usage_24h_minutes"] == 0
    assert rows["Research box"]["cpu"] == 1 and rows["Research box"]["screens"] == 1
    assert [c["name"] for c in client.get("/v1/workspaces/w/fleet?q=research").json()["computers"]] == ["Research box"]
    assert [c["name"] for c in client.get("/v1/workspaces/w/fleet?q=ci").json()["computers"]] == ["Build box"]
    assert [c["name"] for c in client.get("/v1/workspaces/w/fleet?status=stopped").json()["computers"]] == ["Build box"]
    assert client.get("/v1/workspaces/w/fleet?label=prod").json()["computers"][0]["name"] == "Research box"
    assert client.get("/v1/workspaces/other/fleet").status_code == 403


def test_labels_are_normalized_and_validated(client, db):
    c = make(db, "Labelled")
    assert client.put(f"/v1/computers/{c.id}/labels", json={"labels": ["Prod", "prod", "team-a"]}).json() == {
        "labels": ["prod", "team-a"]
    }
    assert client.put(f"/v1/computers/{c.id}/labels", json={"labels": ["bad label"]}).status_code == 422
    assert client.put(f"/v1/computers/{c.id}/labels", json={"labels": [f"l{i}" for i in range(9)]}).status_code == 422
    assert client.get("/v1/workspaces/w/computers").json()[0]["labels"] == ["prod", "team-a"]


def test_bulk_reports_per_item_outcomes_and_respects_limits(client, db):
    a = make(db, "One")
    b = make(db, "Two")
    foreign = make(db, "Foreign", wid="other")
    result = client.post(
        "/v1/workspaces/w/computers/bulk", json={"ids": [a.id, b.id, foreign.id, a.id], "action": "start"}
    ).json()
    outcomes = {r["id"]: r for r in result["results"]}
    assert len(result["results"]) == 3
    assert outcomes[a.id]["ok"] and outcomes[a.id]["status"] == "starting"
    assert not outcomes[b.id]["ok"] and "one running computer" in outcomes[b.id]["error"]
    assert not outcomes[foreign.id]["ok"]
    labelled = client.post(
        "/v1/workspaces/w/computers/bulk", json={"ids": [a.id, b.id], "action": "add_label", "label": "batch"}
    ).json()
    assert labelled["succeeded"] == 2
    removed = client.post(
        "/v1/workspaces/w/computers/bulk", json={"ids": [b.id], "action": "remove_label", "label": "batch"}
    ).json()
    assert removed["results"][0]["labels"] == []
    stop = client.post("/v1/workspaces/w/computers/bulk", json={"ids": [a.id], "action": "stop"}).json()
    assert stop["results"][0]["status"] == "stopping"


def test_configurable_limits(client, db, monkeypatch):
    s = settings()
    monkeypatch.setattr(s, "paid_running_computers", 2)
    monkeypatch.setattr(s, "paid_saved_computers", 3)
    for name in ("A", "B", "C"):
        make(db, name)
    ids = [c["id"] for c in client.get("/v1/workspaces/w/fleet").json()["computers"]]
    result = client.post("/v1/workspaces/w/computers/bulk", json={"ids": ids, "action": "start"}).json()
    assert [r["ok"] for r in result["results"]] == [True, True, False]
    assert "at most 2 computers" in result["results"][2]["error"]
    created = client.post(
        "/v1/workspaces/w/computers", json={"name": "Fourth"}, headers={"Idempotency-Key": "fleet-limit-4"}
    )
    assert created.status_code == 409


def test_move_between_owned_workspaces(client, db):
    c = make(db, "Mover", labels=["x"])
    db.add(Member(workspace_id="other", user_id="local-user", email="you@localhost", role="owner"))
    db.commit()
    automation = client.post(
        f"/v1/computers/{c.id}/automations",
        json={"name": "Nightly", "trigger": {"kind": "interval", "every_minutes": 60}, "action": {"kind": "stop"}},
    ).json()
    c.status = "running"
    db.commit()
    assert client.post(f"/v1/computers/{c.id}/move", json={"workspace_id": "other"}).status_code == 409
    c.status = "stopped"
    db.add(Run(computer_id=c.id, prompt="busy", request_id="move-run", status="queued"))
    db.commit()
    assert client.post(f"/v1/computers/{c.id}/move", json={"workspace_id": "other"}).status_code == 409
    db.scalar(select(Run)).status = "completed"
    db.commit()
    assert client.post(f"/v1/computers/{c.id}/move", json={"workspace_id": "w"}).status_code == 409
    moved = client.post(f"/v1/computers/{c.id}/move", json={"workspace_id": "other"})
    assert moved.status_code == 200 and moved.json()["workspace_id"] == "other"
    db.expire_all()
    assert db.get(Automation, automation["id"]).workspace_id == "other"
    assert any("Moved from workspace" in e.text for e in db.scalars(select(Event)))
    assert [x["name"] for x in client.get("/v1/workspaces/other/fleet").json()["computers"]] == ["Mover"]


def test_move_requires_owner_of_target(client, db):
    c = make(db, "Stuck")
    db.add(Member(workspace_id="other", user_id="local-user", email="you@localhost", role="member"))
    db.commit()
    assert client.post(f"/v1/computers/{c.id}/move", json={"workspace_id": "other"}).status_code == 403


def test_automation_start_respects_running_limit(client, db, monkeypatch):
    monkeypatch.setattr(runtime, "execute", AsyncMock(return_value=""))
    make(db, "Busy", status="running")
    idle = make(db, "Idle")
    aid = client.post(
        f"/v1/computers/{idle.id}/automations",
        json={"name": "Wake", "trigger": {"kind": "webhook"}, "action": {"kind": "start"}},
    ).json()["id"]
    run = client.post(f"/v1/automations/{aid}/run").json()
    asyncio.run(automations.tick())
    db.expire_all()
    r = db.get(AutomationRun, run["id"])
    assert r.status == "skipped" and "one running computer" in r.error
    assert db.get(Computer, idle.id).status == "stopped"


def test_worker_marks_capacity_wait_and_clears_it(db, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(settings(), "max_desktops", 1)
    make(db, "Holder", status="running", wid="other")
    waiting = make(db, "Waiter", status="starting")
    monkeypatch.setattr(worker.runtime, "keep_alive", AsyncMock())
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, waiting.id).error == worker.WAITING_FOR_CAPACITY
    db.get(Workspace, "other")
    holder = db.scalar(select(Computer).where(Computer.name == "Holder"))
    holder.status = "stopped"
    db.commit()
    monkeypatch.setattr(worker.runtime, "create", AsyncMock(return_value="sb"))
    monkeypatch.setattr(worker.secrets_vault, "inject", AsyncMock())
    monkeypatch.setattr(worker.screens, "start_all", AsyncMock())
    asyncio.run(worker.reconcile())
    db.expire_all()
    started = db.get(Computer, waiting.id)
    assert started.status == "running" and started.error is None


@pytest.mark.parametrize("scope,expected", [(["read"], 403), (["manage"], 200)])
def test_fleet_mutations_need_manage_scope(client, db, scope, expected):
    from fastapi.testclient import TestClient

    from desktop_service.main import app

    c = make(db, "Scoped")
    key = client.post("/v1/workspaces/w/api-keys", json={"name": "fleet", "scopes": scope}).json()["key"]
    as_key = TestClient(app, headers={"Authorization": "Bearer " + key})
    assert as_key.get("/v1/workspaces/w/fleet").status_code == 200
    assert as_key.put(f"/v1/computers/{c.id}/labels", json={"labels": ["k"]}).status_code == expected

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import inspect, select

from desktop_service import plans
from desktop_service.config import settings
from desktop_service.db import Computer, Ledger, Workspace, now
from desktop_service.entitlements import can_run, charge
from desktop_service.feature_models import DesktopProfile
from desktop_service.plans import Pass
from desktop_service.platform_credits import available, grant


@pytest.fixture
def broke(db):
    """A workspace with no legacy credits and no balance."""
    w = db.get(Workspace, "w")
    w.subscription, w.included, w.topup = "inactive", 0, 0
    db.commit()
    return w


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setattr(
        settings(), "platform_service_prices", {"cubicle-pass-day": 2_000_000, "cubicle-pass-month": 30_000_000}
    )


def buy(client, plan_id, key):
    return client.post("/v1/workspaces/w/passes", json={"plan_id": plan_id}, headers={"Idempotency-Key": key})


def test_catalog_hides_prices_until_the_owner_sets_them(client, priced, monkeypatch):
    monkeypatch.setattr(settings(), "platform_service_prices", {})
    body = client.get("/v1/plans").json()
    assert [p["id"] for p in body["plans"]] == ["day", "month"]
    assert all(p["price_micro_usdc"] is None and not p["for_sale"] for p in body["plans"])
    assert body["pay_as_you_go"]["minute_micro_usdc"] == settings().cubicle_minute_micro_usdc
    assert "do not renew automatically" in body["renewal"]
    monkeypatch.setattr(settings(), "platform_service_prices", {"cubicle-pass-day": 2_000_000})
    body = client.get("/v1/plans").json()
    day = next(p for p in body["plans"] if p["id"] == "day")
    assert day["for_sale"] and day["price_usdc"] == 2.0
    assert not next(p for p in body["plans"] if p["id"] == "month")["for_sale"]


def test_buying_requires_price_credits_and_ownership(client, db, broke, priced):
    assert buy(client, "day", "pass-nope-1").status_code == 402  # no credits yet
    assert buy(client, "unknown", "pass-nope-2").status_code == 404
    grant(db, "w", 2_500_000, "grant-pass-1", "test funding")
    db.commit()
    bought = buy(client, "day", "pass-buy-1")
    assert bought.status_code == 201
    body = bought.json()
    assert body["plan_id"] == "day" and body["includes"]["running_computers"] == 1
    assert available(db, "w") == 500_000
    assert buy(client, "day", "pass-buy-1").json()["id"] == body["id"]  # replayed, charged once
    assert available(db, "w") == 500_000
    assert buy(client, "month", "pass-buy-2").status_code == 402


def test_buying_again_extends_from_the_current_expiry(client, db, broke, priced):
    grant(db, "w", 10_000_000, "grant-pass-2", "test funding")
    db.commit()
    first = buy(client, "day", "pass-extend-1").json()
    second = buy(client, "day", "pass-extend-2").json()
    assert second["starts_at"] == first["expires_at"]
    current = client.get("/v1/workspaces/w/pass").json()
    assert current["active"]["id"] == second["id"] and len(current["history"]) == 2
    assert plans.active(db, "w").id == second["id"]


def test_pass_makes_minutes_free_and_covers_only_its_tier(client, db, broke, priced):
    grant(db, "w", 40_000_000, "grant-pass-3", "test funding")
    db.commit()
    small = Computer(workspace_id="w", name="Small", request_id="plan-small")
    big = Computer(workspace_id="w", name="Big", request_id="plan-big")
    db.add_all([small, big])
    db.flush()
    db.add(DesktopProfile(computer_id=small.id, cpu=2, memory_gib=4, storage_gib=50))
    db.add(DesktopProfile(computer_id=big.id, cpu=2, memory_gib=4, storage_gib=100))
    db.commit()
    buy(client, "day", "pass-meter-1")
    before = available(db, "w")
    w = db.get(Workspace, "w")
    assert charge(db, w, small.id, 1) and charge(db, w, big.id, 1)
    db.commit()
    assert available(db, "w") == before - settings().cubicle_minute_micro_usdc  # only the over-tier computer paid
    rows = {r.id: r for r in db.scalars(select(Ledger))}
    assert rows[f"usage:{small.id}:1"].amount == 0 and rows[f"usage:{small.id}:1"].reason == "included-in-pass"
    assert rows[f"usage:{big.id}:1"].amount == -1


def test_limits_and_running_come_from_the_pass(client, db, broke, priced):
    grant(db, "w", 40_000_000, "grant-pass-4", "test funding")
    db.commit()
    before = client.get("/v1/workspaces/w/fleet").json()["summary"]["limits"]
    assert before["plan"] == "paid" and before["expires_at"] is None  # credits only
    month = buy(client, "month", "pass-limits-1").json()
    summary = client.get("/v1/workspaces/w/fleet").json()["summary"]
    assert summary["limits"]["plan"] == "Monthly pass" and summary["limits"]["running"] == 2
    assert summary["limits"]["saved"] == 5 and summary["limits"]["expires_at"][:10] == month["expires_at"][:10]
    assert can_run(db, db.get(Workspace, "w"))


def test_zero_credits_still_runs_while_a_pass_is_live_and_stops_after_expiry(client, db, broke, priced, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    grant(db, "w", 2_000_000, "grant-pass-5", "test funding")
    db.commit()
    buy(client, "day", "pass-expiry-1")
    assert available(db, "w") == 0
    created = client.post(
        "/v1/workspaces/w/computers", json={"name": "On pass"}, headers={"Idempotency-Key": "pass-create-1"}
    )
    assert created.status_code == 201
    cid = created.json()["id"]
    assert client.post(f"/v1/computers/{cid}/actions/start").status_code == 200
    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "create", AsyncMock(return_value="sb"))
    monkeypatch.setattr(worker.runtime, "keep_alive", AsyncMock())
    monkeypatch.setattr(worker.secrets_vault, "inject", AsyncMock())
    monkeypatch.setattr(worker.screens, "start_all", AsyncMock())
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, cid).status == "running"
    expired = db.scalar(select(Pass))
    expired.expires_at = now() - timedelta(minutes=1)
    computer = db.get(Computer, cid)
    computer.metered_at = now() - timedelta(minutes=2)
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, cid).status == "stopping"


def test_fresh_database_creates_every_table(tmp_path, monkeypatch):
    from desktop_service import db as models
    from desktop_service import upgrade as upgrade_module

    engine = models.make_engine("sqlite:///" + str(tmp_path / "fresh.db"))
    monkeypatch.setattr(upgrade_module, "engine", engine)
    monkeypatch.setattr(models, "engine", engine)
    upgrade_module.upgrade()
    tables = set(inspect(engine).get_table_names())
    assert {
        "computers",
        "automations",
        "automation_runs",
        "computer_screens",
        "plan_passes",
        "app_installs",
        "workspace_secrets",
        "api_keys",
        "desktop_templates",
    } <= tables
    engine.dispose()

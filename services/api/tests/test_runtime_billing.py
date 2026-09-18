import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from desktop_service import platform_client, runtime_billing
from desktop_service.config import settings
from desktop_service.db import Computer, Event, Workspace, now
from desktop_service.feature_models import DesktopProfile
from desktop_service.plans import Pass
from desktop_service.runtime_billing import HourBlock


class FakePlatform:
    """Stands in for the platform's internal charge API."""

    def __init__(self, priced=True):
        self.prices = {"cubicle.hour.cpu2-mem4": 250_000} if priced else {}
        self.charges = {}
        self.created = []
        self.reachable = True

    def price_for(self, sku):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        return self.prices.get(sku)

    def create_charge(self, sku, subject, idempotency_key, **kwargs):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        self.created.append({"sku": sku, "subject": subject, "key": idempotency_key, **kwargs})
        if sku not in self.prices:
            return {"free": True}
        charge = self.charges.get(subject) or {
            "id": f"chg_{len(self.charges) + 1}",
            "status": "open",
            "amountMicro": self.prices[sku],
            "subject": subject,
        }
        self.charges[subject] = charge
        return {"charge": charge, "payUrl": f"http://127.0.0.1:8760/pay/{charge['id']}", "created": True}

    def get_charge(self, charge_id):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        for charge in self.charges.values():
            if charge["id"] == charge_id:
                return charge
        return None

    def pay(self, charge_id):
        for charge in self.charges.values():
            if charge["id"] == charge_id:
                charge["status"] = "paid"


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(settings(), "platform_url", "http://127.0.0.1:8760")
    monkeypatch.setattr(settings(), "platform_service_token", "test-token")
    monkeypatch.setattr(platform_client, "price_for", fake.price_for)
    monkeypatch.setattr(platform_client, "create_charge", fake.create_charge)
    monkeypatch.setattr(platform_client, "get_charge", fake.get_charge)
    return fake


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Billed", request_id="rb-001", status="running", sandbox_id="sb")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, cpu=2, memory_gib=4))
    db.commit()
    return c


def test_sku_follows_the_resource_tier(db, running):
    profile = db.get(DesktopProfile, running.id)
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu2-mem4"
    profile.cpu, profile.memory_gib = 1, 2
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu1-mem2"
    profile.gpu = 1
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu1-mem2-gpu"
    assert runtime_billing.tier_sku(None) == "cubicle.hour.cpu2-mem4"


def test_unpriced_sku_runs_free_without_a_charge(db, running, platform):
    platform.prices = {}
    assert runtime_billing.ensure(db, running) is True
    db.commit()
    block = db.scalar(select(HourBlock))
    assert block.status == "free" and block.charge_id is None
    assert platform.created == []  # never asks for a charge it does not need


def test_first_hour_opens_a_charge_and_blocks_until_paid(db, running, platform):
    assert runtime_billing.ensure(db, running) is False  # unpaid: the computer may not keep running
    db.commit()
    block = db.scalar(select(HourBlock))
    assert block.status == "open" and block.pay_url.endswith(block.charge_id)
    assert block.amount_micro_usdc == 250_000
    created = platform.created[0]
    assert created["sku"] == "cubicle.hour.cpu2-mem4"
    assert created["subject"] == created["key"] == runtime_billing.subject_for(running.id, block.starts_at)
    assert created["expires_in_seconds"] == runtime_billing.CHARGE_TTL_SECONDS
    assert any(e.kind == "approval" and block.pay_url in e.text for e in db.scalars(select(Event)))
    platform.pay(block.charge_id)
    assert runtime_billing.ensure(db, running) is True
    db.commit()
    assert db.scalar(select(HourBlock)).status == "paid"
    assert len(platform.created) == 1  # replayed, not charged twice


def test_next_hour_is_opened_within_the_grace_window_only(db, running, platform):
    start = runtime_billing.hour_start(now())
    db.add(
        HourBlock(
            computer_id=running.id,
            workspace_id="w",
            sku="cubicle.hour.cpu2-mem4",
            starts_at=start,
            expires_at=now() + timedelta(minutes=30),
            status="paid",
        )
    )
    db.commit()
    assert runtime_billing.ensure(db, running) is True
    assert platform.created == []  # still far from the end
    paid = db.scalar(select(HourBlock))
    paid.expires_at = now() + timedelta(minutes=3)
    db.commit()
    assert runtime_billing.ensure(db, running) is True  # inside the grace window, still running
    db.commit()
    assert len(platform.created) == 1
    upcoming = db.scalar(select(HourBlock).where(HourBlock.status == "open"))
    assert upcoming.starts_at == paid.expires_at


def test_unpaid_next_hour_stops_the_computer_through_the_worker(db, running, platform, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "keep_alive", worker.runtime.keep_alive.__class__ and _noop())
    db.add(
        HourBlock(
            computer_id=running.id,
            workspace_id="w",
            sku="cubicle.hour.cpu2-mem4",
            starts_at=now() - timedelta(hours=1),
            expires_at=now() - timedelta(seconds=30),
            status="paid",
        )
    )
    running.last_active = now()
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, running.id).status == "stopping"
    assert any("was not paid" in e.text for e in db.scalars(select(Event)))


def test_a_pass_covers_runtime_without_hourly_charges(db, running, platform):
    db.add(
        Pass(
            id="pass-cover",
            workspace_id="w",
            plan_id="month",
            starts_at=now(),
            expires_at=now() + timedelta(days=3),
            created_by="local-user",
        )
    )
    db.commit()
    assert runtime_billing.ensure(db, running) is True
    assert platform.created == []
    until, source = runtime_billing.covered_until(db, running)
    assert source == "pass" and until > now()


def test_platform_outage_never_cuts_a_paid_hour_short(db, running, platform):
    db.add(
        HourBlock(
            computer_id=running.id,
            workspace_id="w",
            sku="cubicle.hour.cpu2-mem4",
            starts_at=runtime_billing.hour_start(now()),
            expires_at=now() + timedelta(minutes=2),
            status="paid",
        )
    )
    db.commit()
    platform.reachable = False
    assert runtime_billing.ensure(db, running) is True  # still covered; the outage is logged, not fatal
    assert db.scalar(select(HourBlock)).status == "paid"


def test_status_and_manual_purchase_routes(client, db, running, platform):
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["billing"] == "platform" and body["covered_until"] is None and body["next"] is None
    bought = client.post(f"/v1/computers/{running.id}/runtime/hours")
    assert bought.status_code == 201
    charge = bought.json()
    assert charge["status"] == "open" and charge["pay_url"]
    platform.pay(charge["charge_id"])
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["next"]["status"] == "paid" and body["covered_by"] == "hour"
    assert len(body["hours"]) == 1


def test_credit_billing_stays_when_the_platform_is_not_configured(client, db, running):
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["billing"] == "credits" and body["covered_until"] is None
    assert client.post(f"/v1/computers/{running.id}/runtime/hours").status_code == 409
    assert runtime_billing.ensure(db, running) is True  # legacy metering decides, not this module


def test_starting_needs_no_balance_under_platform_billing(client, db, platform):
    from desktop_service.entitlements import can_run

    w = db.get(Workspace, "w")
    w.subscription, w.included, w.topup = "inactive", 0, 0
    db.commit()
    assert can_run(db, w) is True


def _noop():
    from unittest.mock import AsyncMock

    return AsyncMock()


def test_pass_purchase_goes_through_a_charge_and_starts_when_paid(client, db, platform):
    platform.prices["cubicle.pass.day"] = 2_000_000
    first = client.post("/v1/workspaces/w/passes", json={"plan_id": "day"}, headers={"Idempotency-Key": "chg-pass-1"})
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "pending" and body["pay_url"] and body["price_micro_usdc"] == 2_000_000
    assert client.get("/v1/workspaces/w/pass").json()["active"] is None  # not yet paid
    replay = client.post("/v1/workspaces/w/passes", json={"plan_id": "day"}, headers={"Idempotency-Key": "chg-pass-1"})
    assert replay.json()["id"] == body["id"] and len(platform.created) == 1
    platform.pay(body["charge_id"])
    current = client.get("/v1/workspaces/w/pass").json()["active"]
    assert current["status"] == "active" and current["plan_name"] == "Day pass"
    started = db.scalar(select(Pass))
    assert (started.expires_at - started.starts_at) == timedelta(days=1)


def test_unpriced_pass_activates_immediately(client, db, platform):
    platform.prices.pop("cubicle.pass.day", None)
    body = client.post(
        "/v1/workspaces/w/passes", json={"plan_id": "day"}, headers={"Idempotency-Key": "chg-pass-free"}
    ).json()
    assert body["status"] == "active" and body["charge_id"] is None
    assert client.get("/v1/workspaces/w/pass").json()["active"]["id"] == body["id"]


def test_billing_outage_never_fails_a_desktop(db, running, platform, monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    platform.reachable = False
    assert runtime_billing.ensure(db, running) is True  # no coverage and no platform: keep running
    db.commit()
    assert db.get(Computer, running.id).error == runtime_billing.BILLING_UNAVAILABLE
    assert any("keeps running for now" in e.text for e in db.scalars(select(Event)))
    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "keep_alive", _noop())
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, running.id).status == "running"  # not failed, not stopped
    platform.reachable = True
    assert runtime_billing.ensure(db, running) is False  # billing back: the hour is now open and unpaid


def test_catalog_quotes_the_rail_that_actually_charges(client, db, platform):
    """The two rails spell their SKUs differently, so reading the wrong one either hides a plan
    that is on sale or advertises a price nobody is charged."""
    platform.prices["cubicle.pass.month"] = 9_000_000
    body = client.get("/v1/plans").json()
    assert body["billing"] == "platform" and "pay_as_you_go" not in body
    plans = {p["id"]: p for p in body["plans"]}
    month = plans["month"]
    assert month["price_micro_usdc"] == 9_000_000 and month["price_usdc"] == 9.0
    assert month["for_sale"] is True and month["free"] is False and month["price_source"] == "platform"
    day = plans["day"]
    # Unpriced on the platform means free, which is a price, so the plan stays buyable.
    assert day["price_micro_usdc"] is None and day["free"] is True and day["for_sale"] is True
    hourly = {rate["tier"]: rate for rate in body["hourly"]}
    assert hourly["cpu2-mem4"]["price_micro_usdc"] == 250_000
    assert hourly["cpu2-mem4"]["sku"] == "cubicle.hour.cpu2-mem4"
    assert hourly["cpu1-mem2"]["free"] is True  # no price set for that tier yet
    assert "cpu2-mem4-gpu" in hourly


def test_catalog_says_unknown_rather_than_unpriced_during_an_outage(client, db, platform):
    platform.reachable = False
    body = client.get("/v1/plans").json()
    assert body["hourly"] is None
    for plan in body["plans"]:
        assert plan["price_source"] == "unavailable"
        assert plan["for_sale"] is False and plan["price_micro_usdc"] is None


def test_catalog_keeps_per_minute_credits_when_there_is_no_platform(client, db):
    body = client.get("/v1/plans").json()
    assert body["billing"] == "credits" and body["pay_as_you_go"]["minute_micro_usdc"] > 0
    assert all(p["price_source"] == "credits" for p in body["plans"])

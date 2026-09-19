import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import platform_client, runtime_billing
from desktop_service.config import settings
from desktop_service.db import Computer, Event, Workspace, now
from desktop_service.feature_models import DesktopProfile
from desktop_service.plans import Pass
from desktop_service.runtime_billing import RuntimePack, RuntimeUsage

HOUR_PRICE = 100_000  # the $0.10 an hour agreed for cpu2-mem4


class FakePlatform:
    """Stands in for the platform's internal charge API."""

    def __init__(self):
        self.prices = {"cubicle.hour.cpu2-mem4": HOUR_PRICE}
        self.charges = {}
        self.created = []
        self.reachable = True

    def price_for(self, sku):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        return self.prices.get(sku)

    def create_charge(self, sku, subject, idempotency_key, units=1, **kwargs):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        self.created.append({"sku": sku, "subject": subject, "key": idempotency_key, "units": units, **kwargs})
        if sku not in self.prices:
            return {"free": True}
        charge = self.charges.get(idempotency_key) or {
            "id": f"chg_{len(self.charges) + 1}",
            "status": "open",
            "amountMicro": self.prices[sku] * units,
            "subject": subject,
        }
        self.charges[idempotency_key] = charge
        return {"charge": charge, "payUrl": f"http://127.0.0.1:8760/pay/{charge['id']}", "created": True}

    def get_charge(self, charge_id):
        if not self.reachable:
            raise platform_client.PlatformError("Platform unreachable: probe")
        return next((c for c in self.charges.values() if c["id"] == charge_id), None)

    def set_status(self, charge_id, status):
        self.get_charge(charge_id)["status"] = status

    def pay(self, charge_id):
        self.set_status(charge_id, "paid")


@pytest.fixture
def platform(monkeypatch):
    fake = FakePlatform()
    monkeypatch.setattr(settings(), "platform_url", "http://127.0.0.1:8760")
    monkeypatch.setattr(settings(), "platform_service_token", "test-token")
    monkeypatch.setattr(settings(), "runtime_cap_hours", 190)
    monkeypatch.setattr(platform_client, "price_for", fake.price_for)
    monkeypatch.setattr(platform_client, "create_charge", fake.create_charge)
    monkeypatch.setattr(platform_client, "get_charge", fake.get_charge)
    return fake


@pytest.fixture
def clock(monkeypatch):
    """Pins the meter's clock so elapsed seconds are exact."""
    state = {"now": now()}
    monkeypatch.setattr(runtime_billing, "now", lambda: state["now"])
    return state


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Billed", request_id="rb-001", status="running", sandbox_id="sb")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, cpu=2, memory_gib=4))
    db.commit()
    return c


def paid_pack(db, c, hours=1, used=0):
    pack = RuntimePack(
        computer_id=c.id,
        workspace_id=c.workspace_id,
        sku="cubicle.hour.cpu2-mem4",
        hours=hours,
        seconds_used=used,
        status="paid",
        idempotency_key=f"test:{c.id}:{hours}:{used}",
        paid_at=now(),
    )
    db.add(pack)
    db.commit()
    return pack


def tick(db, c, clock, seconds):
    """Advance the clock by `seconds` since the last metering, then run one worker tick."""
    c.metered_at = clock["now"]
    clock["now"] = clock["now"] + timedelta(seconds=seconds)
    result = runtime_billing.ensure(db, c)
    db.commit()
    return result


def test_sku_follows_the_resource_tier(db, running):
    profile = db.get(DesktopProfile, running.id)
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu2-mem4"
    profile.cpu, profile.memory_gib = 1, 2
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu1-mem2"
    profile.gpu = 1
    assert runtime_billing.tier_sku(profile) == "cubicle.hour.cpu1-mem2-gpu"
    assert runtime_billing.tier_sku(None) == "cubicle.hour.cpu2-mem4"


def test_every_creatable_size_has_a_tier():
    """A size with no tier is never priced, and an unpriced SKU is free: the tiers must cover them all."""
    import typing

    from desktop_service.features import ProfileBody, TemplateCreate
    from desktop_service.main import ComputerCreate

    def choices(model, field):
        return {
            a for arg in typing.get_args(model.model_fields[field].annotation) for a in typing.get_args(arg) or [arg]
        }

    for model in (ComputerCreate, ProfileBody, TemplateCreate):
        assert choices(model, "cpu") - {type(None)} == set(runtime_billing.CPU_SIZES), model
        assert choices(model, "memory_gib") - {type(None)} == set(runtime_billing.MEMORY_SIZES), model
    for cpu in runtime_billing.CPU_SIZES:
        for memory in runtime_billing.MEMORY_SIZES:
            for gpu in (0, 1):
                profile = DesktopProfile(computer_id="x", cpu=cpu, memory_gib=memory, gpu=gpu)
                assert runtime_billing.tier_sku(profile) in runtime_billing.TIER_SKUS.values()
    assert not any("cpu4" in sku for sku in runtime_billing.TIER_SKUS.values())  # no size nobody can create


def test_unpriced_tier_runs_free_and_meters_nothing(db, running, platform, clock):
    platform.prices = {}
    for _ in range(5):
        assert tick(db, running, clock, 60) is True
    assert platform.created == []  # never asks for a charge it does not need
    assert db.scalars(select(RuntimeUsage)).all() == []
    assert runtime_billing.may_start(db, running) == "go"


def test_a_five_minute_task_costs_five_minutes(db, running, platform, clock):
    """The point of metering by the second: short work is not rounded up to an hour."""
    pack = paid_pack(db, running, hours=1)
    for _ in range(5):
        assert tick(db, running, clock, 60) is True
    db.refresh(pack)
    assert pack.seconds_used == 300
    assert runtime_billing.seconds_left(db, running.id) == 3300
    assert runtime_billing.used_in_window(db, running.id) == 300


def test_packs_are_drawn_oldest_first(db, running, platform, clock):
    older = paid_pack(db, running, hours=1, used=3590)
    newer = paid_pack(db, running, hours=2)
    assert tick(db, running, clock, 30) is True
    db.refresh(older)
    db.refresh(newer)
    assert older.seconds_used == 3600 and newer.seconds_used == 20


def test_a_worker_outage_is_not_charged(db, running, platform, clock):
    """A long gap means the worker was down. That time costs us, not the customer."""
    pack = paid_pack(db, running, hours=1)
    assert tick(db, running, clock, 3600) is True
    db.refresh(pack)
    assert pack.seconds_used == runtime_billing.MAX_TICK_SECONDS


def test_low_time_opens_the_next_charge_early(db, running, platform, clock):
    paid_pack(db, running, hours=1, used=3600 - 400)
    assert tick(db, running, clock, 60) is True  # 340 s left: above the 5 minute warning
    assert platform.created == []
    assert tick(db, running, clock, 60) is True  # 280 s left: warn now, while there is time to pay
    assert len(platform.created) == 1
    due = db.scalar(select(RuntimePack).where(RuntimePack.status == "open"))
    assert due.hours == 1 and due.amount_micro_usdc == HOUR_PRICE and due.pay_url
    assert any(e.kind == "approval" and due.pay_url in e.text for e in db.scalars(select(Event)))
    assert tick(db, running, clock, 60) is True
    assert len(platform.created) == 1  # the waiting charge is not duplicated every tick


def test_running_out_stops_the_computer(db, running, platform, clock):
    paid_pack(db, running, hours=1, used=3600 - 10)
    assert tick(db, running, clock, 30) is False  # only 10 of these 30 seconds were paid for


def test_paying_the_waiting_charge_keeps_it_running(db, running, platform, clock):
    paid_pack(db, running, hours=1, used=3600 - 200)
    assert tick(db, running, clock, 60) is True
    due = db.scalar(select(RuntimePack).where(RuntimePack.status == "open"))
    platform.pay(due.charge_id)
    for _ in range(4):
        assert tick(db, running, clock, 60) is True  # crosses into the new hour without a gap
    assert runtime_billing.seconds_left(db, running.id) == 3600 - 100


def test_the_monthly_cap_makes_the_rest_free(db, running, platform, clock, monkeypatch):
    monkeypatch.setattr(settings(), "runtime_cap_hours", 1)
    db.add(RuntimeUsage(computer_id=running.id, day=clock["now"].date(), seconds=3600 - 20))
    db.commit()
    pack = paid_pack(db, running, hours=5)
    assert tick(db, running, clock, 60) is True
    db.refresh(pack)
    assert pack.seconds_used == 20  # only the part of the tick below the cap is drawn
    assert runtime_billing.capped(db, running.id)
    for _ in range(10):
        assert tick(db, running, clock, 60) is True
    db.refresh(pack)
    assert pack.seconds_used == 20  # capped: time runs free, and the pack keeps its hours for later
    pack.seconds_used = pack.hours * 3600
    db.commit()
    assert tick(db, running, clock, 60) is True  # even with nothing left, a capped computer keeps running


def test_usage_older_than_the_window_does_not_count(db, running, platform, clock, monkeypatch):
    monkeypatch.setattr(settings(), "runtime_cap_hours", 1)
    db.add(RuntimeUsage(computer_id=running.id, day=clock["now"].date() - timedelta(days=30), seconds=10**6))
    db.commit()
    assert not runtime_billing.capped(db, running.id)
    db.add(RuntimeUsage(computer_id=running.id, day=clock["now"].date() - timedelta(days=29), seconds=3600))
    db.commit()
    assert runtime_billing.capped(db, running.id)


def test_a_pass_covers_runtime_without_consuming(db, running, platform, clock):
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
    assert tick(db, running, clock, 60) is True
    assert platform.created == []
    assert db.scalars(select(RuntimeUsage)).all() == []
    assert runtime_billing.may_start(db, running) == "go"


def test_platform_outage_keeps_running_unmetered(db, running, platform, clock):
    pack = paid_pack(db, running, hours=1)
    platform.reachable = False
    assert tick(db, running, clock, 60) is True
    db.refresh(running)
    db.refresh(pack)
    assert running.error == runtime_billing.BILLING_UNAVAILABLE
    assert pack.seconds_used == 0  # we could not tell whether it was free, so it was not charged
    assert runtime_billing.may_start(db, running) == "go"
    platform.reachable = True
    assert tick(db, running, clock, 60) is True
    db.refresh(running)
    assert running.error is None


def test_a_computer_without_paid_time_waits_to_start(db, running, platform):
    running.status = "starting"
    db.commit()
    assert runtime_billing.may_start(db, running) == "wait"
    assert platform.created[0]["units"] == 1 and platform.created[0]["sku"] == "cubicle.hour.cpu2-mem4"
    running.error = runtime_billing.WAITING_FOR_PAYMENT  # what the worker records
    assert runtime_billing.may_start(db, running) == "wait"
    assert len(platform.created) == 1
    due = db.scalar(select(RuntimePack).where(RuntimePack.status == "open"))
    platform.pay(due.charge_id)
    assert runtime_billing.may_start(db, running) == "go"


def test_a_lapsed_start_charge_stops_that_start_but_not_the_next(db, running, platform):
    running.status = "starting"
    assert runtime_billing.may_start(db, running) == "wait"
    running.error = runtime_billing.WAITING_FOR_PAYMENT
    due = db.scalar(select(RuntimePack).where(RuntimePack.status == "open"))
    platform.set_status(due.charge_id, "expired")
    assert runtime_billing.may_start(db, running) == "stop"
    running.error = None  # a new start clears the marker
    assert runtime_billing.may_start(db, running) == "wait"
    assert len(platform.created) == 2  # and asks for a fresh charge


def worker_with(monkeypatch):
    from desktop_service import db as models
    from desktop_service import worker

    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "keep_alive", AsyncMock())
    monkeypatch.setattr(worker.runtime, "create", AsyncMock(return_value="sb-new"))
    monkeypatch.setattr(worker.secrets_vault, "inject", AsyncMock())
    monkeypatch.setattr(worker.screens, "start_all", AsyncMock())
    return worker


def test_the_worker_waits_for_payment_then_boots(db, running, platform, monkeypatch):
    worker = worker_with(monkeypatch)
    running.status, running.sandbox_id = "starting", None
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    c = db.get(Computer, running.id)
    assert c.status == "starting" and c.error == runtime_billing.WAITING_FOR_PAYMENT
    worker.runtime.create.assert_not_called()  # nothing boots before the runtime is paid
    platform.pay(db.scalar(select(RuntimePack)).charge_id)
    asyncio.run(worker.reconcile())
    db.expire_all()
    c = db.get(Computer, running.id)
    assert c.status == "running" and c.error is None and c.sandbox_id == "sb-new"


def test_the_worker_stops_a_computer_whose_time_ran_out(db, running, platform, monkeypatch):
    worker = worker_with(monkeypatch)
    paid_pack(db, running, hours=1, used=3600)
    running.metered_at = now() - timedelta(seconds=30)
    running.last_active = now()
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    assert db.get(Computer, running.id).status == "stopping"
    assert any("prepaid runtime ran out" in e.text for e in db.scalars(select(Event)))


def test_billing_outage_never_fails_a_desktop(db, running, platform, monkeypatch):
    worker = worker_with(monkeypatch)
    platform.reachable = False
    running.metered_at = now() - timedelta(seconds=30)
    running.last_active = now()
    db.commit()
    asyncio.run(worker.reconcile())
    db.expire_all()
    c = db.get(Computer, running.id)
    assert c.status == "running" and c.error == runtime_billing.BILLING_UNAVAILABLE


def test_status_and_pack_purchase_routes(client, db, running, platform):
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["billing"] == "platform" and body["seconds_left"] == 0 and body["due"] is None
    assert body["cap_hours"] == 190 and body["window_days"] == 30 and body["capped"] is False
    assert body["price_micro_usdc_per_hour"] == HOUR_PRICE and body["free"] is False
    headers = {"Idempotency-Key": "buy-five-hours"}
    bought = client.post(f"/v1/computers/{running.id}/runtime/hours", json={"hours": 5}, headers=headers)
    assert bought.status_code == 201
    pack = bought.json()
    assert pack["hours"] == 5 and pack["status"] == "open" and pack["amount_micro_usdc"] == 5 * HOUR_PRICE
    assert platform.created[0]["units"] == 5
    replay = client.post(f"/v1/computers/{running.id}/runtime/hours", json={"hours": 5}, headers=headers)
    assert replay.json()["id"] == pack["id"] and len(platform.created) == 1  # not charged twice
    changed = client.post(f"/v1/computers/{running.id}/runtime/hours", json={"hours": 2}, headers=headers)
    assert changed.status_code == 409  # a reused key must describe the same purchase, as on the platform
    assert client.get(f"/v1/computers/{running.id}/runtime").json()["due"]["id"] == pack["id"]
    platform.pay(pack["charge_id"])
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["seconds_left"] == 5 * 3600 and body["due"] is None
    assert client.post(f"/v1/computers/{running.id}/runtime/hours", json={"hours": 0}).status_code == 422


def test_buying_an_unpriced_tier_is_free(client, db, running, platform):
    platform.prices = {}
    body = client.post(f"/v1/computers/{running.id}/runtime/hours", json={"hours": 3}).json()
    assert body == {"free": True, "hours": 3, "status": "free"}
    assert client.get(f"/v1/computers/{running.id}/runtime").json()["free"] is True


def test_credit_billing_stays_when_the_platform_is_not_configured(client, db, running):
    body = client.get(f"/v1/computers/{running.id}/runtime").json()
    assert body["billing"] == "credits"
    assert client.post(f"/v1/computers/{running.id}/runtime/hours").status_code == 409
    assert runtime_billing.ensure(db, running) is True  # legacy metering decides, not this module
    assert runtime_billing.may_start(db, running) == "go"


def test_starting_needs_no_balance_under_platform_billing(client, db, platform):
    from desktop_service.entitlements import can_run

    w = db.get(Workspace, "w")
    w.subscription, w.included, w.topup = "inactive", 0, 0
    db.commit()
    assert can_run(db, w) is True


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


def test_catalog_quotes_the_rail_that_actually_charges(client, db, platform):
    """The two rails spell their SKUs differently, so reading the wrong one either hides a plan
    that is on sale or advertises a price nobody is charged."""
    platform.prices["cubicle.pass.month"] = 9_000_000
    body = client.get("/v1/plans").json()
    assert body["billing"] == "platform" and "pay_as_you_go" not in body
    assert body["cap_hours"] == 190 and body["cap_window_days"] == 30
    plans = {p["id"]: p for p in body["plans"]}
    month = plans["month"]
    assert month["price_micro_usdc"] == 9_000_000 and month["price_usdc"] == 9.0
    assert month["for_sale"] is True and month["free"] is False and month["price_source"] == "platform"
    day = plans["day"]
    # Unpriced on the platform means free, which is a price, so the plan stays buyable.
    assert day["price_micro_usdc"] is None and day["free"] is True and day["for_sale"] is True
    hourly = {rate["tier"]: rate for rate in body["hourly"]}
    assert hourly["cpu2-mem4"]["price_micro_usdc"] == HOUR_PRICE
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

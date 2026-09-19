"""Runtime billing on the Instance platform: prepaid runtime, metered by the second, capped by the month.

A computer runs on runtime bought ahead in packs of whole hours at the rate for its size. While it runs,
the worker meters it by the second and draws the time from its packs, oldest first, so a five minute
task costs five minutes. No computer is ever charged for more than `runtime_cap_hours` in any 30 days:
once it has used that much, the rest of the window is free. A stopped computer consumes nothing.

Packs are time, not money. The platform holds no balance and neither does Cubicle; a pack records hours
that were paid for once, through one platform charge, and how many of its seconds have been used.

When a computer's paid time runs low, the next pack's charge is opened and its payment link shown.
If the time runs out before anyone pays, the computer stops and keeps its files. A computer with no
paid time waits to start, the way it waits for capacity, instead of starting and being stopped.

An unpriced SKU is free by the platform's own rule, so a deployment with no prices set runs normally
and meters nothing. A platform outage never stops a running desktop: it keeps running unmetered,
which gives time away rather than taking work from a customer. When the platform is not configured
at all, Cubicle falls back to its own per-minute credit metering (see entitlements.charge).
"""

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import platform_client
from .config import settings
from .db import Base, Computer, database, event, now, uid
from .feature_models import DesktopProfile
from .security import identity, member

router = APIRouter(prefix="/v1")
log = logging.getLogger(__name__)

HOUR = 3600
WINDOW_DAYS = 30
# The worker ticks every few seconds. A longer gap means it was down, and that time is not charged:
# an outage on our side should cost us, not the customer.
MAX_TICK_SECONDS = 120
# A pack's charge stays payable well past the moment it was opened, so a payer has time to act.
CHARGE_TTL_SECONDS = 4 * HOUR
MAX_PACK_HOURS = 720
BILLING_UNAVAILABLE = "Runtime billing is unavailable; this computer keeps running for now."
WAITING_FOR_PAYMENT = "Waiting for runtime to be paid"


class PackConflict(ValueError):
    """An idempotency key reused for a different purchase."""


class RuntimePack(Base):
    """Hours of runtime for one computer, bought with one platform charge and used by the second."""

    __tablename__ = "runtime_packs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80))
    hours: Mapped[int] = mapped_column(Integer)
    seconds_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, paid, expired
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    charge_id: Mapped[str | None] = mapped_column(String(80))
    pay_url: Mapped[str | None] = mapped_column(Text)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def seconds_left(self):
        return max(0, self.hours * HOUR - self.seconds_used) if self.status == "paid" else 0


class RuntimeUsage(Base):
    """Paid seconds one computer used on one day. The monthly cap is the sum over the last 30 days."""

    __tablename__ = "runtime_usage"
    __table_args__ = (UniqueConstraint("computer_id", "day"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    seconds: Mapped[int] = mapped_column(Integer, default=0)


def tier_name(cpu, memory, gpu=False):
    return f"cpu{cpu}-mem{memory}" + ("-gpu" if gpu else "")


# Every size a computer can be created at. CPU and memory are chosen independently, so each
# pairing is its own SKU. A size missing here is a size nobody prices, and an unpriced SKU is free,
# so these must match the create and profile models exactly; a test holds them together.
CPU_SIZES = (1, 2)
MEMORY_SIZES = (2, 4)

# The tiers a desktop can be sold at. The catalog quotes these, and every pack names one.
TIER_SKUS = {
    tier_name(cpu, memory, gpu): "cubicle.hour." + tier_name(cpu, memory, gpu)
    for gpu in (False, True)
    for cpu in CPU_SIZES
    for memory in MEMORY_SIZES
}


def tier_sku(profile):
    cpu = profile.cpu if profile else 2
    memory = profile.memory_gib if profile else 4
    return "cubicle.hour." + tier_name(cpu, memory, bool(profile and profile.gpu))


def cap_seconds():
    return max(0, settings().runtime_cap_hours) * HOUR


def window_start(today=None):
    return (today or now().date()) - timedelta(days=WINDOW_DAYS - 1)


def used_in_window(db, cid):
    return int(
        db.scalar(
            select(func.coalesce(func.sum(RuntimeUsage.seconds), 0)).where(
                RuntimeUsage.computer_id == cid, RuntimeUsage.day >= window_start()
            )
        )
    )


def capped(db, cid):
    """True once this computer has used its monthly cap: the rest of the window is free."""
    cap = cap_seconds()
    return cap > 0 and used_in_window(db, cid) >= cap


def packs(db, cid, *statuses):
    query = select(RuntimePack).where(RuntimePack.computer_id == cid)
    if statuses:
        query = query.where(RuntimePack.status.in_(statuses))
    return db.scalars(query.order_by(RuntimePack.created_at)).all()


def seconds_left(db, cid):
    return sum(p.seconds_left for p in packs(db, cid, "paid"))


def refresh(db, pack):
    """Ask the platform whether an open pack has been paid."""
    if pack.status != "open" or not pack.charge_id:
        return pack
    try:
        charge = platform_client.get_charge(pack.charge_id)
    except platform_client.PlatformError as exc:
        log.warning("Could not check charge %s: %s", pack.charge_id, exc)
        return pack
    status = (charge or {}).get("status")
    if status == "paid":
        pack.status = "paid"
        pack.paid_at = now()
        event(db, pack.computer_id, f"{pack.hours} h of runtime paid", "info")
    elif status in ("expired", "failed"):
        pack.status = "expired"
    return pack


def settle(db, cid):
    for pack in packs(db, cid, "open"):
        refresh(db, pack)


def organization_for(db, workspace_id):
    """The platform organization a workspace is mapped to, or None before the identity cutover."""
    try:
        from . import identity_link
    except ImportError:
        return None
    return identity_link.organization_for(db, workspace_id)


def covered_by_pass(db, c):
    from . import plans

    current = plans.active(db, c.workspace_id)
    return bool(current and plans.covers(plans.BY_ID.get(current.plan_id), db.get(DesktopProfile, c.id)))


def open_pack(db, c, hours, key):
    """Create (or replay) the charge for `hours` of this computer's runtime. Returns the pack, or None if free.

    Raises PlatformError when the platform cannot be reached.
    """
    existing = db.scalar(select(RuntimePack).where(RuntimePack.idempotency_key == key))
    sku = tier_sku(db.get(DesktopProfile, c.id))
    if existing:
        # Same rule as the platform: a replayed key must describe the same purchase.
        if existing.hours != hours or existing.sku != sku or existing.computer_id != c.id:
            raise PackConflict("This Idempotency-Key was already used for a different runtime purchase")
        return refresh(db, existing)
    if platform_client.price_for(sku) is None:
        return None  # unpriced, so free: nobody is asked to pay
    result = platform_client.create_charge(
        sku,
        key,
        idempotency_key=key,
        units=hours,
        description=f"{c.name}: {hours} h of runtime",
        organization_id=organization_for(db, c.workspace_id),
        expires_in_seconds=CHARGE_TTL_SECONDS,
    )
    if result.get("free"):
        return None
    charge = result.get("charge") or {}
    pack = RuntimePack(
        computer_id=c.id,
        workspace_id=c.workspace_id,
        sku=sku,
        hours=hours,
        idempotency_key=key,
        charge_id=charge.get("id"),
        pay_url=result.get("payUrl"),
        amount_micro_usdc=charge.get("amountMicro") or 0,
        status="paid" if charge.get("status") == "paid" else "open",
    )
    if pack.status == "paid":
        pack.paid_at = now()
    db.add(pack)
    db.flush()
    event(
        db,
        c.id,
        f"Runtime is running low. Pay for {hours} more h to keep this computer running: {pack.pay_url}"
        if pack.status == "open"
        else f"{hours} h of runtime paid",
        "approval" if pack.status == "open" else "info",
    )
    return pack


def top_up(db, c):
    """Open the next hour's charge unless one is already waiting. The key makes retries safe."""
    if packs(db, c.id, "open"):
        return
    paid = len(packs(db, c.id, "paid", "expired"))
    return open_pack(db, c, 1, f"runtime:{c.id}:auto:{paid}")


def record_usage(db, cid, seconds):
    row = db.scalar(select(RuntimeUsage).where(RuntimeUsage.computer_id == cid, RuntimeUsage.day == now().date()))
    if not row:
        row = RuntimeUsage(computer_id=cid, day=now().date(), seconds=0)
        db.add(row)
    row.seconds += seconds


def consume(db, cid, seconds):
    """Take `seconds` from the computer's paid packs, oldest first. Returns the seconds actually taken."""
    taken = 0
    for pack in packs(db, cid, "paid"):
        if taken >= seconds:
            break
        step = min(pack.seconds_left, seconds - taken)
        pack.seconds_used += step
        taken += step
    if taken:
        record_usage(db, cid, taken)
    return taken


def unbillable(db, c, exc):
    """Payment service trouble: keep running unmetered, say so once, and let the next tick try again."""
    log.warning("Runtime billing unavailable for %s: %s", c.id, exc)
    if c.error != BILLING_UNAVAILABLE:
        c.error = BILLING_UNAVAILABLE
        event(db, c.id, BILLING_UNAVAILABLE, "error")
    return True


def charged(db, c):
    """Whether running this computer right now costs paid time. Raises PlatformError if we cannot tell."""
    if covered_by_pass(db, c) or capped(db, c.id):
        return False
    return platform_client.price_for(tier_sku(db.get(DesktopProfile, c.id))) is not None


def ensure(db, c):
    """One worker tick for a running computer: meter it, warn early, and say when it must stop.

    Returns True while the computer may keep running.
    """
    if not platform_client.configured():
        return True
    moment = now()
    elapsed = int((moment - c.metered_at).total_seconds()) if c.metered_at else 0
    elapsed = max(0, min(elapsed, MAX_TICK_SECONDS))
    try:
        settle(db, c.id)
        if not charged(db, c):
            c.metered_at = moment
            return True
        # Never draw past the cap: the part of this tick beyond it is already free.
        cap = cap_seconds()
        if cap:
            elapsed = min(elapsed, max(0, cap - used_in_window(db, c.id)))
        taken = consume(db, c.id, elapsed)
        c.metered_at = moment
        remaining = seconds_left(db, c.id)
        if remaining < settings().runtime_grace_minutes * 60:
            top_up(db, c)
        if c.error == BILLING_UNAVAILABLE:
            c.error = None
        # Out of paid time with some of this tick still unpaid: the computer must stop.
        return not (remaining == 0 and taken < elapsed)
    except platform_client.PlatformError as exc:
        c.metered_at = moment
        return unbillable(db, c, exc)


def may_start(db, c):
    """Whether a starting computer may boot: "go", "wait" for a payment in flight, or "stop"."""
    if not platform_client.configured():
        return "go"
    try:
        settle(db, c.id)
        if not charged(db, c) or seconds_left(db, c.id) > 0:
            return "go"
        if packs(db, c.id, "open"):
            return "wait"
        # The start action clears the error, so this marker means the charge we opened for this
        # same start has lapsed. An old lapsed charge from an earlier start never blocks a new one.
        if c.error == WAITING_FOR_PAYMENT:
            return "stop"
        return "wait" if top_up(db, c) else "go"
    except platform_client.PlatformError as exc:
        log.warning("Runtime billing unavailable while starting %s: %s", c.id, exc)
        return "go"  # our outage is not a reason to refuse a customer's desktop


def pack_public(pack):
    return {
        "id": pack.id,
        "hours": pack.hours,
        "seconds_used": pack.seconds_used,
        "seconds_left": pack.seconds_left,
        "status": pack.status,
        "sku": pack.sku,
        "charge_id": pack.charge_id,
        "pay_url": pack.pay_url,
        "amount_micro_usdc": pack.amount_micro_usdc,
        "created_at": pack.created_at,
        "paid_at": pack.paid_at,
    }


def status_for(db, c):
    configured = platform_client.configured()
    if configured:
        settle(db, c.id)
    body = {
        "billing": "platform" if configured else "credits",
        "sku": tier_sku(db.get(DesktopProfile, c.id)),
        "seconds_left": seconds_left(db, c.id),
        "cap_hours": settings().runtime_cap_hours,
        "used_this_window_seconds": used_in_window(db, c.id),
        "window_days": WINDOW_DAYS,
        "capped": capped(db, c.id),
        "covered_by_pass": covered_by_pass(db, c) if configured else False,
        "grace_minutes": settings().runtime_grace_minutes,
        "price_micro_usdc_per_hour": None,
        "free": False,
        "price_unavailable": False,
        "due": None,
        "packs": [pack_public(p) for p in reversed(packs(db, c.id))][:10],
    }
    if configured:
        try:
            price = platform_client.price_for(body["sku"])
            body["price_micro_usdc_per_hour"] = price
            body["free"] = price is None
        except platform_client.PlatformError:
            body["price_unavailable"] = True
        pending = packs(db, c.id, "open")
        body["due"] = pack_public(pending[-1]) if pending else None
    return body


def lookup(db, cid, user, owner=False):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=owner)
    return c


class Purchase(BaseModel):
    hours: int = Field(default=1, ge=1, le=MAX_PACK_HOURS)


@router.get("/computers/{cid}/runtime")
def runtime_status(cid: str, user=Depends(identity), db=Depends(database)):
    c = lookup(db, cid, user)
    body = status_for(db, c)
    db.commit()
    return body


@router.post("/computers/{cid}/runtime/hours", status_code=201)
def buy_hours(
    cid: str,
    body: Purchase | None = None,
    idempotency_key: str | None = Header(default=None, min_length=8, max_length=128),
    user=Depends(identity),
    db=Depends(database),
):
    """Buy a pack of runtime for this computer. Unused hours stay with the computer and never expire."""
    c = lookup(db, cid, user, owner=True)
    if not platform_client.configured():
        raise HTTPException(409, "This deployment bills runtime with credits, not runtime packs")
    hours = (body or Purchase()).hours
    key = f"runtime:{c.id}:buy:{idempotency_key or uid()}"
    try:
        pack = open_pack(db, c, hours, key)
    except PackConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except platform_client.PlatformError as exc:
        raise HTTPException(503, f"The payment service is unavailable: {exc}") from None
    db.commit()
    if pack is None:
        return {"free": True, "hours": hours, "status": "free"}
    return pack_public(pack)

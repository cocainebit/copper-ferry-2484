"""Runtime billing on the Instance platform: hours bought up front, or a pass covering the period.

No balance exists anywhere. A running desktop is covered by either an active pass or a paid hour block
for that computer. A few minutes before coverage ends, Cubicle asks the platform for the next charge
and shows its payment link; if the charge is still unpaid when coverage ends, the computer stops and
its files are kept.

An unpriced SKU is free by the platform's own rule, so a deployment with no prices set runs normally
and charges nobody. When the platform is not configured at all, Cubicle falls back to its own
per-minute credit metering (see entitlements.charge).
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from . import platform_client
from .config import settings
from .db import Base, Computer, database, event, now, uid
from .feature_models import DesktopProfile
from .security import identity, member

router = APIRouter(prefix="/v1")
log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
# A charge for the next hour stays payable well past its start so a desktop is never cut off by expiry.
CHARGE_TTL_SECONDS = 4 * 3600
BILLING_UNAVAILABLE = "Runtime billing is unavailable; this computer keeps running for now."


class HourBlock(Base):
    """One paid (or free) hour of runtime for one computer."""

    __tablename__ = "runtime_hours"
    __table_args__ = (UniqueConstraint("computer_id", "starts_at"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, paid, free, expired
    charge_id: Mapped[str | None] = mapped_column(String(80))
    pay_url: Mapped[str | None] = mapped_column(Text)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def tier_name(cpu, memory, gpu=False):
    return f"cpu{cpu}-mem{memory}" + ("-gpu" if gpu else "")


# The tiers a desktop can be sold at. The catalog quotes these, and every hour charged names one.
TIER_SKUS = {
    tier_name(*shape): "cubicle.hour." + tier_name(*shape)
    for shape in ((1, 2), (2, 4), (4, 8), (2, 4, True), (4, 8, True))
}


def tier_sku(profile):
    cpu = profile.cpu if profile else 2
    memory = profile.memory_gib if profile else 4
    return "cubicle.hour." + tier_name(cpu, memory, bool(profile and profile.gpu))


def hour_start(moment):
    return moment.replace(minute=0, second=0, microsecond=0)


def organization_for(db, workspace_id):
    """The platform organization a workspace is mapped to, or None before the identity cutover."""
    try:
        from . import identity_link
    except ImportError:
        return None
    return identity_link.organization_for(db, workspace_id)


def subject_for(computer_id, starts_at):
    return f"desktop:{computer_id}:{starts_at.isoformat()}Z"


def block_public(block):
    return {
        "starts_at": block.starts_at,
        "expires_at": block.expires_at,
        "status": block.status,
        "sku": block.sku,
        "charge_id": block.charge_id,
        "pay_url": block.pay_url,
        "amount_micro_usdc": block.amount_micro_usdc,
    }


def covered_until(db, c):
    """When the computer's paid runtime ends, and what covers it."""
    from . import plans

    current = plans.active(db, c.workspace_id)
    if current and plans.covers(plans.BY_ID.get(current.plan_id), db.get(DesktopProfile, c.id)):
        return current.expires_at, "pass"
    block = db.scalar(
        select(HourBlock)
        .where(
            HourBlock.computer_id == c.id,
            HourBlock.status.in_(["paid", "free"]),
            HourBlock.expires_at > now(),
        )
        .order_by(HourBlock.expires_at.desc())
        .limit(1)
    )
    return (block.expires_at, "hour") if block else (None, None)


def refresh(db, block):
    """Ask the platform whether an open charge has been paid."""
    if block.status != "open" or not block.charge_id:
        return block
    try:
        charge = platform_client.get_charge(block.charge_id)
    except platform_client.PlatformError as exc:
        log.warning("Could not check charge %s: %s", block.charge_id, exc)
        return block
    status = (charge or {}).get("status")
    if status == "paid":
        block.status = "paid"
        event(db, block.computer_id, "Runtime paid through " + block.expires_at.isoformat() + "Z", "info")
    elif status in ("expired", "failed"):
        block.status = "expired"
    return block


def open_next(db, c, starts_at):
    """Create (or replay) the charge for one hour of this computer. Returns the block."""
    profile = db.get(DesktopProfile, c.id)
    sku = tier_sku(profile)
    existing = db.scalar(select(HourBlock).where(HourBlock.computer_id == c.id, HourBlock.starts_at == starts_at))
    if existing:
        return refresh(db, existing)
    block = HourBlock(
        computer_id=c.id,
        workspace_id=c.workspace_id,
        sku=sku,
        starts_at=starts_at,
        expires_at=starts_at + HOUR,
    )
    if platform_client.price_for(sku) is None:
        # Unpriced on the platform: the hour is free and nobody is asked to pay.
        block.status = "free"
        db.add(block)
        return block
    subject = subject_for(c.id, starts_at)
    result = platform_client.create_charge(
        sku,
        subject,
        idempotency_key=subject,
        description=f"{c.name}: one hour of runtime",
        organization_id=organization_for(db, c.workspace_id),
        expires_in_seconds=CHARGE_TTL_SECONDS,
    )
    if result.get("free"):
        block.status = "free"
        db.add(block)
        return block
    charge = result.get("charge") or {}
    block.charge_id = charge.get("id")
    block.pay_url = result.get("payUrl")
    block.amount_micro_usdc = charge.get("amountMicro") or 0
    block.status = "paid" if charge.get("status") == "paid" else "open"
    db.add(block)
    event(
        db,
        c.id,
        f"The next hour of runtime needs payment: {block.pay_url}" if block.status == "open" else "Next hour is paid",
        "info" if block.status == "paid" else "approval",
    )
    return block


def unbillable(db, c, exc):
    """Payment service trouble: keep running, say so once, and let the next pass try again."""
    log.warning("Runtime billing unavailable for %s: %s", c.id, exc)
    if c.error != BILLING_UNAVAILABLE:
        c.error = BILLING_UNAVAILABLE
        event(db, c.id, "Runtime billing is unavailable; this computer keeps running for now.", "error")
    return True


def ensure(db, c):
    """One pass over a running computer: keep it covered, warn early, report when it must stop.

    Returns True while the computer may keep running.
    """
    if not platform_client.configured():
        return True
    until, source = covered_until(db, c)
    grace = timedelta(minutes=settings().runtime_grace_minutes)
    if until is None:
        try:
            block = open_next(db, c, hour_start(now()))
        except platform_client.PlatformError as exc:
            # Our billing being down is not the customer's fault: keep the desktop up and retry.
            return unbillable(db, c, exc)
        return block.status in ("paid", "free")
    if source == "pass":
        return True
    if until - now() <= grace:
        # Ask for the next hour before this one runs out, so a payer has time to act.
        try:
            open_next(db, c, until)
        except platform_client.PlatformError as exc:
            log.warning("Could not open the next hour for %s: %s", c.id, exc)
            return unbillable(db, c, exc)
    return until > now()


def status_for(db, c):
    upcoming = db.scalar(
        select(HourBlock)
        .where(HourBlock.computer_id == c.id, HourBlock.status == "open")
        .order_by(HourBlock.starts_at.desc())
        .limit(1)
    )
    # Settle the open charge first, so coverage reflects a payment made a moment ago.
    if upcoming:
        refresh(db, upcoming)
    until, source = covered_until(db, c)
    return {
        "billing": "platform" if platform_client.configured() else "credits",
        "covered_until": until,
        "covered_by": source,
        "grace_minutes": settings().runtime_grace_minutes,
        "next": block_public(upcoming) if upcoming else None,
        "hours": [
            block_public(b)
            for b in db.scalars(
                select(HourBlock).where(HourBlock.computer_id == c.id).order_by(HourBlock.starts_at.desc()).limit(10)
            )
        ],
    }


def lookup(db, cid, user, owner=False):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=owner)
    return c


@router.get("/computers/{cid}/runtime")
def runtime_status(cid: str, user=Depends(identity), db=Depends(database)):
    c = lookup(db, cid, user)
    body = status_for(db, c)
    db.commit()
    return body


@router.post("/computers/{cid}/runtime/hours", status_code=201)
def buy_hour(cid: str, user=Depends(identity), db=Depends(database)):
    """Open the charge for the next hour now, so a payer can settle it before the desktop stops."""
    c = lookup(db, cid, user, owner=True)
    if not platform_client.configured():
        raise HTTPException(409, "This deployment bills runtime with credits, not hourly charges")
    until, source = covered_until(db, c)
    if source == "pass":
        raise HTTPException(409, "An active pass already covers this computer")
    starts = until if until else hour_start(now())
    try:
        block = open_next(db, c, starts)
    except platform_client.PlatformError as exc:
        raise HTTPException(503, f"The payment service is unavailable: {exc}") from None
    db.commit()
    return block_public(block)

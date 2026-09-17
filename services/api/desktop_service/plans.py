"""Time-boxed passes next to per-minute credits.

A workspace either pays as it goes (credits metered every minute) or holds a pass: a period bought once
with credits, during which runtime costs nothing and the plan's own limits apply. x402 cannot charge
again by itself, so a pass never auto-renews: buying again while one is active extends it from its
current expiry.

Prices are server-owned and unset by default. A plan with no configured price is listed but cannot be
bought, and the dashboard says so rather than showing a made-up number.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import platform_client, platform_credits
from .config import settings
from .db import Base, database, now, uid
from .security import identity, member

router = APIRouter(prefix="/v1")

# Server-owned catalog. Limits are what a pass includes; resources above them stay on per-minute credits.
CATALOG = [
    {
        "id": "day",
        "name": "Day pass",
        "period_days": 1,
        "description": "24 hours of runtime from purchase.",
        "running_computers": 1,
        "saved_computers": 2,
        "max_cpu": 2,
        "max_memory_gib": 4,
        "max_storage_gib": 50,
        "gpu": False,
    },
    {
        "id": "month",
        "name": "Monthly pass",
        "period_days": 30,
        "description": "30 days of runtime, more computers and the largest disks.",
        "running_computers": 2,
        "saved_computers": 5,
        "max_cpu": 2,
        "max_memory_gib": 4,
        "max_storage_gib": 100,
        "gpu": True,
    },
]
BY_ID = {plan["id"]: plan for plan in CATALOG}


class Purchase(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)


class Pass(Base):
    __tablename__ = "plan_passes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    plan_id: Mapped[str] = mapped_column(String(40))
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    price_micro_usdc: Mapped[int] = mapped_column(default=0)
    # Platform billing: a pass is pending until its charge is paid, then it starts.
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    charge_id: Mapped[str | None] = mapped_column(String(80))
    pay_url: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def sku(plan_id):
    return f"cubicle-pass-{plan_id}"


def price_of(plan_id):
    """Configured price in micro-USDC, or None when the owner has not set one."""
    value = dict(getattr(settings(), "platform_service_prices", {})).get(sku(plan_id))
    return value if type(value) is int and 0 < value <= platform_credits.MAX_AMOUNT else None


def public(plan):
    price = price_of(plan["id"])
    return {
        **plan,
        "price_micro_usdc": price,
        "price_usdc": round(price / 1_000_000, 2) if price else None,
        "for_sale": price is not None,
    }


def active(db, wid):
    """The pass covering this workspace right now, or None."""
    return db.scalar(
        select(Pass)
        .where(Pass.workspace_id == wid, Pass.status == "active", Pass.expires_at > now())
        .order_by(Pass.expires_at.desc())
        .limit(1)
    )


def settle_pending(db, wid):
    """Activate passes whose platform charge has been paid; drop the ones that expired unpaid."""
    changed = False
    for row in db.scalars(select(Pass).where(Pass.workspace_id == wid, Pass.status == "pending")):
        if not row.charge_id:
            continue
        try:
            charge = platform_client.get_charge(row.charge_id)
        except platform_client.PlatformError:
            continue
        status = (charge or {}).get("status")
        if status == "paid":
            plan = BY_ID.get(row.plan_id)
            current = active(db, wid)
            row.starts_at = current.expires_at if current else now()
            row.expires_at = row.starts_at + timedelta(days=plan["period_days"] if plan else 1)
            row.status = "active"
            changed = True
        elif status in ("expired", "failed"):
            row.status = "cancelled"
            changed = True
    if changed:
        db.commit()


def plan_of(db, wid):
    current = active(db, wid)
    return (current, BY_ID.get(current.plan_id)) if current and current.plan_id in BY_ID else (None, None)


def covers(plan, profile):
    """True when a computer's resources fall inside what the pass includes."""
    if not plan:
        return False
    if profile is None:
        return True
    if profile.gpu and not plan["gpu"]:
        return False
    return (
        profile.cpu <= plan["max_cpu"]
        and profile.memory_gib <= plan["max_memory_gib"]
        and profile.storage_gib <= plan["max_storage_gib"]
    )


def covers_computer(db, wid, computer_id):
    from .feature_models import DesktopProfile

    _, plan = plan_of(db, wid)
    return covers(plan, db.get(DesktopProfile, computer_id))


def pass_public(row):
    plan = BY_ID.get(row.plan_id, {})
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "plan_name": plan.get("name", row.plan_id),
        "status": row.status,
        "charge_id": row.charge_id,
        "pay_url": row.pay_url,
        "starts_at": row.starts_at,
        "expires_at": row.expires_at,
        "price_micro_usdc": row.price_micro_usdc,
        "includes": {
            k: plan.get(k)
            for k in ("running_computers", "saved_computers", "max_cpu", "max_memory_gib", "max_storage_gib", "gpu")
        },
    }


@router.get("/plans")
def catalog():
    return {
        "plans": [public(plan) for plan in CATALOG],
        "pay_as_you_go": {
            "minute_micro_usdc": settings().cubicle_minute_micro_usdc,
            "hour_usdc": round(settings().cubicle_minute_micro_usdc * 60 / 1_000_000, 2),
        },
        "renewal": "Passes do not renew automatically. Buy again before expiry to extend from the current end date.",
    }


@router.get("/workspaces/{wid}/pass")
def current_pass(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    if platform_client.configured():
        settle_pending(db, wid)
    row = active(db, wid)
    history = db.scalars(select(Pass).where(Pass.workspace_id == wid).order_by(Pass.created_at.desc()).limit(10)).all()
    return {"active": pass_public(row) if row else None, "history": [pass_public(p) for p in history]}


@router.post("/workspaces/{wid}/passes", status_code=201)
def buy(
    wid: str,
    body: Purchase,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    member(db, wid, user, owner=True, lock=True)
    plan = BY_ID.get(body.plan_id)
    if not plan:
        raise HTTPException(404, "Unknown plan")
    if platform_client.configured():
        return buy_with_charge(db, wid, plan, idempotency_key, user)
    price = price_of(plan["id"])
    if price is None:
        raise HTTPException(409, "This plan has no price yet; it cannot be bought")
    key = f"pass:{wid}:{idempotency_key}"
    existing = db.scalar(select(Pass).where(Pass.workspace_id == wid, Pass.id == key))
    if existing:
        return pass_public(existing)
    if not platform_credits.debit(db, wid, sku(plan["id"]), 1, key):
        raise HTTPException(402, "Not enough credits for this pass. Add credits and try again.")
    current = active(db, wid)
    starts = current.expires_at if current else now()
    row = Pass(
        id=key,
        workspace_id=wid,
        plan_id=plan["id"],
        starts_at=starts,
        expires_at=starts + timedelta(days=plan["period_days"]),
        price_micro_usdc=price,
        created_by=user["id"],
    )
    db.add(row)
    db.commit()
    return pass_public(row)


def organization_for(db, wid):
    from .runtime_billing import organization_for as mapped

    return mapped(db, wid)


def platform_sku(plan_id):
    return f"cubicle.pass.{plan_id}"


def buy_with_charge(db, wid, plan, idempotency_key, user):
    """Platform billing: one charge per pass. The period starts when the charge is paid."""
    sku = platform_sku(plan["id"])
    key = f"pass:{wid}:{idempotency_key}"
    existing = db.get(Pass, key)
    if existing:
        settle_pending(db, wid)
        return pass_public(db.get(Pass, key))
    row = Pass(
        id=key,
        workspace_id=wid,
        plan_id=plan["id"],
        starts_at=now(),
        expires_at=now(),
        created_by=user["id"],
        status="pending",
    )
    try:
        if platform_client.price_for(sku) is None:
            row.status = "active"
            current = active(db, wid)
            row.starts_at = current.expires_at if current else now()
            row.expires_at = row.starts_at + timedelta(days=plan["period_days"])
        else:
            result = platform_client.create_charge(
                sku,
                f"workspace:{wid}:pass:{plan['id']}:{idempotency_key}",
                idempotency_key=key,
                description=f"Cubicle {plan['name']}",
                organization_id=organization_for(db, wid),
            )
            if result.get("free"):
                row.status = "active"
                row.expires_at = row.starts_at + timedelta(days=plan["period_days"])
            else:
                charge = result.get("charge") or {}
                row.charge_id = charge.get("id")
                row.pay_url = result.get("payUrl")
                row.price_micro_usdc = charge.get("amountMicro") or 0
    except platform_client.PlatformError as exc:
        raise HTTPException(503, f"The payment service is unavailable: {exc}") from None
    db.add(row)
    db.commit()
    return pass_public(row)

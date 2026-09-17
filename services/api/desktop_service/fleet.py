"""Fleet management: plan limits, labels, search and filters, bulk lifecycle, moving computers, overview.

Limits come from settings so operators can size plans without code changes. Every figure in the
overview is read from real records: computer rows, the per-minute usage ledger and platform entries.
"""

import re
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .config import settings
from .db import Computer, Ledger, Run, Workspace, database, event, now
from .feature_models import DesktopProfile, FeatureJob
from .payment_models import PlatformEntry
from .platform_credits import paid_access
from .security import identity, member

router = APIRouter(prefix="/v1")

LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
MAX_LABELS = 8
ACTIVE_RUN = ["queued", "running", "paused", "awaiting_approval"]


def limits(db, w):
    s = settings()
    paid = w.subscription == "active" or paid_access(db, w.id)
    return {
        "plan": "paid" if paid else "trial",
        "saved": s.paid_saved_computers if paid else s.trial_saved_computers,
        "running": s.paid_running_computers if paid else s.trial_running_computers,
    }


def saved_count(db, wid):
    return db.scalar(
        select(func.count()).select_from(Computer).where(Computer.workspace_id == wid, Computer.status != "deleted")
    )


def running_count(db, wid, exclude=None):
    query = (
        select(func.count())
        .select_from(Computer)
        .where(Computer.workspace_id == wid, Computer.status.in_(["running", "starting"]))
    )
    if exclude:
        query = query.where(Computer.id != exclude)
    return db.scalar(query)


def check_saved(db, w):
    if saved_count(db, w.id) >= limits(db, w)["saved"]:
        raise HTTPException(409, "Saved computer limit reached")


def check_running(db, w, cid):
    allowed = limits(db, w)["running"]
    if running_count(db, w.id, exclude=cid) >= allowed:
        raise HTTPException(
            409,
            "Only one running computer is included"
            if allowed == 1
            else f"This plan runs at most {allowed} computers at once",
        )


def host_capacity(db):
    busy = db.scalar(
        select(func.count()).select_from(Computer).where(Computer.status.in_(["running", "starting", "stopping"]))
    )
    busy += db.scalar(select(func.count()).select_from(FeatureJob).where(FeatureJob.status == "running"))
    return {"max_desktops": settings().max_desktops, "in_use": busy}


class LabelsBody(BaseModel):
    labels: list[str] = Field(max_length=MAX_LABELS)


class BulkBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    action: Literal["start", "stop", "add_label", "remove_label"]
    label: str | None = None


class MoveBody(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=100)


def clean_labels(values):
    labels = sorted({v.strip().lower() for v in values})
    bad = [v for v in labels if not LABEL.match(v)]
    if bad:
        raise HTTPException(422, "Labels are lowercase letters, digits and dashes, up to 24 characters")
    if len(labels) > MAX_LABELS:
        raise HTTPException(422, f"At most {MAX_LABELS} labels per computer")
    return labels


def usage_since(db, wid, since):
    """Metered minutes per computer and platform spend in micro-USDC since a time, from the ledger."""
    minutes = {}
    for key in db.scalars(select(Ledger.id).where(Ledger.workspace_id == wid, Ledger.created_at >= since)):
        if key.startswith("usage:"):
            cid = key.split(":")[1]
            minutes[cid] = minutes.get(cid, 0) + 1
    spend = -(
        db.scalar(
            select(func.coalesce(func.sum(PlatformEntry.amount), 0)).where(
                PlatformEntry.workspace_id == wid,
                PlatformEntry.created_at >= since,
                PlatformEntry.reason == "service-usage",
            )
        )
        or 0
    )
    return minutes, spend


@router.get("/workspaces/{wid}/fleet")
def fleet(
    wid: str,
    q: str = "",
    status: str = "",
    label: str = "",
    user=Depends(identity),
    db=Depends(database),
):
    w = member(db, wid, user)
    from .automations import Automation
    from .screens import ComputerScreen

    rows = db.execute(
        select(Computer, DesktopProfile)
        .outerjoin(DesktopProfile, DesktopProfile.computer_id == Computer.id)
        .where(Computer.workspace_id == wid, Computer.status != "deleted")
        .order_by(Computer.created_at)
    ).all()
    minutes, spend = usage_since(db, wid, now() - timedelta(hours=24))
    automations = dict(
        db.execute(
            select(Automation.computer_id, func.count())
            .where(Automation.workspace_id == wid, Automation.enabled.is_(True))
            .group_by(Automation.computer_id)
        ).all()
    )
    screens = dict(
        db.execute(select(ComputerScreen.computer_id, func.count()).group_by(ComputerScreen.computer_id)).all()
    )
    counts = {}
    items = []
    needle = q.strip().lower()
    for c, p in rows:
        counts[c.status] = counts.get(c.status, 0) + 1
        labels = c.labels or []
        if needle and needle not in c.name.lower() and not any(needle in lab for lab in labels):
            continue
        if status and c.status != status:
            continue
        if label and label not in labels:
            continue
        items.append(
            {
                "id": c.id,
                "name": c.name,
                "workspace_id": c.workspace_id,
                "status": c.status,
                "controller": c.controller,
                "error": c.error,
                "created_at": c.created_at,
                "labels": labels,
                "cpu": p.cpu if p else 2,
                "memory_gib": p.memory_gib if p else 4,
                "storage_gib": p.storage_gib if p else 20,
                "resolution": p.resolution if p else "1440x900",
                "os": p.os if p else "linux",
                "gpu": p.gpu if p else 0,
                "screens": 1 + screens.get(c.id, 0),
                "automations": automations.get(c.id, 0),
                "usage_24h_minutes": minutes.get(c.id, 0),
                "last_active": c.last_active,
            }
        )
    plan = limits(db, w)
    return {
        "summary": {
            "by_status": counts,
            "saved": sum(counts.values()),
            "running": counts.get("running", 0) + counts.get("starting", 0),
            "limits": plan,
            "host": host_capacity(db),
            "usage_24h_minutes": sum(minutes.values()),
            "spend_24h_micro_usdc": spend,
            "labels": sorted({lab for c, _ in rows for lab in (c.labels or [])}),
        },
        "computers": items,
    }


@router.put("/computers/{cid}/labels")
def set_labels(cid: str, body: LabelsBody, user=Depends(identity), db=Depends(database)):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    c.labels = clean_labels(body.labels)
    db.commit()
    return {"labels": c.labels}


@router.post("/workspaces/{wid}/computers/bulk")
def bulk(wid: str, body: BulkBody, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    from .main import computer_action

    results = []
    for cid in dict.fromkeys(body.ids):
        c = db.get(Computer, cid)
        if not c or c.status == "deleted" or c.workspace_id != wid:
            results.append({"id": cid, "ok": False, "error": "Computer not found in this workspace"})
            continue
        try:
            if body.action in ("start", "stop"):
                computer_action(cid, body.action, user=user, db=db)
            else:
                if not body.label:
                    raise HTTPException(422, "A label is required")
                label = clean_labels([body.label])[0]
                current = set(c.labels or [])
                current = current | {label} if body.action == "add_label" else current - {label}
                c.labels = clean_labels(current)
                db.commit()
            db.refresh(c)
            results.append({"id": cid, "ok": True, "status": c.status, "labels": c.labels or []})
        except HTTPException as exc:
            db.rollback()
            results.append({"id": cid, "ok": False, "error": exc.detail})
    return {"results": results, "succeeded": sum(r["ok"] for r in results)}


@router.post("/computers/{cid}/move")
def move(cid: str, body: MoveBody, user=Depends(identity), db=Depends(database)):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    source = c.workspace_id
    if body.workspace_id == source:
        raise HTTPException(409, "The computer is already in that workspace")
    member(db, source, user, owner=True, lock=True)
    target = member(db, body.workspace_id, user, owner=True, lock=True)
    db.refresh(c)
    if c.status != "stopped" or c.sandbox_id:
        raise HTTPException(409, "Stop the computer before moving it")
    if db.scalar(select(Run).where(Run.computer_id == cid, Run.status.in_(ACTIVE_RUN) | Run.lease.is_not(None))):
        raise HTTPException(409, "Wait for the agent task to finish")
    if db.scalar(
        select(FeatureJob).where(
            (FeatureJob.source_id == cid) | (FeatureJob.target_id == cid), FeatureJob.status.in_(["queued", "running"])
        )
    ):
        raise HTTPException(409, "Wait for the copy to finish")
    check_saved(db, target)
    from .automations import Automation

    c.workspace_id = target.id
    c.controller = "agent"
    for a in db.scalars(select(Automation).where(Automation.computer_id == cid)):
        a.workspace_id = target.id
    event(db, cid, f"Moved from workspace {db.get(Workspace, source).name} to {target.name}", "info")
    db.commit()
    return {"id": c.id, "workspace_id": c.workspace_id}

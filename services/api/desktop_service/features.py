"""Owner-controlled profiles, system templates and full stopped-computer cloning."""

import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import db as models
from . import feature_runtime, runtime
from .db import Computer, Run, Workspace, database, event, now
from .entitlements import balance
from .feature_models import DesktopProfile, DesktopTemplate, FeatureJob
from .security import identity, member

router = APIRouter(prefix="/v1")
log = logging.getLogger(__name__)


class ProfileBody(BaseModel):
    cpu: Literal[1, 2] = 2
    memory_gib: Literal[2, 4] = 4


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")


def owned_computer(db, cid, user):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=True, lock=True)
    db.refresh(c)
    return c


def stopped(db, c):
    if c.status != "stopped" or c.sandbox_id:
        raise HTTPException(409, "Stop the computer before changing resources, cloning or saving a template")
    if db.scalar(select(Run).where(Run.computer_id == c.id, Run.lease.is_not(None))):
        raise HTTPException(409, "Wait for the agent to stop")


def job_public(j):
    return {k: getattr(j, k) for k in ("id", "kind", "status", "source_id", "target_id", "template_id", "error")}


def template_public(t):
    return {
        "id": t.id,
        "name": t.name,
        "status": t.status,
        "cpu": t.cpu,
        "memory_gib": t.memory_gib,
        "includes_home": False,
    }


def old_job(db, wid, key):
    return db.scalar(select(FeatureJob).where(FeatureJob.workspace_id == wid, FeatureJob.request_id == key))


def reserve_computer(db, wid, name, key):
    w = db.get(Workspace, wid)
    if balance(db, w) <= 0:
        raise HTTPException(402, "An active subscription or trial with credits is required")
    count = db.scalar(
        select(func.count()).select_from(Computer).where(Computer.workspace_id == wid, Computer.status != "deleted")
    )
    if count >= (2 if w.subscription == "active" else 1):
        raise HTTPException(409, "Saved computer limit reached")
    c = Computer(workspace_id=wid, name=name.strip(), request_id="feature:" + key, status="copying")
    db.add(c)
    db.flush()
    return c


@router.get("/computers/{cid}/profile")
def profile(cid: str, user=Depends(identity), db=Depends(database)):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    p = db.get(DesktopProfile, cid)
    return {
        "cpu": p.cpu if p else 2,
        "memory_gib": p.memory_gib if p else 4,
        "options": {"cpu": [1, 2], "memory_gib": [2, 4]},
        "storage_quota_enforced": False,
    }


@router.put("/computers/{cid}/profile")
def update_profile(cid: str, body: ProfileBody, user=Depends(identity), db=Depends(database)):
    c = owned_computer(db, cid, user)
    stopped(db, c)
    p = db.get(DesktopProfile, cid) or DesktopProfile(computer_id=cid)
    p.cpu, p.memory_gib = body.cpu, body.memory_gib
    db.add(p)
    event(db, cid, f"Resources set to {p.cpu} CPU and {p.memory_gib} GiB RAM for the next start")
    db.commit()
    return {"cpu": p.cpu, "memory_gib": p.memory_gib}


@router.get("/workspaces/{wid}/templates")
def templates(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    return [
        template_public(t)
        for t in db.scalars(
            select(DesktopTemplate).where(DesktopTemplate.workspace_id == wid, DesktopTemplate.status != "deleted")
        )
    ]


@router.get("/workspaces/{wid}/feature-jobs")
def jobs(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    return [
        job_public(j)
        for j in db.scalars(
            select(FeatureJob).where(FeatureJob.workspace_id == wid).order_by(FeatureJob.created_at.desc()).limit(30)
        )
    ]


@router.post("/computers/{cid}/clone", status_code=202)
def clone(
    cid: str,
    body: Named,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    c = owned_computer(db, cid, user)
    old = old_job(db, c.workspace_id, idempotency_key)
    if old:
        return job_public(old)
    stopped(db, c)
    if not c.system_snapshot_id:
        raise HTTPException(409, "Start and stop this computer once to save its system before cloning")
    target = reserve_computer(db, c.workspace_id, body.name, idempotency_key)
    p = db.get(DesktopProfile, cid)
    db.add(DesktopProfile(computer_id=target.id, cpu=p.cpu if p else 2, memory_gib=p.memory_gib if p else 4))
    c.status = "customizing"
    j = FeatureJob(
        workspace_id=c.workspace_id, request_id=idempotency_key, kind="clone", source_id=cid, target_id=target.id
    )
    db.add(j)
    db.commit()
    return job_public(j)


@router.post("/computers/{cid}/templates", status_code=202)
def save_template(
    cid: str,
    body: Named,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    c = owned_computer(db, cid, user)
    old = old_job(db, c.workspace_id, idempotency_key)
    if old:
        return job_public(old)
    stopped(db, c)
    if not c.system_snapshot_id:
        raise HTTPException(409, "Start and stop this computer once to save its system before templating")
    if (
        db.scalar(
            select(func.count())
            .select_from(DesktopTemplate)
            .where(DesktopTemplate.workspace_id == c.workspace_id, DesktopTemplate.status != "deleted")
        )
        >= 5
    ):
        raise HTTPException(409, "Workspace template limit reached")
    p = db.get(DesktopProfile, cid)
    t = DesktopTemplate(
        workspace_id=c.workspace_id, name=body.name.strip(), cpu=p.cpu if p else 2, memory_gib=p.memory_gib if p else 4
    )
    db.add(t)
    db.flush()
    c.status = "customizing"
    j = FeatureJob(
        workspace_id=c.workspace_id, request_id=idempotency_key, kind="template", source_id=cid, template_id=t.id
    )
    db.add(j)
    db.commit()
    return job_public(j)


@router.post("/templates/{tid}/computers", status_code=202)
def from_template(
    tid: str,
    body: Named,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    t = db.get(DesktopTemplate, tid)
    if not t:
        raise HTTPException(404, "Template not found")
    member(db, t.workspace_id, user, owner=True, lock=True)
    db.refresh(t)
    old = old_job(db, t.workspace_id, idempotency_key)
    if old:
        return job_public(old)
    if t.status != "ready":
        raise HTTPException(409, "Template is not ready")
    target = reserve_computer(db, t.workspace_id, body.name, idempotency_key)
    db.add(DesktopProfile(computer_id=target.id, cpu=t.cpu, memory_gib=t.memory_gib))
    j = FeatureJob(
        workspace_id=t.workspace_id,
        request_id=idempotency_key,
        kind="instantiate",
        template_id=tid,
        target_id=target.id,
    )
    db.add(j)
    db.commit()
    return job_public(j)


@router.delete("/templates/{tid}", status_code=202)
def delete_template(
    tid: str, user=Depends(identity), db=Depends(database), idempotency_key: str = Header(min_length=8, max_length=100)
):
    t = db.get(DesktopTemplate, tid)
    if not t:
        raise HTTPException(404, "Template not found")
    member(db, t.workspace_id, user, owner=True, lock=True)
    db.refresh(t)
    old = old_job(db, t.workspace_id, idempotency_key)
    if old:
        return job_public(old)
    if t.status not in ("ready", "failed") or db.scalar(
        select(FeatureJob).where(FeatureJob.template_id == tid, FeatureJob.status.in_(["queued", "running"]))
    ):
        raise HTTPException(409, "Template is busy")
    t.status = "deleting"
    j = FeatureJob(workspace_id=t.workspace_id, request_id=idempotency_key, kind="delete_template", template_id=tid)
    db.add(j)
    db.commit()
    return job_public(j)


def finish_failed(db, j):
    j.status = "failed"
    j.error = "Copy could not complete. Source data is preserved; delete the failed copy and retry."
    if j.source_id:
        db.get(Computer, j.source_id).status = "stopped"
    if j.target_id:
        c = db.get(Computer, j.target_id)
        c.status, c.error = "copy_failed", j.error
    if j.template_id and j.kind != "instantiate":
        db.get(DesktopTemplate, j.template_id).status = "failed"
    db.commit()


async def process_one():
    """Call serially under the existing worker singleton lock.

    Never replay interrupted disk operations: their helper expires in 15 minutes.
    Release frozen sources only after 20 minutes if the worker crashed.
    """
    with models.Session() as db:
        for stale in db.scalars(
            select(FeatureJob).where(
                FeatureJob.status == "running", FeatureJob.created_at < now() - timedelta(minutes=20)
            )
        ):
            finish_failed(db, stale)
        if db.scalar(select(FeatureJob).where(FeatureJob.status == "running")):
            return
        j = db.scalar(select(FeatureJob).where(FeatureJob.status == "queued").order_by(FeatureJob.created_at).limit(1))
        if not j:
            return
        # Reserve one infrastructure slot for the short-lived copy helper.
        from .config import settings

        active = db.scalar(
            select(func.count()).select_from(Computer).where(Computer.status.in_(["running", "starting", "stopping"]))
        )
        if active >= settings().max_desktops:
            return
        j.status = "running"
        j.created_at = now()
        db.commit()
        try:
            source = db.get(Computer, j.source_id) if j.source_id else None
            template = db.get(DesktopTemplate, j.template_id) if j.template_id else None
            if j.kind == "delete_template":
                if template.snapshot_id:
                    await runtime.delete_system(template.snapshot_id)
                template.snapshot_id, template.status = None, "deleted"
            else:
                snapshot = await feature_runtime.materialize(
                    source.system_snapshot_id if source else template.snapshot_id,
                    source_id=source.id if j.kind == "clone" else None,
                    target_id=j.target_id,
                )
                if j.target_id:
                    target = db.get(Computer, j.target_id)
                    target.system_snapshot_id, target.status, target.error = snapshot, "stopped", None
                    event(db, target.id, "Independent desktop copy is ready")
                else:
                    template.snapshot_id, template.status = snapshot, "ready"
                if source:
                    source.status = "stopped"
            j.status = "completed"
            db.commit()
        except Exception:
            log.exception("Desktop feature job failed: %s", j.id)
            db.rollback()
            j = db.get(FeatureJob, j.id)
            finish_failed(db, j)

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from . import plans, providers, runtime_billing
from .api_keys import router as api_keys_router
from .apps import router as apps_router
from .automations import router as automations_router
from .billing import router as billing_router
from .computer_api import router as computer_api_router
from .config import settings
from .crypto_payments import router as crypto_router
from .db import (
    Computer,
    Credential,
    Entitlement,
    Event,
    Invitation,
    Member,
    Run,
    ServiceHeartbeat,
    Session,
    TrialIntent,
    Workspace,
    database,
    event,
    now,
)
from .display import Resolution
from .entitlements import ChainVerifier, activate, balance, can_run, create_intent
from .feature_models import DesktopProfile
from .features import router as features_router
from .fleet import check_running, check_saved
from .fleet import router as fleet_router
from .gateway import router as gateway_router
from .onboarding import router as onboarding_router
from .operations import requests as request_counts
from .operations import router as operations_router
from .platform_credits import available
from .screens import router as screens_router
from .secrets_vault import router as secrets_router
from .security import digest, identity, member, seal
from .template_registry import router as template_registry_router
from .x402_rail import configuration_status


@asynccontextmanager
async def lifespan(app):
    if settings().dev_mode:
        from .upgrade import upgrade

        upgrade()
        with Session() as db:
            if not db.get(Workspace, "local-workspace"):
                db.add(Workspace(id="local-workspace", name="Your workspace", subscription="active", included=6000))
                db.flush()
                db.add(
                    Member(workspace_id="local-workspace", user_id="local-user", email="you@localhost", role="owner")
                )
                db.commit()
    yield


app = FastAPI(title="Cubicle & Platform Billing", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins or [settings().public_url],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "PAYMENT-SIGNATURE"],
    expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"],
)


class Named(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ComputerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    cpu: Literal[1, 2] = 2
    memory_gib: Literal[2, 4] = 4
    storage_gib: Literal[20, 50, 100] = 20
    resolution: Resolution = "1440x900"
    idle_timeout_minutes: int = Field(default=15, ge=0, le=1440, strict=True)
    os: Literal["linux", "windows", "macos"] = "linux"
    gpu: int = Field(default=0, ge=0, le=8)


class KeyBody(BaseModel):
    key: str = Field(min_length=20, max_length=512)


class TaskBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class IntentBody(BaseModel):
    workspace_id: str
    service: str = "agent-desktop"
    wallet: str = Field(min_length=8, max_length=200)


class SignatureBody(BaseModel):
    signature: str = Field(min_length=1, max_length=2000)


class PaymentBody(BaseModel):
    transaction_id: str = Field(min_length=8, max_length=256)


def computer(db, cid, user, lock=False):
    query = select(Computer).where(Computer.id == cid)
    c = db.scalar(query.with_for_update() if lock else query)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    return c


def public(c):
    body = {k: getattr(c, k) for k in ("id", "name", "workspace_id", "status", "controller", "error", "created_at")}
    return body | {"labels": c.labels or []}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/config")
def config():
    s = settings()
    configured = bool(
        s.trial_adapter_url
        and s.trial_adapter_key
        and s.trial_chain
        and s.trial_token
        and s.trial_recipient
        and 0 <= s.trial_decimals <= 30
    )
    return {
        "dev_mode": s.dev_mode,
        "billing_available": configuration_status()["enabled"],
        "payment_provider": "x402",
        "trials_available": configured,
        "services": {
            key: {"name": key.replace("-", " ").title(), "minutes": minutes}
            for key, minutes in s.trial_services.items()
        },
        "minute_micro_usdc": s.cubicle_minute_micro_usdc,
        "hour_usdc": round(s.cubicle_minute_micro_usdc * 60 / 1_000_000, 2),
        "storage_quota_enforced": s.storage_quota_enforced,
        "trial_hours": s.trial_credits // 60,
        "trial_days": 7,
    }


@app.get("/v1/workspaces")
def workspaces(user=Depends(identity), db=Depends(database)):
    query = select(Workspace, Member).join(Member).where(Member.user_id == user["id"])
    if user.get("workspace_id"):
        query = query.where(Workspace.id == user["workspace_id"])
    rows = db.execute(query).all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "role": m.role,
            "subscription": w.subscription,
            "credits": balance(db, w),
            "balance_micro_usdc": available(db, w.id),
            "has_key": db.get(Credential, w.id) is not None,
        }
        for w, m in rows
    ]


@app.post("/v1/workspaces", status_code=201)
def create_workspace(body: Named, user=Depends(identity), db=Depends(database)):
    if db.scalar(select(func.count()).select_from(Member).where(Member.user_id == user["id"])) >= 5:
        raise HTTPException(409, "Workspace limit reached")
    w = Workspace(name=body.name.strip())
    db.add(w)
    db.flush()
    db.add(Member(workspace_id=w.id, user_id=user["id"], email=user["email"], role="owner"))
    db.commit()
    return {"id": w.id, "name": w.name}


@app.get("/v1/workspaces/{wid}/members")
def members(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    return [
        {"id": m.id, "email": m.email, "role": m.role}
        for m in db.scalars(select(Member).where(Member.workspace_id == wid))
    ]


@app.post("/v1/workspaces/{wid}/invitations")
def invite(wid: str, body: InviteBody, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True, lock=True)
    count = db.scalar(select(func.count()).select_from(Member).where(Member.workspace_id == wid))
    if count >= 3:
        raise HTTPException(409, "This plan supports three members")
    token = secrets.token_urlsafe(32)
    db.add(
        Invitation(
            workspace_id=wid, email=body.email.lower(), token_hash=digest(token), expires_at=now() + timedelta(days=7)
        )
    )
    db.commit()
    return {"url": settings().public_url + "/invite?token=" + token, "expires_in_days": 7}


@app.post("/v1/invitations/{token}/accept")
def accept(token: str, user=Depends(identity), db=Depends(database)):
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == digest(token)).with_for_update())
    if not inv or inv.expires_at < now() or inv.accepted_at or inv.email != user["email"].lower():
        raise HTTPException(400, "Invitation is invalid, expired, or belongs to a different email")
    db.scalar(select(Workspace).where(Workspace.id == inv.workspace_id).with_for_update())
    if db.scalar(select(func.count()).select_from(Member).where(Member.workspace_id == inv.workspace_id)) >= 3:
        raise HTTPException(409, "Workspace is full")
    if not db.scalar(select(Member).where(Member.workspace_id == inv.workspace_id, Member.user_id == user["id"])):
        db.add(Member(workspace_id=inv.workspace_id, user_id=user["id"], email=user["email"]))
    inv.accepted_at = now()
    db.commit()
    return {"workspace_id": inv.workspace_id}


@app.delete("/v1/workspaces/{wid}/members/{mid}")
def remove_member(wid: str, mid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True, lock=True)
    m = db.get(Member, mid)
    if not m or m.workspace_id != wid or m.role == "owner":
        raise HTTPException(400, "Cannot remove this membership")
    db.delete(m)
    db.commit()
    return {"ok": True}


@app.put("/v1/workspaces/{wid}/credential")
async def credential(wid: str, body: KeyBody, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": body.key, "anthropic-version": "2023-06-01"},
            )
            r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(400, "Could not validate this Anthropic API key") from None
    row = db.get(Credential, wid) or Credential(workspace_id=wid)
    row.encrypted_key = seal(body.key)
    row.suffix = body.key[-4:]
    db.add(row)
    db.commit()
    return {"suffix": row.suffix}


@app.delete("/v1/workspaces/{wid}/credential")
def delete_credential(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True)
    row = db.get(Credential, wid)
    if row:
        db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/v1/workspaces/{wid}/computers")
def computers(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    rows = db.execute(
        select(Computer, DesktopProfile)
        .outerjoin(DesktopProfile, DesktopProfile.computer_id == Computer.id)
        .where(Computer.workspace_id == wid, Computer.status != "deleted")
        .order_by(Computer.created_at)
    ).all()
    return [
        {
            **public(c),
            "cpu": p.cpu if p else 2,
            "memory_gib": p.memory_gib if p else 4,
            "storage_gib": p.storage_gib if p else 20,
            "resolution": p.resolution if p else "1440x900",
            "os": p.os if p else "linux",
            "gpu": p.gpu if p else 0,
        }
        for c, p in rows
    ]


@app.post("/v1/workspaces/{wid}/computers", status_code=201)
def create_computer(
    wid: str,
    body: ComputerCreate,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    w = member(db, wid, user, lock=True)
    old = db.scalar(select(Computer).where(Computer.workspace_id == wid, Computer.request_id == idempotency_key))
    if old:
        return public(old)
    if not can_run(db, w):
        raise HTTPException(402, "Buy a pass, add platform credits, or activate a trial first")
    check_saved(db, w)
    providers.validate(body.os, body.gpu, body.cpu, body.memory_gib, body.storage_gib)
    c = Computer(workspace_id=wid, name=body.name.strip(), request_id=idempotency_key)
    db.add(c)
    db.flush()
    db.add(
        DesktopProfile(
            computer_id=c.id,
            cpu=body.cpu,
            memory_gib=body.memory_gib,
            storage_gib=body.storage_gib,
            resolution=body.resolution,
            idle_timeout_minutes=body.idle_timeout_minutes,
            os=body.os,
            gpu=body.gpu,
        )
    )
    db.commit()
    return public(c)


@app.patch("/v1/computers/{cid}")
def rename_computer(cid: str, body: Named, user=Depends(identity), db=Depends(database)):
    c = computer(db, cid, user, lock=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name cannot be blank")
    if name != c.name:
        c.name = name
        event(db, cid, f"Computer renamed to {name}", "activity")
        db.commit()
    return public(c)


@app.post("/v1/computers/{cid}/actions/{action}")
def computer_action(
    cid: str,
    action: Literal["start", "stop", "take-control", "resume", "heartbeat"],
    user=Depends(identity),
    db=Depends(database),
):
    c = computer(db, cid, user)
    w = member(db, c.workspace_id, user, lock=True)
    db.refresh(c, with_for_update=True)
    if c.status in ("copying", "customizing", "copy_failed"):
        raise HTTPException(409, "Wait for the desktop copy to finish; failed copies must be deleted")
    active = db.scalar(
        select(Run).where(
            Run.computer_id == cid,
            (Run.status.in_(["queued", "running", "paused", "awaiting_approval"])) | Run.lease.is_not(None),
        )
    )
    if action == "start":
        if c.status in ("running", "starting"):
            return public(c)
        heartbeat = db.get(ServiceHeartbeat, "desktop-worker")
        if not heartbeat or now() - heartbeat.updated_at > timedelta(seconds=30):
            raise HTTPException(503, "Desktop service is unavailable. Please try again shortly.")
        if c.status in ("stopping", "deleting"):
            raise HTTPException(409, "Wait for the computer to stop")
        if not can_run(db, w):
            raise HTTPException(402, "No pass or credits available")
        check_running(db, w, cid)
        c.status = "starting"
        c.error = None
    elif action == "stop":
        c.status = "stopping"
        if active:
            active.status = "interrupted"
    elif action == "take-control":
        if c.status != "running":
            raise HTTPException(409, "Start the computer first")
        # A leased run acknowledges pause at a tool boundary before the viewer gains control.
        c.controller = "pending:" + user["id"] if active and active.lease else user["id"]
        if active:
            active.status = "paused"
    elif action == "resume":
        c.controller = "agent"
        if active and active.status == "paused":
            active.status = "queued"
    elif action == "heartbeat" and c.controller != user["id"]:
        raise HTTPException(409, "You do not control this computer")
    c.last_active = now()
    db.commit()
    return public(c)


@app.delete("/v1/computers/{cid}")
def delete_computer(cid: str, confirm: str, user=Depends(identity), db=Depends(database)):
    c = computer(db, cid, user)
    member(db, c.workspace_id, user, owner=True, lock=True)
    db.refresh(c, with_for_update=True)
    if c.status in ("copying", "customizing"):
        raise HTTPException(409, "Wait for the desktop copy to finish")
    if confirm != c.name:
        raise HTTPException(400, "Type the computer name to confirm deletion")
    c.status = "deleting"
    for run in db.scalars(
        select(Run).where(Run.computer_id == cid, Run.status.in_(["running", "queued", "paused", "awaiting_approval"]))
    ):
        run.status = "canceled"
    db.commit()
    return {"ok": True}


@app.post("/v1/computers/{cid}/runs", status_code=201)
def submit(
    cid: str,
    body: TaskBody,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    c = computer(db, cid, user, lock=True)
    old = db.scalar(select(Run).where(Run.computer_id == cid, Run.request_id == idempotency_key))
    if old:
        return {"id": old.id, "status": old.status}
    providers.require_for(db, cid, "agent")
    if c.status != "running" or c.controller != "agent":
        raise HTTPException(409, "Start the computer and return control to the agent")
    if not db.get(Credential, c.workspace_id):
        raise HTTPException(409, "Connect your Anthropic API key in settings")
    if balance(db, member(db, c.workspace_id, user)) <= 0:
        raise HTTPException(402, "No credits remaining")
    if db.scalar(
        select(Run).where(
            Run.computer_id == cid,
            (Run.status.in_(["queued", "running", "paused", "awaiting_approval"])) | Run.lease.is_not(None),
        )
    ):
        raise HTTPException(409, "Finish or cancel the current task first")
    r = Run(computer_id=cid, prompt=body.prompt, request_id=idempotency_key)
    db.add(r)
    db.flush()
    event(db, cid, body.prompt, "user", r.id)
    c.last_active = now()
    db.commit()
    return {"id": r.id, "status": r.status}


@app.get("/v1/computers/{cid}/runs")
def runs(cid: str, user=Depends(identity), db=Depends(database)):
    computer(db, cid, user)
    return [
        {"id": r.id, "prompt": r.prompt, "status": r.status, "approval": r.approval, "steps": r.steps}
        for r in db.scalars(select(Run).where(Run.computer_id == cid).order_by(Run.created_at.desc()).limit(20))
    ]


@app.post("/v1/runs/{rid}/{action}")
def run_action(rid: str, action: Literal["approve", "reject", "cancel"], user=Depends(identity), db=Depends(database)):
    r = db.scalar(select(Run).where(Run.id == rid).with_for_update())
    if not r:
        raise HTTPException(404, "Task not found")
    c = computer(db, r.computer_id, user)
    if action == "cancel":
        r.status = "canceled"
    else:
        if r.status != "awaiting_approval" or not r.approval:
            raise HTTPException(409, "No pending approval")
        if c.status != "running":
            raise HTTPException(409, "Restart the computer before responding")
        r.approval = {**r.approval, "decision": action, "user_id": user["id"]}
        r.status = "queued"
    event(
        db,
        c.id,
        {"approve": "Action approved", "reject": "Action declined", "cancel": "Task canceled"}[action],
        "info",
        r.id,
    )
    db.commit()
    return {"status": r.status}


@app.get("/v1/computers/{cid}/events")
def events(cid: str, after: int = 0, user=Depends(identity), db=Depends(database)):
    computer(db, cid, user)
    return [
        {"id": e.id, "kind": e.kind, "text": e.text, "run_id": e.run_id, "created_at": e.created_at}
        for e in db.scalars(
            select(Event).where(Event.computer_id == cid, Event.id > after).order_by(Event.id).limit(200)
        )
    ]


@app.get("/v1/computers/{cid}/stream")
async def stream(cid: str, after: int = 0, user=Depends(identity), db=Depends(database)):
    computer(db, cid, user)

    async def generate():
        cursor = after
        for _ in range(300):
            with Session() as session:
                computer(session, cid, user)
                rows = session.scalars(
                    select(Event).where(Event.computer_id == cid, Event.id > cursor).order_by(Event.id).limit(100)
                ).all()
                for e in rows:
                    cursor = e.id
                    yield f"id: {e.id}\ndata: {json.dumps({'id': e.id, 'kind': e.kind, 'text': e.text})}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@app.post("/v1/trials/intents")
def trial_intent(body: IntentBody, user=Depends(identity), db=Depends(database)):
    member(db, body.workspace_id, user, owner=True)
    intent = create_intent(db, body.workspace_id, user, body.service, body.wallet)
    return {"id": intent.id, "message": intent.message, "expires_at": intent.expires_at}


def owned_intent(db, iid, user, redeeming=False):
    i = db.scalar(select(TrialIntent).where(TrialIntent.id == iid, TrialIntent.user_id == user["id"]).with_for_update())
    if not i or i.expires_at + (timedelta(days=7) if redeeming and i.verified_at else timedelta()) < now():
        raise HTTPException(400, "Enrollment expired or not found")
    member(db, i.workspace_id, user, owner=True)
    return i


@app.post("/v1/trials/intents/{iid}/verify-wallet")
async def verify_wallet(iid: str, body: SignatureBody, user=Depends(identity), db=Depends(database)):
    i = owned_intent(db, iid, user)
    if i.verified_at:
        raise HTTPException(409, "Wallet already verified")
    i.wallet = await ChainVerifier().wallet(i.wallet, i.message, body.signature)
    used = db.scalar(
        select(Entitlement).where(
            Entitlement.chain == i.chain, Entitlement.wallet == i.wallet, Entitlement.service == i.service
        )
    )
    if used:
        raise HTTPException(409, "This wallet has already used its trial. Do not send tokens.")
    i.verified_at = now()
    db.commit()
    s = settings()
    return {
        "recipient": s.trial_recipient,
        "token": s.trial_token,
        "chain": s.trial_chain,
        "amount": "1",
        "amount_atomic": str(10**s.trial_decimals),
        "minimum_remaining": "10000",
        "expires_at": i.expires_at,
    }


@app.post("/v1/trials/intents/{iid}/redeem")
async def redeem(iid: str, body: PaymentBody, user=Depends(identity), db=Depends(database)):
    i = owned_intent(db, iid, user, redeeming=True)
    if not i.verified_at:
        raise HTTPException(403, "Verify wallet ownership first")
    proof = await ChainVerifier().payment(body.transaction_id, i.wallet)
    if proof.transaction_id != body.transaction_id:
        raise HTTPException(400, "Transaction does not match")
    try:
        e = activate(db, i, proof)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Trial or payment already redeemed") from None
    return {"id": e.id, "service": e.service, "expires_at": e.expires_at, "credits": e.remaining}


@app.get("/v1/workspaces/{wid}/entitlements")
def entitlements(wid: str, user=Depends(identity), db=Depends(database)):
    w = member(db, wid, user)
    return {
        "subscription": w.subscription,
        "credits": balance(db, w),
        "balance_micro_usdc": available(db, w.id),
        "trials": [
            {
                "service": e.service,
                "expires_at": e.expires_at,
                "credits": e.remaining,
                "active": e.expires_at > now() and e.remaining > 0,
            }
            for e in db.scalars(select(Entitlement).where(Entitlement.workspace_id == wid))
        ],
    }


# Register isolated payment and desktop-gateway modules after core routes.

app.include_router(features_router)
app.include_router(api_keys_router)
app.include_router(computer_api_router)
app.include_router(secrets_router)
app.include_router(apps_router)
app.include_router(template_registry_router)
app.include_router(automations_router)
app.include_router(screens_router)
app.include_router(fleet_router)
app.include_router(providers.router)
app.include_router(plans.router)
app.include_router(runtime_billing.router)
app.include_router(onboarding_router)
app.include_router(operations_router)
app.include_router(billing_router)
app.include_router(crypto_router)
app.include_router(gateway_router)


@app.middleware("http")
async def count_requests(request, call_next):
    response = await call_next(request)
    request_counts[str(response.status_code)] += 1
    return response

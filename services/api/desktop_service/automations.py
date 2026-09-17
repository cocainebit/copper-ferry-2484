"""Automations: triggers that run commands, built-in agent tasks, or lifecycle actions on a computer.

Triggers
  schedule   five-field cron in an IANA time zone
  interval   every N minutes (N >= 5)
  webhook    POST /v1/hooks/{id} with the automation's secret token (shown once)
  file       a path under Home was created or changed (polled while the computer runs)
  process    a named process is not running (polled while the computer runs)

Actions
  command     shell command as administrator, detached, with log and exit status (timeout applies)
  agent_task  submit a prompt to the built-in Claude agent (needs the workspace Anthropic key)
  start / stop  lifecycle

Every firing becomes a durable AutomationRun keyed by trigger slot, so a restart never double-fires the
same slot. Missed schedule slots are not backfilled: only the most recent due slot runs. An execution
that finds the computer stopped starts it when start_if_stopped is set, otherwise it is skipped.
"""

import secrets
import shlex
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from . import db as models
from . import runtime
from .cron import Cron, CronError
from .db import Base, Computer, Credential, Run, Workspace, database, event, now, uid
from .entitlements import balance
from .security import digest, identity, member

router = APIRouter(prefix="/v1")

MIN_GAP_MINUTES = 5
MAX_PER_COMPUTER = 20
MAX_RUNS_PER_DAY = 300
WATCH_EVERY = timedelta(seconds=30)
LOG_LIMIT = 32_000
ROOT = "/opt/cubicle/automations"
ACTIVE_RUN = ["queued", "running", "paused", "awaiting_approval"]


class Automation(Base):
    __tablename__ = "automations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[dict] = mapped_column(JSON)
    action: Mapped[dict] = mapped_column(JSON)
    start_if_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=30)
    token_hash: Mapped[str | None] = mapped_column(String(64))
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime)
    watch_state: Mapped[str | None] = mapped_column(Text)
    watched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (UniqueConstraint("automation_id", "slot"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    automation_id: Mapped[str] = mapped_column(ForeignKey("automations.id"), index=True)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    slot: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String, default="queued")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Trigger(BaseModel):
    kind: Literal["schedule", "interval", "webhook", "file", "process"]
    cron: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    every_minutes: int | None = Field(default=None, ge=MIN_GAP_MINUTES, le=10080)
    path: str | None = Field(default=None, max_length=1024)
    process: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind == "schedule":
            if not self.cron:
                raise ValueError("Schedules need a cron expression")
            try:
                gap = Cron(self.cron, self.timezone).minimum_gap_minutes()
            except CronError as exc:
                raise ValueError(str(exc)) from None
            if gap < MIN_GAP_MINUTES:
                raise ValueError(f"Schedules may fire at most every {MIN_GAP_MINUTES} minutes")
        if self.kind == "interval" and not self.every_minutes:
            raise ValueError("Intervals need every_minutes")
        if self.kind == "file":
            if not self.path or self.path.startswith("/") or ".." in self.path.split("/"):
                raise ValueError("File triggers need a path relative to Home without '..'")
        if self.kind == "process" and not self.process:
            raise ValueError("Process triggers need a process name")
        return self


class Action(BaseModel):
    kind: Literal["command", "agent_task", "start", "stop"]
    command: str | None = Field(default=None, max_length=8000)
    prompt: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind == "command" and not (self.command or "").strip():
            raise ValueError("Command actions need a command")
        if self.kind == "agent_task" and not (self.prompt or "").strip():
            raise ValueError("Agent task actions need a prompt")
        return self


class AutomationBody(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    trigger: Trigger
    action: Action
    enabled: bool = True
    start_if_stopped: bool = False
    timeout_minutes: int = Field(default=30, ge=1, le=240)

    @model_validator(mode="after")
    def coherent(self):
        if self.action.kind == "start" and self.trigger.kind in ("file", "process"):
            raise ValueError("File and process triggers only fire while the computer runs; start makes no sense")
        return self


class AutomationUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")


def schedule_next(a, after):
    t = a.trigger
    if t["kind"] == "schedule":
        return Cron(t["cron"], t.get("timezone") or "UTC").next_after(after)
    if t["kind"] == "interval":
        return after + timedelta(minutes=t["every_minutes"])
    return None


def public(a):
    return {
        "id": a.id,
        "computer_id": a.computer_id,
        "name": a.name,
        "enabled": a.enabled,
        "trigger": a.trigger,
        "action": a.action,
        "start_if_stopped": a.start_if_stopped,
        "timeout_minutes": a.timeout_minutes,
        "next_fire_at": a.next_fire_at,
        "last_fired_at": a.last_fired_at,
        "created_at": a.created_at,
        "webhook_path": f"/v1/hooks/{a.id}" if a.trigger["kind"] == "webhook" else None,
    }


def run_public(r):
    return {
        "id": r.id,
        "slot": r.slot,
        "reason": r.reason,
        "status": r.status,
        "output": r.output[-8000:],
        "error": r.error,
        "run_id": r.run_id,
        "created_at": r.created_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
    }


def fire(db, a, slot, reason):
    """Queue one execution for a trigger slot. Returns None when the slot already fired or caps apply."""
    day_ago = now() - timedelta(days=1)
    if (
        db.scalar(
            select(func.count())
            .select_from(AutomationRun)
            .where(AutomationRun.automation_id == a.id, AutomationRun.created_at > day_ago)
        )
        >= MAX_RUNS_PER_DAY
    ):
        return None
    try:
        with db.begin_nested():
            r = AutomationRun(automation_id=a.id, computer_id=a.computer_id, slot=slot, reason=reason)
            db.add(r)
    except IntegrityError:
        return None
    a.last_fired_at = now()
    return r


def owned_computer(db, cid, user, owner=True):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=owner)
    return c


def owned_automation(db, aid, user, owner=True):
    a = db.get(Automation, aid)
    if not a:
        raise HTTPException(404, "Automation not found")
    member(db, a.workspace_id, user, owner=owner)
    return a


@router.get("/computers/{cid}/automations")
def list_automations(cid: str, user=Depends(identity), db=Depends(database)):
    owned_computer(db, cid, user, owner=False)
    rows = db.scalars(select(Automation).where(Automation.computer_id == cid).order_by(Automation.created_at))
    return [public(a) for a in rows]


@router.post("/computers/{cid}/automations", status_code=201)
def create_automation(cid: str, body: AutomationBody, user=Depends(identity), db=Depends(database)):
    c = owned_computer(db, cid, user)
    if db.scalar(select(func.count()).select_from(Automation).where(Automation.computer_id == cid)) >= MAX_PER_COMPUTER:
        raise HTTPException(409, f"A computer holds at most {MAX_PER_COMPUTER} automations")
    token = None
    a = Automation(
        workspace_id=c.workspace_id,
        computer_id=cid,
        name=body.name.strip(),
        enabled=body.enabled,
        trigger=body.trigger.model_dump(exclude_none=True),
        action=body.action.model_dump(exclude_none=True),
        start_if_stopped=body.start_if_stopped,
        timeout_minutes=body.timeout_minutes,
        created_by=user["id"],
    )
    if body.trigger.kind == "webhook":
        token = "cbh_" + secrets.token_urlsafe(32)
        a.token_hash = digest(token)
    a.next_fire_at = schedule_next(a, now())
    db.add(a)
    db.commit()
    return {**public(a), **({"webhook_token": token} if token else {})}


@router.patch("/automations/{aid}")
def update_automation(aid: str, body: AutomationUpdate, user=Depends(identity), db=Depends(database)):
    a = owned_automation(db, aid, user)
    if body.name is not None:
        a.name = body.name.strip()
    if body.enabled is not None and body.enabled != a.enabled:
        a.enabled = body.enabled
        # Re-enabling never replays slots that passed while disabled.
        a.next_fire_at = schedule_next(a, now()) if a.enabled else a.next_fire_at
        a.watch_state = None
    db.commit()
    return public(a)


@router.delete("/automations/{aid}")
def delete_automation(aid: str, user=Depends(identity), db=Depends(database)):
    a = owned_automation(db, aid, user)
    for r in db.scalars(select(AutomationRun).where(AutomationRun.automation_id == aid)):
        db.delete(r)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/automations/{aid}/run", status_code=202)
def run_now(aid: str, user=Depends(identity), db=Depends(database)):
    a = owned_automation(db, aid, user)
    r = fire(db, a, "manual:" + secrets.token_hex(8), "Run now by " + (user.get("email") or "a workspace owner"))
    if not r:
        raise HTTPException(429, "Daily execution limit reached")
    db.commit()
    return run_public(r)


@router.get("/automations/{aid}/runs")
def automation_runs(aid: str, user=Depends(identity), db=Depends(database)):
    owned_automation(db, aid, user, owner=False)
    rows = db.scalars(
        select(AutomationRun)
        .where(AutomationRun.automation_id == aid)
        .order_by(AutomationRun.created_at.desc())
        .limit(30)
    )
    return [run_public(r) for r in rows]


@router.post("/hooks/{aid}", status_code=202)
async def webhook(
    aid: str,
    request: Request,
    x_cubicle_token: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, max_length=100),
    db=Depends(database),
):
    a = db.get(Automation, aid)
    token = x_cubicle_token or request.query_params.get("token", "")
    if (
        not a
        or a.trigger.get("kind") != "webhook"
        or not a.token_hash
        or not secrets.compare_digest(a.token_hash, digest(token))
    ):
        raise HTTPException(404, "Unknown hook")
    if not a.enabled:
        raise HTTPException(409, "Automation is disabled")
    slot = "hook:" + (idempotency_key or secrets.token_hex(8))
    if idempotency_key:
        # Sender retries return the original execution instead of firing again.
        existing = db.scalar(
            select(AutomationRun).where(AutomationRun.automation_id == aid, AutomationRun.slot == slot)
        )
        if existing:
            return run_public(existing)
    recent = db.scalar(
        select(func.count())
        .select_from(AutomationRun)
        .where(AutomationRun.automation_id == aid, AutomationRun.created_at > now() - timedelta(seconds=10))
    )
    if recent:
        raise HTTPException(429, "Hooks accept at most one call every 10 seconds")
    r = fire(db, a, slot, "Webhook call")
    if not r:
        raise HTTPException(429, "Daily execution limit reached")
    db.commit()
    return run_public(r)


# Worker side ---------------------------------------------------------------------------------------


def watch_command(trigger):
    if trigger["kind"] == "file":
        path = shlex.quote("/home/desktop/" + trigger["path"])
        return f"stat -c %Y:%s {path} 2>/dev/null || echo absent; true"
    return f"pgrep -x {shlex.quote(trigger['process'])} >/dev/null && echo running || echo stopped; true"


def detached(command, run_id):
    log, code = f"{ROOT}/{run_id}.log", f"{ROOT}/{run_id}.exit"
    body = f"{command}\necho __CUBICLE_EXIT__=$?"
    return (
        f"mkdir -p {ROOT} && printf %s {shlex.quote(body)} > {ROOT}/{run_id}.sh && rm -f {code} && "
        f"(nohup sh -c '. /etc/profile; cd /home/desktop; sh {ROOT}/{run_id}.sh > {log} 2>&1; "
        f"tail -n 1 {log} | sed s/.*=// > {code}' >/dev/null 2>&1 &)"
    )


def poll_command(run_id):
    return f"tail -c {LOG_LIMIT} {ROOT}/{run_id}.log 2>/dev/null; echo; echo __POLL__; cat {ROOT}/{run_id}.exit 2>/dev/null; true"


def finish(db, r, status, error=None):
    r.status, r.error, r.finished_at = status, error, now()
    label = {"succeeded": "succeeded", "failed": "failed", "skipped": "skipped"}.get(status, status)
    a = db.get(Automation, r.automation_id)
    event(db, r.computer_id, f"Automation {a.name if a else ''} {label}" + (f": {error}" if error else ""), "info")


async def watch(db, a, c):
    """Poll a file or process trigger on a running computer; fire on a change after the baseline."""
    output = (await runtime.execute(c.sandbox_id, watch_command(a.trigger))).strip()
    a.watched_at = now()
    previous, a.watch_state = a.watch_state, output
    if previous is None:
        return None
    if a.trigger["kind"] == "file" and output != previous and output != "absent":
        return fire(db, a, f"file:{output}", f"{a.trigger['path']} changed")
    if a.trigger["kind"] == "process" and output == "stopped" and previous == "running":
        return fire(db, a, f"process:{now().isoformat()}", f"{a.trigger['process']} stopped")
    return None


def start_blocker(db, c):
    """Same credit and plan checks as a manual start; returns a reason to skip, or None."""
    from .fleet import check_running

    w = db.get(Workspace, c.workspace_id)
    if balance(db, w) <= 0:
        return "No credits to start the computer"
    try:
        check_running(db, w, c.id)
    except HTTPException as exc:
        return exc.detail
    return None


async def execute_run(db, r, a, c):
    kind = a.action["kind"]
    if kind == "stop":
        if c.status in ("running", "starting"):
            c.status = "stopping"
        finish(db, r, "succeeded")
        return
    if kind == "start":
        if c.status in ("stopped", "failed"):
            skip = start_blocker(db, c)
            if skip:
                finish(db, r, "skipped", skip)
                return
            c.status, c.error = "starting", None
        if c.status in ("starting", "running"):
            finish(db, r, "succeeded")
        else:
            finish(db, r, "skipped", f"Computer is {c.status}")
        return
    if c.status != "running":
        if c.status in ("stopped", "failed") and a.start_if_stopped:
            skip = start_blocker(db, c)
            if skip:
                finish(db, r, "skipped", skip)
                return
            c.status, c.error = "starting", None
            r.status = "waiting_computer"
            event(db, c.id, f"Automation {a.name} is starting the computer", "info")
        elif c.status == "starting" and (a.start_if_stopped or r.status == "waiting_computer"):
            r.status = "waiting_computer"
        elif r.status != "waiting_computer":
            finish(db, r, "skipped", "Computer was not running")
        return
    r.started_at = now()
    c.last_active = now()
    if kind == "command":
        await runtime.execute(c.sandbox_id, detached(a.action["command"], r.id))
        r.status = "running"
        return
    if kind == "agent_task":
        if not db.get(Credential, c.workspace_id):
            finish(db, r, "failed", "Connect an Anthropic API key to run agent tasks")
            return
        if c.controller != "agent" or db.scalar(
            select(Run).where(Run.computer_id == c.id, Run.status.in_(ACTIVE_RUN) | Run.lease.is_not(None))
        ):
            finish(db, r, "skipped", "The agent is busy or someone has taken control")
            return
        task = Run(computer_id=c.id, prompt=a.action["prompt"], request_id="automation:" + r.id)
        db.add(task)
        db.flush()
        event(db, c.id, a.action["prompt"], "user", task.id)
        r.run_id, r.status = task.id, "running"


async def track(db, r, a, c):
    if r.run_id:
        task = db.get(Run, r.run_id)
        if task and task.status not in ACTIVE_RUN:
            finish(
                db,
                r,
                "succeeded" if task.status == "completed" else "failed",
                None if task.status == "completed" else f"Agent task {task.status}",
            )
        return
    if c.status != "running":
        finish(db, r, "failed", "Computer stopped during the command")
        return
    output = await runtime.execute(c.sandbox_id, poll_command(r.id))
    log, _, code = output.rpartition("__POLL__")
    r.output = log.strip()[-LOG_LIMIT:]
    code = code.strip()
    if code:
        finish(db, r, "succeeded" if code == "0" else "failed", None if code == "0" else f"Exit status {code}")
    c.last_active = now()


async def tick():
    """One scheduler pass. Runs under the worker's singleton lock; each automation fails in isolation."""
    with models.Session() as db:
        current = now()
        for a in db.scalars(select(Automation).where(Automation.enabled.is_(True))).all():
            try:
                c = db.get(Computer, a.computer_id)
                if not c or c.status == "deleted":
                    a.enabled = False
                    continue
                kind = a.trigger["kind"]
                if kind in ("schedule", "interval") and a.next_fire_at and a.next_fire_at <= current:
                    slot_time = a.next_fire_at
                    # Skip ahead past missed slots; only the most recent due slot runs.
                    upcoming = schedule_next(a, slot_time)
                    while upcoming <= current:
                        slot_time, upcoming = upcoming, schedule_next(a, upcoming)
                    fire(db, a, f"slot:{slot_time.isoformat()}", f"Scheduled for {slot_time.isoformat()}Z")
                    a.next_fire_at = upcoming
                elif kind in ("file", "process") and c.status == "running" and c.sandbox_id:
                    if not a.watched_at or current - a.watched_at >= WATCH_EVERY:
                        await watch(db, a, c)
                elif kind in ("file", "process") and c.status != "running":
                    a.watch_state = None
                db.commit()
            except Exception:
                db.rollback()
        pending = db.scalars(
            select(AutomationRun)
            .where(AutomationRun.status.in_(["queued", "waiting_computer", "running"]))
            .order_by(AutomationRun.created_at)
        ).all()
        for r in pending:
            try:
                a = db.get(Automation, r.automation_id)
                c = db.get(Computer, r.computer_id)
                if not a or not c or c.status == "deleted":
                    finish(db, r, "skipped", "Automation or computer no longer exists")
                elif r.status == "waiting_computer" and current - r.created_at > timedelta(minutes=10):
                    finish(db, r, "failed", "Computer did not start within 10 minutes")
                elif (
                    r.status == "running"
                    and r.started_at
                    and current - r.started_at > timedelta(minutes=a.timeout_minutes)
                ):
                    if r.run_id and (task := db.get(Run, r.run_id)) and task.status in ACTIVE_RUN:
                        task.status = "canceled"
                    finish(db, r, "failed", f"Timed out after {a.timeout_minutes} minutes")
                elif r.status == "running":
                    await track(db, r, a, c)
                else:
                    await execute_run(db, r, a, c)
                db.commit()
            except Exception as exc:
                db.rollback()
                r = db.get(AutomationRun, r.id)
                if r and r.status in ("queued", "waiting_computer"):
                    finish(db, r, "failed", f"Could not run: {type(exc).__name__}")
                    db.commit()

"""Public computer-control primitives for external agents, SDKs, the CLI and the MCP server.

Each call drives the live desktop through the same guest tools the built-in agent uses. A caller may
operate a computer when nobody has taken manual control and no built-in task holds it, or when the
caller is the person currently in control. Calls are metered as activity so idle stop and billing see them.
"""

import time
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import runtime
from .db import Computer, Run, database, event, now
from .display import dimensions
from .feature_models import DesktopProfile
from .security import identity, member

router = APIRouter(prefix="/v1/computers/{cid}")

RATE_PER_SECOND = 10
BURST = 30
_buckets: dict[tuple[str, str], list[float]] = defaultdict(lambda: [BURST, time.monotonic()])


def throttle(actor, cid):
    """In-process token bucket per actor and computer. Multi-process deployments need a shared limiter."""
    bucket = _buckets[(actor, cid)]
    tokens, stamp = bucket
    current = time.monotonic()
    tokens = min(BURST, tokens + (current - stamp) * RATE_PER_SECOND)
    if tokens < 1:
        bucket[:] = [tokens, current]
        raise HTTPException(429, "Slow down: at most 10 computer actions per second")
    bucket[:] = [tokens - 1, current]


def operator(db, cid, user):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    if c.status != "running":
        raise HTTPException(409, "Start the computer first")
    if c.controller != user["id"]:
        if c.controller != "agent":
            raise HTTPException(409, "Someone else has taken control of this computer")
        busy = db.scalar(
            select(Run).where(
                Run.computer_id == cid,
                (Run.status.in_(["queued", "running", "paused", "awaiting_approval"])) | Run.lease.is_not(None),
            )
        )
        if busy:
            raise HTTPException(409, "A built-in task is using this computer; cancel it first")
    from .providers import require_for

    require_for(db, cid, "computer_api")
    throttle(user.get("api_key") or user["id"], cid)
    return c


def target(db, cid, number):
    """X display for a validated screen number (0 is the primary desktop)."""
    from .screens import display, require_screen

    require_screen(db, cid, number)
    return display(number)


def touch(db, c, text):
    c.last_active = now()
    event(db, c.id, text, "activity")
    db.commit()


class Click(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    x: int = Field(ge=0, le=8192)
    y: int = Field(ge=0, le=8192)
    button: Literal["left", "right", "middle"] = "left"
    count: Literal[1, 2, 3] = 1


class Drag(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    from_: list[int] = Field(alias="from", min_length=2, max_length=2)
    to: list[int] = Field(min_length=2, max_length=2)


class Scroll(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    x: int = Field(ge=0, le=8192)
    y: int = Field(ge=0, le=8192)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=3, ge=1, le=100)


class Type(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    text: str = Field(min_length=1, max_length=10000)


class Key(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+\-]+$")


class Bash(BaseModel):
    command: str = Field(min_length=1, max_length=8000)


class Wait(BaseModel):
    screen: int = Field(default=0, ge=0, le=3)
    seconds: float = Field(default=1, ge=0, le=10)


def public(c, p):
    return {
        "id": c.id,
        "name": c.name,
        "workspace_id": c.workspace_id,
        "status": c.status,
        "controller": c.controller,
        "error": c.error,
        "created_at": c.created_at,
        "cpu": p.cpu if p else 2,
        "memory_gib": p.memory_gib if p else 4,
        "storage_gib": p.storage_gib if p else 20,
        "resolution": p.resolution if p else "1440x900",
        "idle_timeout_minutes": p.idle_timeout_minutes if p else 15,
    }


@router.get("")
def get_computer(cid: str, user=Depends(identity), db=Depends(database)):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    return public(c, db.get(DesktopProfile, cid))


@router.post("/screenshot")
async def screenshot(cid: str, screen: int = 0, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    image = await runtime.tool(c.sandbox_id, "computer", {"action": "screenshot"}, display=target(db, cid, screen))
    from .screens import listing

    resolution = next(s["resolution"] for s in listing(db, c) if s["number"] == screen)
    width, height = dimensions(resolution)
    c.last_active = now()
    db.commit()
    return {"format": "png", "width": width, "height": height, "image": image.strip()}


@router.post("/click")
async def click(cid: str, body: Click, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    action = {1: f"{body.button}_click", 2: "double_click", 3: "triple_click"}[body.count]
    if body.count > 1 and body.button != "left":
        raise HTTPException(422, "Multi-clicks use the left button")
    await runtime.tool(
        c.sandbox_id,
        "computer",
        {"action": action, "coordinate": [body.x, body.y]},
        display=target(db, cid, body.screen),
    )
    touch(db, c, f"api: {action} at {body.x},{body.y}")
    return {"ok": True}


@router.post("/drag")
async def drag(cid: str, body: Drag, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    await runtime.tool(
        c.sandbox_id,
        "computer",
        {"action": "mouse_move", "coordinate": body.from_},
        display=target(db, cid, body.screen),
    )
    await runtime.tool(
        c.sandbox_id,
        "computer",
        {"action": "left_click_drag", "coordinate": body.to},
        display=target(db, cid, body.screen),
    )
    touch(db, c, f"api: drag {body.from_} to {body.to}")
    return {"ok": True}


@router.post("/scroll")
async def scroll(cid: str, body: Scroll, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    await runtime.tool(
        c.sandbox_id,
        "computer",
        {"action": "mouse_move", "coordinate": [body.x, body.y]},
        display=target(db, cid, body.screen),
    )
    await runtime.tool(
        c.sandbox_id,
        "computer",
        {"action": "scroll", "scroll_direction": body.direction, "scroll_amount": body.amount},
        display=target(db, cid, body.screen),
    )
    touch(db, c, f"api: scroll {body.direction} {body.amount}")
    return {"ok": True}


@router.post("/type")
async def type_text(cid: str, body: Type, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    await runtime.tool(
        c.sandbox_id, "computer", {"action": "type", "text": body.text}, display=target(db, cid, body.screen)
    )
    touch(db, c, f"api: typed {len(body.text)} characters")
    return {"ok": True}


@router.post("/key")
async def key(cid: str, body: Key, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    await runtime.tool(
        c.sandbox_id, "computer", {"action": "key", "text": body.key}, display=target(db, cid, body.screen)
    )
    touch(db, c, f"api: key {body.key}")
    return {"ok": True}


@router.post("/bash")
async def bash(cid: str, body: Bash, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    try:
        output = await runtime.tool(c.sandbox_id, "bash", {"command": body.command})
    except runtime.CommandFailed as exc:
        touch(db, c, "api: shell command failed")
        code = "timed out after 45 seconds" if str(exc.status) == "124" else f"exit status {exc.status}"
        return {"output": exc.output[:200000], "error": code, "exit_code": exc.status}
    except RuntimeError as exc:
        touch(db, c, "api: shell command failed")
        return {"output": "", "error": str(exc)[:4000], "exit_code": None}
    touch(db, c, "api: shell command")
    return {"output": output[:200000], "error": None, "exit_code": 0}


@router.post("/wait")
async def wait(cid: str, body: Wait, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    await runtime.tool(
        c.sandbox_id, "computer", {"action": "wait", "duration": body.seconds}, display=target(db, cid, body.screen)
    )
    return {"ok": True}

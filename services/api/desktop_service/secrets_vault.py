"""Workspace secrets: named values encrypted at rest and handed to computers at boot, never baked in.

Values reach a computer as an env file on /dev/shm (tmpfs, so never part of a system snapshot) that
login shells source: the dashboard terminal, the computer API's bash route and the built-in agent's
bash tool all see them. Values are never returned by the API and never written to activity events.
"""

import base64
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from . import runtime
from .db import Base, Computer, database, event, now, uid
from .feature_models import DesktopProfile
from .security import identity, member, seal, unseal

router = APIRouter(prefix="/v1")

NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
RESERVED = {
    "HOME",
    "PATH",
    "DISPLAY",
    "TERM",
    "LANG",
    "USER",
    "SHELL",
    "PWD",
    "VNC_PASSWORD",
    "PTY_TOKEN",
    "CHROMIUM_DEV_FLAGS",
    "DESKTOP_RESOLUTION",
}
MAX_SECRETS = 50
ENV_FILE = "/dev/shm/cubicle/secrets.env"
PROFILE_HOOK = "[ -r /dev/shm/cubicle/secrets.env ] && . /dev/shm/cubicle/secrets.env"


class Secret(Base):
    __tablename__ = "workspace_secrets"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=8192)


class Allowlist(BaseModel):
    names: list[str] | None = Field(default=None, max_length=MAX_SECRETS)


def public(s):
    return {
        "id": s.id,
        "name": s.name,
        "created_by": s.created_by,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def valid_name(name):
    if not NAME.match(name) or name in RESERVED:
        raise HTTPException(
            422, "Secret names are UPPER_SNAKE_CASE, up to 64 characters, and cannot shadow system variables"
        )
    return name


def env_file(mapping):
    """Shell-safe export lines; single quotes in values are closed, escaped and reopened."""
    return "".join(
        f"export {name}='{value.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
        for name, value in sorted(mapping.items())
    )


def injection_script(mapping):
    payload = base64.b64encode(env_file(mapping).encode()).decode()
    return (
        "mkdir -p /dev/shm/cubicle && umask 077 && "
        f"printf %s {payload} | base64 -d > {ENV_FILE} && "
        f"chown desktop:desktop /dev/shm/cubicle {ENV_FILE} && chmod 700 /dev/shm/cubicle && chmod 600 {ENV_FILE}"
    )


def mapping_for(db, c):
    profile = db.get(DesktopProfile, c.id)
    allowed = set(profile.secret_names) if profile and profile.secret_names is not None else None
    rows = db.scalars(select(Secret).where(Secret.workspace_id == c.workspace_id).order_by(Secret.name))
    return {s.name: unseal(s.encrypted_value) for s in rows if allowed is None or s.name in allowed}


async def inject(db, c):
    """Write the computer's secrets into its running sandbox. Callers commit."""
    mapping = mapping_for(db, c)
    await runtime.execute(c.sandbox_id, injection_script(mapping))
    profile = db.get(DesktopProfile, c.id) or DesktopProfile(computer_id=c.id)
    profile.secrets_injected_at = now()
    db.add(profile)
    event(
        db, c.id, f"{len(mapping)} secret{'s' if len(mapping) != 1 else ''} available to shells and the agent", "info"
    )
    return len(mapping)


def owned(db, cid, user, owner=True):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=owner)
    return c


@router.get("/workspaces/{wid}/secrets")
def list_secrets(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    return [public(s) for s in db.scalars(select(Secret).where(Secret.workspace_id == wid).order_by(Secret.name))]


@router.put("/workspaces/{wid}/secrets/{name}")
def put_secret(wid: str, name: str, body: SecretBody, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True, lock=True)
    valid_name(name)
    row = db.scalar(select(Secret).where(Secret.workspace_id == wid, Secret.name == name))
    if not row:
        count = db.scalar(select(func.count()).select_from(Secret).where(Secret.workspace_id == wid))
        if count >= MAX_SECRETS:
            raise HTTPException(409, f"A workspace holds at most {MAX_SECRETS} secrets")
        row = Secret(workspace_id=wid, name=name, created_by=user["id"], encrypted_value="")
        db.add(row)
    row.encrypted_value = seal(body.value)
    row.updated_at = now()
    db.commit()
    return public(row)


@router.delete("/workspaces/{wid}/secrets/{name}")
def delete_secret(wid: str, name: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True, lock=True)
    row = db.scalar(select(Secret).where(Secret.workspace_id == wid, Secret.name == name))
    if not row:
        raise HTTPException(404, "Secret not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/computers/{cid}/secrets")
def computer_secrets(cid: str, user=Depends(identity), db=Depends(database)):
    c = owned(db, cid, user, owner=False)
    profile = db.get(DesktopProfile, cid)
    return {
        "names": sorted(mapping_for(db, c)),
        "allowlist": profile.secret_names if profile else None,
        "injected_at": profile.secrets_injected_at if profile else None,
        "where": "Login shells: dashboard terminal, computer API bash, built-in agent bash. Not desktop menu apps.",
    }


@router.put("/computers/{cid}/secrets")
def set_allowlist(cid: str, body: Allowlist, user=Depends(identity), db=Depends(database)):
    c = owned(db, cid, user)
    names = None if body.names is None else sorted({valid_name(n) for n in body.names})
    profile = db.get(DesktopProfile, cid) or DesktopProfile(computer_id=cid)
    profile.secret_names = names
    db.add(profile)
    db.commit()
    return {"allowlist": names, "names": sorted(mapping_for(db, c))}


@router.post("/computers/{cid}/secrets/refresh")
async def refresh(cid: str, user=Depends(identity), db=Depends(database)):
    c = owned(db, cid, user)
    if c.status != "running" or not c.sandbox_id:
        raise HTTPException(409, "Start the computer first; stopped computers receive secrets at boot")
    count = await inject(db, c)
    db.commit()
    return {"injected": count}

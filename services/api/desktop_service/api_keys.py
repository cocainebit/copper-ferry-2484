"""Workspace API keys for agents and scripts that drive computers without a browser session.

A key acts as the member who created it, inside one workspace, with an explicit scope:
  read     list and inspect computers, files, events and runs
  control  drive a computer: screenshot, mouse, keyboard, shell, files
  manage   create, start, stop, rename, configure, clone and delete computers, submit built-in tasks
Keys can never manage other keys, the workspace's Anthropic credential, members, invitations, trials or
payments; those stay session-only. Only the hash is stored; the secret is shown once at creation.
"""

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, database, now, uid
from .security import digest, identity, member

router = APIRouter(prefix="/v1")

SCOPES = ("read", "control", "manage")
PREFIX = "cbk_"
MAX_KEYS = 20

# Route templates a key may call with a mutating method, by required scope. Everything else is
# session-only. GET routes need only "read", which every key has.
CONTROL_ROUTES = {
    "/v1/computers/{cid}/screenshot",
    "/v1/computers/{cid}/click",
    "/v1/computers/{cid}/drag",
    "/v1/computers/{cid}/scroll",
    "/v1/computers/{cid}/type",
    "/v1/computers/{cid}/key",
    "/v1/computers/{cid}/bash",
    "/v1/computers/{cid}/wait",
    "/v1/computers/{cid}/terminal",
    "/v1/computers/{cid}/upload",
    "/v1/computers/{cid}/delete-file",
    "/v1/computers/{cid}/apps/{app_id}/launch",
    "/v1/computers/{cid}/apps/check",
    "/v1/computers/{cid}/secrets/refresh",
}
MANAGE_ROUTES = {
    "/v1/workspaces/{wid}/computers",
    "/v1/computers/{cid}",
    "/v1/computers/{cid}/actions/{action}",
    "/v1/computers/{cid}/runs",
    "/v1/runs/{rid}/{action}",
    "/v1/computers/{cid}/profile",
    "/v1/computers/{cid}/clone",
    "/v1/computers/{cid}/templates",
    "/v1/templates/{tid}/computers",
    "/v1/templates/{tid}",
    "/v1/computers/{cid}/apps/{app_id}/install",
    "/v1/computers/{cid}/apps/{app_id}/remove",
    "/v1/computers/{cid}/secrets",
    "/v1/workspaces/{wid}/template-definitions",
    "/v1/templates/{tid}/rebuild",
    "/v1/computers/{cid}/automations",
    "/v1/automations/{aid}",
    "/v1/automations/{aid}/run",
    "/v1/computers/{cid}/screens",
    "/v1/computers/{cid}/screens/{number}",
    "/v1/computers/{cid}/labels",
    "/v1/workspaces/{wid}/computers/bulk",
    "/v1/computers/{cid}/move",
}


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    scopes: list[str] = Field(default=["read", "control"], min_length=1, max_length=3)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def scope_list(key):
    return [s for s in key.scopes.split(",") if s]


def public(k):
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "scopes": scope_list(k),
        "created_at": k.created_at,
        "expires_at": k.expires_at,
        "last_used_at": k.last_used_at,
        "revoked_at": k.revoked_at,
    }


def resolve(db, token):
    """Return the identity a valid key acts as, or None when the token is not a live key."""
    if not token.startswith(PREFIX):
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest(token)))
    if not key or key.revoked_at or (key.expires_at and key.expires_at < now()):
        return None
    if not key.last_used_at or now() - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now()
        db.commit()
    return {
        "id": key.created_by,
        "email": "",
        "verified": True,
        "api_key": key.id,
        "workspace_id": key.workspace_id,
        "scopes": scope_list(key),
    }


def authorize_request(user, request: Request):
    """Enforce key scopes against the matched route. Sessions pass through untouched."""
    if "api_key" not in user:
        return
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    if request.method in ("GET", "HEAD"):
        if "read" not in user["scopes"]:
            raise HTTPException(403, "This API key cannot read")
        return
    if path in CONTROL_ROUTES:
        needed = "control"
    elif path in MANAGE_ROUTES:
        needed = "manage"
    else:
        raise HTTPException(403, "This action requires a signed-in session, not an API key")
    if needed not in user["scopes"]:
        raise HTTPException(403, f"This API key lacks the {needed} scope")


def session_only(user):
    if "api_key" in user:
        raise HTTPException(403, "API keys cannot manage API keys")


@router.get("/workspaces/{wid}/api-keys")
def list_keys(wid: str, user=Depends(identity), db=Depends(database)):
    session_only(user)
    member(db, wid, user, owner=True)
    rows = db.scalars(select(ApiKey).where(ApiKey.workspace_id == wid).order_by(ApiKey.created_at.desc()))
    return [public(k) for k in rows]


@router.post("/workspaces/{wid}/api-keys", status_code=201)
def create_key(wid: str, body: KeyCreate, user=Depends(identity), db=Depends(database)):
    session_only(user)
    member(db, wid, user, owner=True, lock=True)
    scopes = sorted(set(body.scopes), key=SCOPES.index) if set(body.scopes) <= set(SCOPES) else None
    if not scopes:
        raise HTTPException(422, "Scopes must be among read, control, manage")
    if "read" not in scopes:
        scopes = ["read", *scopes]
    live = db.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.workspace_id == wid, ApiKey.revoked_at.is_(None))
    )
    if live >= MAX_KEYS:
        raise HTTPException(409, f"This workspace already has {MAX_KEYS} active keys; revoke one first")
    prefix = PREFIX + secrets.token_hex(4)
    token = prefix + "_" + secrets.token_urlsafe(32)
    key = ApiKey(
        workspace_id=wid,
        created_by=user["id"],
        name=body.name.strip(),
        prefix=prefix,
        key_hash=digest(token),
        scopes=",".join(scopes),
        expires_at=now() + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    db.add(key)
    db.commit()
    return {**public(key), "key": token}


@router.delete("/api-keys/{kid}")
def revoke_key(kid: str, user=Depends(identity), db=Depends(database)):
    session_only(user)
    key = db.get(ApiKey, kid)
    if not key:
        raise HTTPException(404, "API key not found")
    member(db, key.workspace_id, user, owner=True)
    if not key.revoked_at:
        key.revoked_at = now()
        db.commit()
    return public(key)

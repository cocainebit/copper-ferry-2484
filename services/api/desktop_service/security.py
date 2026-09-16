import hashlib
import secrets
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from .config import settings
from .db import Member, Workspace

bearer = HTTPBearer(auto_error=False)


@lru_cache
def cipher():
    key = settings().encryption_key
    if not key and settings().dev_mode:
        path = Path(".local/encryption.key")
        path.parent.mkdir(exist_ok=True)
        if not path.exists():
            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
        key = path.read_text()
    return Fernet(key.encode())


def seal(value):
    return cipher().encrypt(value.encode()).decode()


def unseal(value):
    return cipher().decrypt(value.encode()).decode()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@lru_cache
def jwks():
    return jwt.PyJWKClient(settings().supabase_url + "/auth/v1/.well-known/jwks.json")


def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, "Sign in to continue")
    token = credentials.credentials
    if settings().dev_mode and secrets.compare_digest(token, settings().dev_token):
        return {"id": "local-user", "email": "you@localhost", "verified": True}
    try:
        key = jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=settings().supabase_url + "/auth/v1",
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
        if claims.get("role") != "authenticated" or not claims.get("sub") or claims.get("is_anonymous", False):
            raise ValueError("A registered user session is required")
        return {"id": claims["sub"], "email": claims.get("email", ""), "verified": bool(claims.get("email"))}
    except Exception:
        raise HTTPException(401, "Session expired; please sign in again") from None


def member(db, workspace_id, user, owner=False, lock=False):
    row = db.scalar(select(Member).where(Member.workspace_id == workspace_id, Member.user_id == user["id"]))
    if not row or (owner and row.role != "owner"):
        raise HTTPException(403, "Workspace access denied")
    query = select(Workspace).where(Workspace.id == workspace_id)
    return db.scalar(query.with_for_update() if lock else query)

import hashlib
import logging
import secrets
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .config import settings
from .db import Member, Workspace, database

log = logging.getLogger(__name__)
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


@lru_cache
def platform_jwks():
    return jwt.PyJWKClient(settings().platform_issuer + "/jwks")


def platform_identity(token):
    """The user behind a platform access token, or None when it is not one (or platform auth is off)."""
    config = settings()
    if not (config.platform_issuer and config.platform_audience):
        return None
    try:
        # Route on the unverified issuer so Supabase tokens never reach the platform's JWKS endpoint.
        unverified = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None  # not a JWT at all, so it belongs to one of the other schemes
    if unverified.get("iss") != config.platform_issuer:
        return None
    try:
        key = platform_jwks().get_signing_key_from_jwt(token).key
    except Exception as exc:
        # The token names our issuer and we still cannot get a key for it: that is an outage or a
        # misconfiguration here. Without this line every sign-in fails and nothing says why.
        log.warning("No signing key for a platform token: %s: %s", type(exc).__name__, exc)
        return None
    try:
        claims = jwt.decode(
            token,
            key,
            # better-auth signs with Ed25519 by default; ES256 and RS256 cover the other key types it offers.
            algorithms=["EdDSA", "ES256", "RS256"],
            audience=config.platform_audience,
            issuer=config.platform_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except Exception as exc:
        # Never log the token itself. The exception type says enough to tell an expired session from
        # a wrong audience, which is the difference between "sign in again" and "fix the config".
        log.info("Rejected a platform token: %s", type(exc).__name__)
        return None
    if not claims.get("sub"):
        return None
    email = claims.get("email", "")
    return {"id": claims["sub"], "email": email, "verified": bool(email), "platform": True}


def identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    request: Request = None,
    db=Depends(database),
):
    if not credentials:
        raise HTTPException(401, "Sign in to continue")
    token = credentials.credentials
    if settings().dev_mode and secrets.compare_digest(token, settings().dev_token):
        return {"id": "local-user", "email": "you@localhost", "verified": True}
    if token.startswith("cbk_"):
        from .api_keys import authorize_request, resolve

        user = resolve(db, token)
        if not user:
            raise HTTPException(401, "API key is invalid, expired or revoked")
        authorize_request(user, request)
        return user
    user = platform_identity(token)
    if user:
        # Linking runs only with a real session: identity() is also called directly in tests.
        if isinstance(db, OrmSession):
            try:
                from . import identity_link

                user = identity_link.ensure_linked(db, user) or user
            except Exception:
                # A linking failure must never lock someone out of a verified account.
                log.exception("Could not link platform identity %s", user["id"])
        return user
    # Supabase stays in the chain during the migration, so both token sources work at once.
    if not settings().supabase_url:
        raise HTTPException(401, "Session expired; please sign in again")
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
    if user.get("workspace_id") and user["workspace_id"] != workspace_id:
        raise HTTPException(403, "API key is scoped to a different workspace")
    row = db.scalar(select(Member).where(Member.workspace_id == workspace_id, Member.user_id == user["id"]))
    if not row or (owner and row.role != "owner"):
        raise HTTPException(403, "Workspace access denied")
    query = select(Workspace).where(Workspace.id == workspace_id)
    return db.scalar(query.with_for_update() if lock else query)

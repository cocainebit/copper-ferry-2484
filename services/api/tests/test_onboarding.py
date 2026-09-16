import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from desktop_service import security
from desktop_service.config import settings


@pytest.mark.parametrize(
    "change", [{"exp": None}, {"aud": "wrong"}, {"role": "service_role"}, {"is_anonymous": True}, {"exp": 1}]
)
def test_rejects_invalid_signed_sessions(monkeypatch, change):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        security,
        "jwks",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())),
    )
    claims = {
        "sub": "user",
        "email": "user@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": settings().supabase_url + "/auth/v1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    claims.update(change)
    if claims.get("exp") is None:
        claims.pop("exp")
    token = jwt.encode(claims, key, algorithm="ES256")
    with pytest.raises(HTTPException) as exc:
        security.identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert exc.value.status_code == 401


def test_valid_registered_session(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        security,
        "jwks",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())),
    )
    claims = {
        "sub": "user",
        "email": "user@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": settings().supabase_url + "/auth/v1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(claims, key, algorithm="ES256")
    assert security.identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))["id"] == "user"


def test_setup_is_owner_only_and_contains_no_keys(client, db):
    from desktop_service.db import Member

    response = client.get("/v1/workspaces/w/setup")
    assert response.status_code == 200
    assert "stripe_secret_key" not in response.text
    assert client.get("/v1/workspaces/other/setup").status_code == 403
    from sqlalchemy import select

    row = db.scalar(select(Member).where(Member.workspace_id == "w", Member.user_id == "local-user"))
    row.role = "member"
    db.commit()
    assert client.get("/v1/workspaces/w/setup").status_code == 403

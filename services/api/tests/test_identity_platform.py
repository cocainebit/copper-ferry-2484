import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from desktop_service import security
from desktop_service.config import settings

ISSUER = "http://platform.test/api/auth"
AUDIENCE = "http://cubicle.test"


def signer(algorithm):
    return ed25519.Ed25519PrivateKey.generate() if algorithm == "EdDSA" else ec.generate_private_key(ec.SECP256R1())


def serve(monkeypatch, name, key):
    monkeypatch.setattr(
        security,
        name,
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())),
    )


def platform_token(key, algorithm="ES256", **change):
    claims = {
        "sub": "platform-user",
        "email": "user@example.com",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    claims.update(change)
    # A None in `change` drops the claim, which is how the "missing claim" cases are written.
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm=algorithm)


def supabase_token(key):
    return jwt.encode(
        {
            "sub": "supabase-user",
            "email": "user@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            "iss": settings().supabase_url + "/auth/v1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        key,
        algorithm="ES256",
    )


def call(token, db=None):
    """Linking only runs with a real session, so pass one when the test cares about the hook."""
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return security.identity(credentials, db=db) if db is not None else security.identity(credentials)


@pytest.fixture(autouse=True)
def linked(monkeypatch):
    """identity_link belongs to another module; stub it so these tests only cover token verification."""
    seen = []

    def ensure_linked(db, user):
        seen.append(user)
        return dict(user, linked=True)

    # Patch the function on the real module: "from . import identity_link" reads the package
    # attribute, so replacing the sys.modules entry is ignored once the module has been imported.
    from desktop_service import identity_link

    monkeypatch.setattr(identity_link, "ensure_linked", ensure_linked)
    return seen


@pytest.fixture
def platform(monkeypatch):
    monkeypatch.setattr(settings(), "platform_issuer", ISSUER)
    monkeypatch.setattr(settings(), "platform_audience", AUDIENCE)


@pytest.mark.parametrize("algorithm", ["ES256", "EdDSA"])
def test_accepts_platform_access_token(monkeypatch, platform, linked, algorithm, db):
    key = signer(algorithm)
    serve(monkeypatch, "platform_jwks", key)
    user = call(platform_token(key, algorithm), db=db)
    assert user["id"] == "platform-user"
    assert user["email"] == "user@example.com"
    assert user["verified"] is True
    assert user["platform"] is True
    assert user["linked"] is True
    assert [u["id"] for u in linked] == ["platform-user"]


def test_platform_token_without_email_is_unverified(monkeypatch, platform):
    key = signer("ES256")
    serve(monkeypatch, "platform_jwks", key)
    user = call(platform_token(key, email=None))
    assert user["email"] == "" and user["verified"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"aud": "http://someone-else.test"},
        {"iss": "http://impostor.test/api/auth"},
        {"exp": int(time.time()) - 1},
        {"sub": None},
    ],
)
def test_rejects_bad_platform_tokens(monkeypatch, platform, change):
    key = signer("ES256")
    serve(monkeypatch, "platform_jwks", key)
    token = platform_token(key, **change)
    with pytest.raises(HTTPException) as exc:
        call(token)
    assert exc.value.status_code == 401


def test_platform_token_signed_by_a_stranger_is_rejected(monkeypatch, platform):
    serve(monkeypatch, "platform_jwks", signer("ES256"))
    with pytest.raises(HTTPException) as exc:
        call(platform_token(signer("ES256")))
    assert exc.value.status_code == 401


def test_supabase_sessions_survive_alongside_the_platform(monkeypatch, platform):
    serve(monkeypatch, "platform_jwks", signer("ES256"))
    supabase = signer("ES256")
    serve(monkeypatch, "jwks", supabase)
    user = call(supabase_token(supabase))
    assert user["id"] == "supabase-user"
    assert "platform" not in user


def test_unconfigured_platform_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings(), "platform_issuer", "")
    monkeypatch.setattr(settings(), "platform_audience", "")
    key = signer("ES256")
    serve(monkeypatch, "platform_jwks", key)
    serve(monkeypatch, "jwks", key)
    assert call(supabase_token(key))["id"] == "supabase-user"
    with pytest.raises(HTTPException) as exc:
        call(platform_token(key))
    assert exc.value.status_code == 401


def test_dev_token_still_wins(platform):
    assert call(settings().dev_token)["id"] == "local-user"


def test_linking_is_skipped_without_a_real_session(monkeypatch, platform, linked):
    """identity() is called directly in other tests; the hook must not run on a dependency sentinel."""
    key = signer("ES256")
    serve(monkeypatch, "platform_jwks", key)
    user = call(platform_token(key))
    assert user["platform"] is True and "linked" not in user and linked == []


def test_a_failing_link_never_locks_the_account_out(monkeypatch, platform, db):
    from desktop_service import identity_link

    def explode(db, user):
        raise RuntimeError("linking is broken")

    monkeypatch.setattr(identity_link, "ensure_linked", explode)
    key = signer("ES256")
    serve(monkeypatch, "platform_jwks", key)
    user = call(platform_token(key), db=db)
    assert user["id"] == "platform-user" and user["platform"] is True

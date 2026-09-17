import pytest
from sqlalchemy import func, select

from desktop_service import identity_link, platform_client
from desktop_service.api_keys import ApiKey
from desktop_service.automations import Automation
from desktop_service.config import settings
from desktop_service.db import Computer, Entitlement, Member, TrialIntent, Workspace, now
from desktop_service.identity_link import IdentityLink, ensure_linked, organization_for
from desktop_service.plans import Pass
from desktop_service.secrets_vault import Secret

SUB = "sub-9f2"
EMAIL = "you@localhost"  # the conftest member of workspace "w", stored as local-user
WALLET = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
PERSONAL = {"id": "org_personal", "name": "Personal", "slug": "personal-sub9f2", "role": "owner"}


def account(organizations=None, wallets=None, email=None):
    return {
        "user": {"id": SUB, "email": email, "emailVerified": bool(email)},
        "wallets": wallets or [],
        "organizations": [PERSONAL] if organizations is None else organizations,
    }


@pytest.fixture
def platform(monkeypatch, isolated_platform):
    """Configured but never reachable: every test decides what fetch_user returns."""
    monkeypatch.setattr(settings(), "platform_url", "http://platform.test")
    monkeypatch.setattr(settings(), "platform_service_token", "service-token")

    def fetched(sub):
        raise AssertionError("fetch_user was not expected here")

    monkeypatch.setattr(identity_link, "fetch_user", fetched)
    return monkeypatch


@pytest.fixture
def legacy(db):
    """One row per table that stores a user id, all owned by local-user in workspace w."""
    db.add(Computer(id="c1", workspace_id="w", request_id="r1", name="Desk"))
    db.add(
        ApiKey(
            id="k1", workspace_id="w", created_by="local-user", name="bot", prefix="cbk_a", key_hash="h1", scopes="read"
        )
    )
    db.add(
        Entitlement(
            id="e1",
            workspace_id="w",
            user_id="local-user",
            service="desktop",
            chain="base",
            wallet=WALLET,
            transaction_id="tx1",
            expires_at=now(),
        )
    )
    db.add(
        TrialIntent(
            id="i1",
            workspace_id="w",
            user_id="local-user",
            service="desktop",
            wallet=WALLET,
            chain="base",
            nonce="n1",
            message="sign this",
            expires_at=now(),
        )
    )
    db.add(
        Automation(
            id="a1",
            workspace_id="w",
            computer_id="c1",
            name="nightly",
            trigger={"kind": "schedule"},
            action={"kind": "prompt"},
            created_by="local-user",
        )
    )
    db.add(Secret(id="s1", workspace_id="w", name="TOKEN", encrypted_value="sealed", created_by="local-user"))
    db.add(Pass(id="p1", workspace_id="w", plan_id="day", expires_at=now(), created_by="local-user"))
    db.commit()
    return db


def owners(db):
    db.expire_all()
    return {
        "member": db.scalar(select(Member.user_id).where(Member.workspace_id == "w")),
        "api_key": db.get(ApiKey, "k1").created_by,
        "entitlement": db.get(Entitlement, "e1").user_id,
        "trial": db.get(TrialIntent, "i1").user_id,
        "automation": db.get(Automation, "a1").created_by,
        "secret": db.get(Secret, "s1").created_by,
        "pass": db.get(Pass, "p1").created_by,
    }


def link_row(db, sub=SUB):
    return db.scalar(select(IdentityLink).where(IdentityLink.platform_sub == sub))


def test_first_sign_in_adopts_every_row_the_legacy_email_owns(legacy, db):
    user = ensure_linked(db, {"id": SUB, "email": "You@Localhost", "verified": True})

    assert user["id"] == SUB and "organization_id" not in user  # no platform configured, so no mapping
    assert set(owners(db).values()) == {SUB}
    link = link_row(db)
    assert link.legacy_user_id == "local-user" and link.email == EMAIL
    assert db.get(Member, db.scalar(select(Member.id).where(Member.workspace_id == "other"))).user_id == "another-user"


def test_a_linked_account_is_a_single_lookup_and_never_asks_the_platform_again(legacy, db, platform):
    calls = []
    platform.setattr(identity_link, "fetch_user", lambda sub: calls.append(sub) or account())

    first = ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})
    assert first["organization_id"] == "org_personal" and calls == [SUB]

    second = ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})
    assert second["organization_id"] == "org_personal"
    assert calls == [SUB]  # the link row alone answers every later sign-in
    assert db.scalar(select(func.count()).select_from(IdentityLink)) == 1
    assert set(owners(db).values()) == {SUB}


def test_an_email_two_legacy_users_share_is_left_alone(legacy, db):
    db.add(Member(workspace_id="other", user_id="legacy-two", email="YOU@LOCALHOST", role="member"))
    db.commit()

    ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})

    assert set(owners(db).values()) == {"local-user"}
    assert link_row(db).legacy_user_id is None


def test_a_sign_in_with_no_legacy_match_still_records_a_link(legacy, db):
    ensure_linked(db, {"id": SUB, "email": "stranger@example.com", "verified": True})

    assert set(owners(db).values()) == {"local-user"}
    link = link_row(db)
    assert link is not None and link.legacy_user_id is None and link.email == "stranger@example.com"


def test_a_wallet_only_account_links_through_its_entitlement_wallet(legacy, db, platform):
    # Wallet sign-in: no email anywhere, and the platform reports the address in lower case.
    platform.setattr(identity_link, "fetch_user", lambda sub: account(wallets=[eip155(WALLET.lower())], email=None))

    user = ensure_linked(db, {"id": SUB, "email": None})

    assert set(owners(db).values()) == {SUB}
    link = link_row(db)
    assert link.legacy_user_id == "local-user" and link.email == ""
    assert user["organization_id"] == "org_personal"


def test_ethereum_wallets_match_whatever_their_case(legacy, db, platform):
    db.execute(Entitlement.__table__.delete())
    db.get(TrialIntent, "i1").wallet = WALLET.lower()
    db.commit()
    platform.setattr(identity_link, "fetch_user", lambda sub: account(wallets=[eip155(WALLET.upper())], email=None))

    ensure_linked(db, {"id": SUB, "email": None})

    assert link_row(db).legacy_user_id == "local-user"
    assert db.get(TrialIntent, "i1").user_id == SUB


def test_an_email_and_a_wallet_pointing_at_different_users_change_nothing(legacy, db, platform):
    other = "0x9999999999999999999999999999999999999999"
    db.add(
        Entitlement(
            id="e2",
            workspace_id="other",
            user_id="another-user",
            service="trial",
            chain="base",
            wallet=other,
            transaction_id="tx2",
            expires_at=now(),
        )
    )
    db.commit()
    platform.setattr(identity_link, "fetch_user", lambda sub: account(wallets=[eip155(other)], email=EMAIL))

    ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})

    assert set(owners(db).values()) == {"local-user"}
    assert db.get(Entitlement, "e2").user_id == "another-user"
    assert link_row(db).legacy_user_id is None


def test_organization_mapping_survives_the_platform_being_unreachable(legacy, db, platform):
    def down(sub):
        raise platform_client.PlatformError("Platform unreachable: ConnectError")

    platform.setattr(identity_link, "fetch_user", down)
    user = ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})

    assert "organization_id" not in user  # the sign-in still worked and the adoption still happened
    assert set(owners(db).values()) == {SUB}
    assert organization_for(db, "w") is None

    named = {"id": "org_team", "name": "Test", "slug": "test-team", "role": "owner"}
    platform.setattr(identity_link, "fetch_user", lambda sub: account(organizations=[PERSONAL, named]))
    user = ensure_linked(db, {"id": SUB, "email": EMAIL, "verified": True})

    assert user["organization_id"] == "org_personal"
    assert organization_for(db, "w") == "org_team"  # workspace "w" is named Test, which one organization matches
    assert db.get(Workspace, "other").platform_organization_id is None  # not a workspace this person owns
    assert link_row(db).organization_id == "org_personal"


def test_the_personal_organization_is_found_by_slug_not_by_position():
    unordered = [{"id": "org_team", "slug": "acme"}, PERSONAL]
    assert identity_link.personal_organization(SUB, unordered) == "org_personal"
    assert identity_link.personal_organization(SUB, [{"id": "org_x", "slug": "personal-sub-9f2"}]) == "org_x"
    assert identity_link.personal_organization(SUB, [{"id": "org_team", "slug": "acme"}]) is None


def eip155(address):
    return {"chainFamily": "eip155", "address": address, "chainId": 8453}

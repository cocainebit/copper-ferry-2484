from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from desktop_service.db import Entitlement, Workspace, now
from desktop_service.entitlements import balance, charge
from desktop_service.payment_models import PlatformEntry
from desktop_service.platform_credits import available, debit, grant, price


def test_grant_duplicate_and_mismatch(db):
    grant(db, "w", 10000, "deposit", "confirmed-payment")
    grant(db, "w", 10000, "deposit", "confirmed-payment")
    assert available(db, "w") == 10000
    for wid, amount, reason in [
        ("other", 10000, "confirmed-payment"),
        ("w", 10001, "confirmed-payment"),
        ("w", 10000, "other"),
    ]:
        with pytest.raises(HTTPException) as exc:
            grant(db, wid, amount, "deposit", reason)
        assert exc.value.status_code == 409
    assert available(db, "other") == 0
    assert available(db, "w") == 10000


def test_debit_idempotency_insufficient_and_parameter_mismatch(db):
    p = price("cubicle")
    grant(db, "w", 2 * p, "deposit", "confirmed")
    assert debit(db, "w", "cubicle", 1, "use")
    assert debit(db, "w", "cubicle", 1, "use")
    assert available(db, "w") == p
    with pytest.raises(HTTPException):
        debit(db, "w", "cubicle", 2, "use")
    with pytest.raises(HTTPException):
        debit(db, "other", "cubicle", 1, "use")
    assert not debit(db, "w", "cubicle", 2, "too-much")
    assert db.get(PlatformEntry, "too-much") is None
    assert available(db, "w") == p


def test_legacy_minutes_spent_before_crypto(db):
    w = db.get(Workspace, "w")
    w.included = 1
    p = price("cubicle")
    grant(db, "w", p, "deposit", "confirmed")
    assert balance(db, w) == 2
    assert charge(db, w, "pc", 1)
    assert available(db, "w") == p
    assert charge(db, w, "pc", 2)
    assert available(db, "w") == 0
    assert charge(db, w, "pc", 2)
    assert not charge(db, w, "pc", 3)
    assert db.scalar(select(func.count()).select_from(PlatformEntry)) == 2


def test_trial_then_crypto_without_subscription(db):
    w = db.get(Workspace, "w")
    w.subscription = "inactive"
    db.add(
        Entitlement(
            workspace_id="w",
            user_id="user",
            service="agent-desktop",
            chain="test",
            wallet="wallet",
            transaction_id="trial",
            expires_at=now() + timedelta(days=7),
            remaining=1,
        )
    )
    p = price("cubicle")
    grant(db, "w", p, "deposit", "confirmed")
    assert balance(db, w) == 2
    assert charge(db, w, "pc", 1)
    assert available(db, "w") == p
    assert charge(db, w, "pc", 2)
    assert balance(db, w) == 0


def test_unknown_service_and_invalid_units_rejected(db):
    for service, units in [("unknown", 1), ("cubicle", 0), ("cubicle", -1), ("cubicle", True), ("cubicle", 0.5)]:
        with pytest.raises(HTTPException):
            debit(db, "w", service, units, "use")


def test_rollback_reverts_grant(db):
    grant(db, "w", 10000, "deposit", "confirmed")
    db.rollback()
    assert available(db, "w") == 0


def test_shared_services_and_reprice_replay(db, monkeypatch):
    from desktop_service import platform_credits
    from desktop_service.config import settings

    configured = settings().model_copy(
        update={"platform_service_prices": {"render": 1000}, "cubicle_minute_micro_usdc": 3334}
    )
    monkeypatch.setattr(platform_credits, "settings", lambda: configured)
    grant(db, "w", 10000, "deposit", "confirmed")
    assert debit(db, "w", "render", 2, "render-use")
    assert debit(db, "w", "cubicle", 1, "desk-use")
    assert available(db, "w") == 4666
    configured.cubicle_minute_micro_usdc = 4000
    assert debit(db, "w", "cubicle", 1, "desk-use")
    assert available(db, "w") == 4666
    entry = db.get(PlatformEntry, "desk-use")
    assert entry.unit_price == 3334 and entry.amount == -3334


def test_expired_trial_does_not_hide_crypto_balance(db):
    w = db.get(Workspace, "w")
    w.subscription = "inactive"
    db.add(
        Entitlement(
            workspace_id="w",
            user_id="user",
            service="agent-desktop",
            chain="test",
            wallet="wallet",
            transaction_id="trial",
            expires_at=now() - timedelta(seconds=1),
            remaining=600,
        )
    )
    grant(db, "w", price("cubicle"), "deposit", "confirmed")
    assert balance(db, w) == 1
    assert charge(db, w, "pc", 1)
    assert balance(db, w) == 0

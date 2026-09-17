"""Transactional, provider-independent billing. Callers own commit/rollback."""

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Workspace
from .payment_models import PlatformBalance, PlatformEntry

MAX_AMOUNT = 10**15


def price(service):
    s = settings()
    prices = dict(getattr(s, "platform_service_prices", {}))
    prices["cubicle"] = getattr(s, "cubicle_minute_micro_usdc", 3334)
    value = prices.get(service)
    if type(value) is not int or not 0 < value <= MAX_AMOUNT:
        raise HTTPException(400, "Service has no valid server-configured price")
    return value


def available(db, wid):
    return db.scalar(select(PlatformBalance.balance).where(PlatformBalance.workspace_id == wid)) or 0


def paid_access(db, wid):
    return available(db, wid) >= price("cubicle")


def lock_workspace(db, wid):
    # A no-op write also serializes writers under SQLite, where FOR UPDATE is ignored.
    result = db.execute(update(Workspace).where(Workspace.id == wid).values(id=wid))
    if result.rowcount != 1:
        raise HTTPException(404, "Workspace not found")
    return db.scalar(select(Workspace).where(Workspace.id == wid).execution_options(populate_existing=True))


def _validate(amount, key):
    if type(amount) is not int or not 0 < amount <= MAX_AMOUNT:
        raise HTTPException(400, "Amount/units must be a positive bounded integer")
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise HTTPException(400, "A bounded idempotency key is required")


def _match(entry, wid, service, units, reason, amount=None):
    if (entry.workspace_id, entry.service, entry.units, entry.reason) != (wid, service, units, reason) or (
        amount is not None and entry.amount != amount
    ):
        raise HTTPException(409, "Idempotency key was already used for different billing parameters")
    return entry


def _change(db, wid, service, units, key, reason, amount, unit_price):
    lock_workspace(db, wid)
    try:
        with db.begin_nested():
            previous = db.get(PlatformEntry, key)
            if previous:
                return _match(previous, wid, service, units, reason, amount if amount > 0 else None)
            if not db.get(PlatformBalance, wid):
                db.add(PlatformBalance(workspace_id=wid, balance=0))
                db.flush()
            change = db.execute(
                update(PlatformBalance)
                .where(
                    PlatformBalance.workspace_id == wid,
                    PlatformBalance.balance >= max(0, -amount),
                    PlatformBalance.balance <= MAX_AMOUNT - max(0, amount),
                )
                .values(balance=PlatformBalance.balance + amount)
            )
            if change.rowcount != 1:
                if amount < 0:
                    return None
                raise HTTPException(409, "Maximum prepaid balance exceeded")
            entry = PlatformEntry(
                id=key,
                workspace_id=wid,
                service=service,
                amount=amount,
                units=units,
                unit_price=unit_price,
                reason=reason,
            )
            db.add(entry)
            db.flush()
            return entry
    except IntegrityError:
        # Concurrent reuse of a global key by another workspace rolls back the entire
        # balance mutation in this savepoint before examining the winning entry.
        previous = db.get(PlatformEntry, key)
        if previous:
            return _match(previous, wid, service, units, reason, amount if amount > 0 else None)
        raise


def grant(db, wid, amount, key, reason):
    _validate(amount, key)
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        raise HTTPException(400, "A bounded grant reason is required")
    return _change(db, wid, "platform", 1, key, reason, amount, amount)


def debit(db, wid, service, units, key):
    _validate(units, key)
    unit_price = price(service)
    amount = units * unit_price
    if amount > MAX_AMOUNT:
        raise HTTPException(400, "Charge exceeds maximum amount")
    return _change(db, wid, service, units, key, "service-usage", -amount, unit_price) is not None

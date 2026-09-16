"""Exercise real PostgreSQL concurrency in a disposable, uniquely named schema.

Run from services/api: .venv/bin/python ../../scripts/check_postgres.py
No existing tables, data, database settings or worker locks are modified. The
schema is removed in finally. Trial proofs are synthetic; no chain call occurs.
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service import feature_models  # noqa: F401 registers additive ORM tables
from desktop_service.config import settings
from desktop_service.db import Base, Computer, Entitlement, Event, Ledger, TrialIntent, Workspace, make_engine, now
from desktop_service.entitlements import PaymentProof, activate, charge


def main():
    s = settings()
    engine = make_engine(s.database_url)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("DATABASE_URL must point to PostgreSQL")
    schema = "codex_check_" + uuid4().hex
    # Generated identifier contains only our fixed prefix and hexadecimal digits.
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    factory = sessionmaker(scoped, expire_on_commit=False)
    print(f"Isolated schema: {schema}", flush=True)
    try:
        Base.metadata.create_all(scoped)
        with factory() as db:
            db.add_all(
                [
                    Workspace(id="metering", name="Metering", subscription="active", included=100),
                    Workspace(id="last-credit", name="Last credit", subscription="active", included=1),
                    Workspace(id="trial-a", name="Trial A"),
                    Workspace(id="trial-b", name="Trial B"),
                ]
            )
            db.flush()
            c = Computer(workspace_id="metering", request_id="sequence-check", name="Sequence test")
            db.add(c)
            db.flush()
            first = Event(computer_id=c.id, kind="info", text="First")
            second = Event(computer_id=c.id, kind="info", text="Second")
            db.add_all([first, second])
            db.commit()
            assert isinstance(first.id, int) and second.id > first.id
        print("PASS: ORM schema, foreign keys and event sequences", flush=True)

        barrier = Barrier(12)

        def same_bucket(_):
            with factory() as db:
                barrier.wait(timeout=20)
                w = db.scalar(select(Workspace).where(Workspace.id == "metering").with_for_update())
                result = charge(db, w, "same-computer", 12345)
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(same_bucket, range(12)))
        with factory() as db:
            assert all(results)
            assert db.get(Workspace, "metering").included == 99
            assert db.scalar(select(func.count()).select_from(Ledger).where(Ledger.workspace_id == "metering")) == 1
        print("PASS: 12 concurrent same-minute charges debit exactly one credit", flush=True)

        barrier = Barrier(2)

        def final_credit(index):
            with factory() as db:
                barrier.wait(timeout=20)
                w = db.scalar(select(Workspace).where(Workspace.id == "last-credit").with_for_update())
                result = charge(db, w, f"computer-{index}", 999)
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(final_credit, range(2)))
        with factory() as db:
            assert sorted(results) == [False, True]
            assert db.get(Workspace, "last-credit").included == 0
            assert db.scalar(select(func.count()).select_from(Ledger).where(Ledger.workspace_id == "last-credit")) == 1
        print("PASS: two competing computers cannot overspend the final credit", flush=True)

        trial_settings = s.model_copy(
            update={
                "trial_chain": "test-chain",
                "trial_token": "test-token",
                "trial_recipient": "test-treasury",
                "trial_decimals": 6,
                "trial_services": {"agent-desktop": 600},
            }
        )
        created = now() - timedelta(seconds=5)
        with factory() as db:
            for suffix in ("a", "b"):
                db.add(
                    TrialIntent(
                        id=f"intent-{suffix}",
                        workspace_id=f"trial-{suffix}",
                        user_id=f"user-{suffix}",
                        service="agent-desktop",
                        wallet="shared-wallet",
                        chain="test-chain",
                        nonce=f"nonce-{suffix}",
                        message="Synthetic proof for database constraints only",
                        created_at=created,
                        expires_at=created + timedelta(minutes=30),
                        verified_at=now(),
                    )
                )
            db.commit()
        proof = PaymentProof(
            chain="test-chain",
            transaction_id="same-finalized-payment",
            token="test-token",
            sender="shared-wallet",
            recipient="test-treasury",
            amount_atomic=10**6,
            balance_after_atomic=10000 * 10**6,
            successful=True,
            finalized=True,
            direct_transfer=True,
            block_time=int(now().replace(tzinfo=timezone.utc).timestamp()),
        )
        barrier = Barrier(2)

        def redeem(suffix):
            with factory() as db:
                # Both requests reach INSERT before either commits. This tests
                # the database uniqueness backstop, not just sequential lookup.
                def before_flush(session, context, instances):
                    if any(isinstance(row, Entitlement) for row in session.new):
                        barrier.wait(timeout=20)

                event.listen(db, "before_flush", before_flush)
                try:
                    result = activate(db, db.get(TrialIntent, f"intent-{suffix}"), proof)
                    return ("granted", result.id)
                except (IntegrityError, HTTPException):
                    db.rollback()
                    return ("rejected", None)

        with patch("desktop_service.entitlements.settings", return_value=trial_settings):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(redeem, ("a", "b")))
            with factory() as db:
                assert sorted(result[0] for result in results) == ["granted", "rejected"]
                assert db.scalar(select(func.count()).select_from(Entitlement)) == 1
                granted = db.scalar(select(Entitlement))
                assert granted.remaining == 600
                replay_intent = db.get(TrialIntent, "intent-" + granted.user_id[-1])
                assert activate(db, replay_intent, proof).id == granted.id
        print("PASS: simultaneous trial redemption grants once; same-owner retry is idempotent", flush=True)

        key = uuid4().int % (2**62)
        assert key != 8118026
        with engine.connect() as first, engine.connect() as second:
            try:
                assert first.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
                assert not second.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
                assert first.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key}).scalar()
                assert second.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
            finally:
                first.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                second.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        print("PASS: independent advisory lock exclusion and handover", flush=True)
        print("All real PostgreSQL checks passed. Chain and production RLS policy are outside this test.", flush=True)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
        print(f"Removed only {schema}", flush=True)


if __name__ == "__main__":
    main()

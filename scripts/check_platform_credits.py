"""Concurrent financial invariants in a disposable PostgreSQL schema; run from services/api."""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service.config import settings
from desktop_service.db import Base, Workspace, make_engine
from desktop_service.payment_models import PlatformEntry
from desktop_service.platform_credits import available, debit, grant, price
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker


def main():
    engine = make_engine(settings().database_url)
    assert engine.dialect.name == "postgresql", "PostgreSQL required"
    schema = "credits_check_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    factory = sessionmaker(scoped, expire_on_commit=False)
    try:
        Base.metadata.create_all(scoped)
        with factory() as db:
            db.add_all(
                [
                    Workspace(id=wid, name=wid)
                    for wid in ["w", "other", "race-a", "race-b"]
                ]
            )
            db.commit()
        barrier = Barrier(12)

        def deposit(_):
            with factory() as db:
                barrier.wait(timeout=20)
                grant(db, "w", price("cubicle"), "deposit", "confirmed")
                db.commit()

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(deposit, range(12)))
        with factory() as db:
            assert available(db, "w") == price("cubicle")
            assert db.scalar(select(func.count()).select_from(PlatformEntry)) == 1
        print("PASS: 12 concurrent payment retries grant once", flush=True)
        barrier = Barrier(12)

        def consume(index):
            with factory() as db:
                barrier.wait(timeout=20)
                result = debit(db, "w", "cubicle", 1, f"use-{index}")
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=12) as pool:
            assert sum(pool.map(consume, range(12))) == 1
        with factory() as db:
            assert available(db, "w") == 0
        print("PASS: concurrent consumers cannot overspend", flush=True)
        barrier = Barrier(2)

        def collide(wid):
            with factory() as db:
                barrier.wait(timeout=20)
                try:
                    grant(db, wid, 1000000, "global-payment", "confirmed")
                    db.commit()
                    return True
                except HTTPException as exc:
                    assert exc.status_code == 409
                    db.commit()  # Savepoint must have reverted losing balance mutation.
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(collide, ["race-a", "race-b"])) == 1
        with factory() as db:
            assert available(db, "race-a") + available(db, "race-b") == 1000000
        print(
            "PASS: cross-workspace payment replay credits exactly one account",
            flush=True,
        )
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
        print("Removed disposable credits schema", flush=True)


if __name__ == "__main__":
    main()

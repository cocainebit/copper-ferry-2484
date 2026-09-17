"""Initial schema creation. Run once on a new database before starting production."""

from sqlalchemy import text

from . import crypto_models, feature_models, payment_models  # noqa: F401
from .db import Base, engine

Base.metadata.create_all(engine)
if engine.dialect.name == "postgresql":
    with engine.begin() as conn:
        for name in Base.metadata.tables:
            conn.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
            # All access is through the backend's private DB role. No browser table access.
            for role in ("anon", "authenticated"):
                if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    conn.execute(text(f'REVOKE ALL ON TABLE "{name}" FROM "{role}"'))
print("Schema ready")

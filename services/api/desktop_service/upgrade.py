"""Additive upgrade for existing MVP databases. Run before API/worker startup."""

from sqlalchemy import inspect, text

from . import crypto_models, feature_models, payment_models  # noqa: F401
from .db import Base, engine


def upgrade():
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("computers")}
    if "system_snapshot_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE computers ADD COLUMN system_snapshot_id VARCHAR"))
    if "pty_secret" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE computers ADD COLUMN pty_secret TEXT"))

    for table in ("desktop_profiles", "desktop_templates"):
        names = {column["name"] for column in inspect(engine).get_columns(table)}
        if "resolution" not in names:
            with engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN resolution VARCHAR(20) NOT NULL DEFAULT '1440x900'")
                )

        if "idle_timeout_minutes" not in names:
            with engine.begin() as connection:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN idle_timeout_minutes INTEGER NOT NULL DEFAULT 15")
                )
        if "storage_gib" not in names:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN storage_gib INTEGER NOT NULL DEFAULT 20"))

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for name in Base.metadata.tables:
                connection.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
                for role in ("anon", "authenticated"):
                    if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                        connection.execute(text(f'REVOKE ALL ON TABLE "{name}" FROM "{role}"'))


if __name__ == "__main__":
    upgrade()
    print("Database upgraded")

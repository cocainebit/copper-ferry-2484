"""Additive upgrade for existing MVP databases. Run before API/worker startup."""

from sqlalchemy import inspect, text

# Import every module that defines tables so create_all sees them on a fresh database.
from . import (
    api_keys,  # noqa: F401
    apps,  # noqa: F401
    automations,  # noqa: F401
    crypto_models,  # noqa: F401
    feature_models,  # noqa: F401
    payment_models,  # noqa: F401
    plans,  # noqa: F401
    screens,  # noqa: F401
    secrets_vault,  # noqa: F401
    template_registry,  # noqa: F401
)
from .db import Base, engine


def upgrade():
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("computers")}
    if "system_snapshot_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE computers ADD COLUMN system_snapshot_id VARCHAR"))
    if "labels" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE computers ADD COLUMN labels JSON"))
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
        if table == "desktop_templates" and "definition_id" not in names:
            with engine.begin() as connection:
                for column, kind in (
                    ("definition_id", "VARCHAR"),
                    ("version", "INTEGER"),
                    ("digest", "VARCHAR(80)"),
                    ("spec", "JSON"),
                    ("build_log", "TEXT"),
                    ("requires_secrets", "JSON"),
                ):
                    connection.execute(text(f"ALTER TABLE desktop_templates ADD COLUMN {column} {kind}"))
        if table == "desktop_profiles" and "os" not in names:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE desktop_profiles ADD COLUMN os VARCHAR(16) NOT NULL DEFAULT 'linux'")
                )
                connection.execute(text("ALTER TABLE desktop_profiles ADD COLUMN gpu INTEGER NOT NULL DEFAULT 0"))
        if table == "desktop_profiles" and "secret_names" not in names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE desktop_profiles ADD COLUMN secret_names JSON"))
                connection.execute(text("ALTER TABLE desktop_profiles ADD COLUMN secrets_injected_at TIMESTAMP"))

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

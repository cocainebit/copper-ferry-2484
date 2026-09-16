"""Additive upgrade for existing MVP databases. Run before API/worker startup."""

from sqlalchemy import inspect, text

from . import feature_models  # noqa: F401
from .db import Base, engine


def upgrade():
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("computers")}
    if "system_snapshot_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE computers ADD COLUMN system_snapshot_id VARCHAR"))

    if engine.dialect.name == 'postgresql':
        with engine.begin() as connection:
            for name in Base.metadata.tables:
                connection.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))
                for role in ('anon','authenticated'):
                    if connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}).scalar():
                        connection.execute(text(f'REVOKE ALL ON TABLE "{name}" FROM "{role}"'))


if __name__ == "__main__":
    upgrade()
    print("Database upgraded")

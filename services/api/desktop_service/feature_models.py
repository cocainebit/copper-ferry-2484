"""Workspace-owned desktop customization and durable copy jobs."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now, uid


class DesktopProfile(Base):
    __tablename__ = "desktop_profiles"
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), primary_key=True)
    cpu: Mapped[int] = mapped_column(Integer, default=2)
    memory_gib: Mapped[int] = mapped_column(Integer, default=4)
    storage_gib: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    idle_timeout_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    resolution: Mapped[str] = mapped_column(String(20), default="1440x900", server_default="1440x900")
    os: Mapped[str] = mapped_column(String(16), default="linux", server_default="linux")
    gpu: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # None means every workspace secret; a list restricts injection to those names.
    secret_names: Mapped[list | None] = mapped_column(JSON)
    secrets_injected_at: Mapped[datetime | None] = mapped_column(DateTime)


class DesktopTemplate(Base):
    __tablename__ = "desktop_templates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String, default="creating")
    snapshot_id: Mapped[str | None] = mapped_column(String)
    cpu: Mapped[int] = mapped_column(Integer, default=2)
    memory_gib: Mapped[int] = mapped_column(Integer, default=4)
    storage_gib: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    idle_timeout_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    resolution: Mapped[str] = mapped_column(String(20), default="1440x900", server_default="1440x900")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # Set only for versions built from a declarative definition (template_registry).
    definition_id: Mapped[str | None] = mapped_column(String, index=True)
    version: Mapped[int | None] = mapped_column(Integer)
    digest: Mapped[str | None] = mapped_column(String(80))
    spec: Mapped[dict | None] = mapped_column(JSON)
    build_log: Mapped[str | None] = mapped_column(Text)
    requires_secrets: Mapped[list | None] = mapped_column(JSON)


class FeatureJob(Base):
    __tablename__ = "desktop_feature_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "request_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("computers.id"))
    target_id: Mapped[str | None] = mapped_column(ForeignKey("computers.id"))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("desktop_templates.id"))
    status: Mapped[str] = mapped_column(String, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

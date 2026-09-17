from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    subscription: Mapped[str] = mapped_column(String, default="inactive")
    customer_id: Mapped[str | None] = mapped_column(String, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String)
    included: Mapped[int] = mapped_column(Integer, default=0)
    topup: Mapped[int] = mapped_column(Integer, default=0)
    period_end: Mapped[datetime | None] = mapped_column(DateTime)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The Instance platform organization this workspace bills against; set by identity_link.
    platform_organization_id: Mapped[str | None] = mapped_column(String)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="member")


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    email: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Credential(Base):
    __tablename__ = "credentials"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    encrypted_key: Mapped[str] = mapped_column(Text)
    suffix: Mapped[str] = mapped_column(String)


class Computer(Base):
    __tablename__ = "computers"
    __table_args__ = (UniqueConstraint("workspace_id", "request_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    request_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String, default="stopped")
    sandbox_id: Mapped[str | None] = mapped_column(String)
    system_snapshot_id: Mapped[str | None] = mapped_column(String)
    vnc_secret: Mapped[str | None] = mapped_column(Text)
    pty_secret: Mapped[str | None] = mapped_column(Text)
    controller: Mapped[str] = mapped_column(String, default="agent")
    last_active: Mapped[datetime] = mapped_column(DateTime, default=now)
    metered_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("computer_id", "request_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"))
    request_id: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="queued")
    messages: Mapped[list] = mapped_column(JSON, default=list)
    pending_tools: Mapped[list] = mapped_column(JSON, default=list)
    approval: Mapped[dict | None] = mapped_column(JSON)
    lease: Mapped[str | None] = mapped_column(String)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    steps: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Ledger(Base):
    __tablename__ = "credit_ledger"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class TrialIntent(Base):
    __tablename__ = "trial_intents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[str] = mapped_column(String)
    service: Mapped[str] = mapped_column(String)
    wallet: Mapped[str] = mapped_column(String)
    chain: Mapped[str] = mapped_column(String)
    nonce: Mapped[str] = mapped_column(String, unique=True)
    message: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Entitlement(Base):
    __tablename__ = "entitlements"
    __table_args__ = (
        UniqueConstraint("user_id", "service"),
        UniqueConstraint("chain", "wallet", "service"),
        UniqueConstraint("workspace_id", "service"),
        UniqueConstraint("chain", "transaction_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[str] = mapped_column(String)
    service: Mapped[str] = mapped_column(String)
    chain: Mapped[str] = mapped_column(String)
    wallet: Mapped[str] = mapped_column(String)
    transaction_id: Mapped[str] = mapped_column(String)
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    remaining: Mapped[int] = mapped_column(Integer, default=600)


def make_engine(url):
    if url.startswith("sqlite"):
        Path(".local").mkdir(exist_ok=True)
    return create_engine(
        url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
    )


engine = make_engine(settings().database_url)
Session = sessionmaker(engine, expire_on_commit=False)


def database():
    with Session() as db:
        yield db


def event(db, computer_id, text, kind="info", run_id=None):
    db.add(Event(computer_id=computer_id, run_id=run_id, text=text, kind=kind))

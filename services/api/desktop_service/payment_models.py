"""Shared prepaid balance. All monetary amounts are integer USDC millionths."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now


class PlatformBalance(Base):
    __tablename__ = "platform_balances"
    __table_args__ = (CheckConstraint("balance >= 0", name="platform_balance_nonnegative"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)


class PlatformEntry(Base):
    __tablename__ = "platform_entries"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    service: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(BigInteger)
    units: Mapped[int] = mapped_column(BigInteger)
    unit_price: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

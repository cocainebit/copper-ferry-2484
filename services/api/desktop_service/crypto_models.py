"""Durable x402 invoice lifecycle; a signed authorization is never a credit receipt."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now, uid


class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_id"),
        UniqueConstraint("network", "asset", "nonce"),
        UniqueConstraint("network", "transaction"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(String)
    request_id: Mapped[str] = mapped_column(String)
    amount_micro_usdc: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String, default="open", index=True)
    network: Mapped[str] = mapped_column(String)
    asset: Mapped[str] = mapped_column(String)
    recipient: Mapped[str] = mapped_column(String)
    nonce: Mapped[str] = mapped_column(String)
    requirements: Mapped[dict] = mapped_column(JSON)
    resource_url: Mapped[str] = mapped_column(Text)
    signed_payload: Mapped[str | None] = mapped_column(Text)  # encrypted at rest
    payload_digest: Mapped[str | None] = mapped_column(String)
    payer: Mapped[str | None] = mapped_column(String)
    transaction: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    settlement_from_block: Mapped[int | None] = mapped_column(BigInteger)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)

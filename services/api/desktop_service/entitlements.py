"""Provider-neutral, reusable paid/trial access; quantities are integer atomic units."""

import secrets
from datetime import timedelta, timezone

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr, ValidationError
from sqlalchemy import or_, select

from . import platform_credits
from .config import settings
from .db import Entitlement, Ledger, TrialIntent, now

SERVICES = {"agent-desktop": {"name": "Cubicle", "minutes": 600}}


class PaymentProof(BaseModel):
    chain: StrictStr
    transaction_id: StrictStr
    token: StrictStr
    sender: StrictStr
    recipient: StrictStr
    amount_atomic: StrictInt
    balance_after_atomic: StrictInt
    successful: StrictBool
    finalized: StrictBool
    block_time: StrictInt
    direct_transfer: StrictBool


class ChainVerifier:
    """Trusted private adapter must independently query a chain RPC; never browser-supplied proof."""

    def __init__(self):
        s = settings()
        if (
            not all((s.trial_adapter_url, s.trial_adapter_key, s.trial_chain, s.trial_token, s.trial_recipient))
            or not 0 <= s.trial_decimals <= 30
        ):
            raise HTTPException(503, "Token trials are not configured yet. No payment is required or accepted here.")
        if not s.trial_adapter_url.startswith("https://") and not s.dev_mode:
            raise HTTPException(503, "Trial verifier requires HTTPS")
        self.s = s

    async def call(self, path, body):
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.post(
                    self.s.trial_adapter_url.rstrip("/") + path,
                    json=body,
                    headers={"Authorization": "Bearer " + self.s.trial_adapter_key},
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, "Chain verification unavailable; retry with the same transaction") from None

    async def wallet(self, wallet, message, signature):
        data = await self.call(
            "/verify-signature",
            {"chain": self.s.trial_chain, "wallet": wallet, "message": message, "signature": signature},
        )
        if data.get("valid") is not True or not isinstance(data.get("canonical_wallet"), str):
            raise HTTPException(400, "Wallet signature is invalid")
        return data["canonical_wallet"]

    async def payment(self, tx, wallet):
        data = await self.call(
            "/verify-payment",
            {
                "chain": self.s.trial_chain,
                "transaction_id": tx,
                "token": self.s.trial_token,
                "wallet": wallet,
                "recipient": self.s.trial_recipient,
            },
        )
        try:
            return PaymentProof.model_validate(data)
        except ValidationError:
            raise HTTPException(503, "Chain verifier returned an invalid proof; no access was granted") from None


def create_intent(db, workspace, user, service, wallet):
    s = settings()
    ChainVerifier()  # fail before asking users to sign or transfer anything
    if service not in s.trial_services:
        raise HTTPException(404, "Unknown service")
    previous = db.scalar(
        select(Entitlement).where(
            Entitlement.service == service,
            or_(Entitlement.user_id == user["id"], Entitlement.workspace_id == workspace),
        )
    )
    if previous:
        raise HTTPException(409, "This account or workspace has already used its trial")
    nonce = secrets.token_urlsafe(24)
    expires = now() + timedelta(minutes=30)
    message = (
        f"Cubicle trial enrollment\nOrigin: {s.public_url}\nChain: {s.trial_chain}\n"
        f"Wallet: {wallet}\nUser: {user['id']}\nWorkspace: {workspace}\nService: {service}\n"
        f"Nonce: {nonce}\nExpires: {expires.isoformat()}Z\n"
        "This signature verifies wallet ownership. It does not authorize a token transfer."
    )
    intent = TrialIntent(
        workspace_id=workspace,
        user_id=user["id"],
        service=service,
        wallet=wallet,
        chain=s.trial_chain,
        nonce=nonce,
        message=message,
        expires_at=expires,
    )
    db.add(intent)
    db.commit()
    return intent


def validate_payment(proof, intent):
    s = settings()
    unit = 10**s.trial_decimals
    checks = [
        proof.successful,
        proof.finalized,
        proof.direct_transfer,
        proof.chain == intent.chain,
        proof.token == s.trial_token,
        proof.sender == intent.wallet,
        proof.recipient == s.trial_recipient,
        proof.amount_atomic == unit,
        proof.balance_after_atomic >= 10000 * unit,
        intent.created_at.replace(tzinfo=timezone.utc).timestamp()
        <= proof.block_time
        <= intent.expires_at.replace(tzinfo=timezone.utc).timestamp(),
    ]
    if not all(checks):
        raise HTTPException(
            400,
            "Payment must be finalized, direct, exactly 1 platform token, within this enrollment window, with at least 10,000 tokens remaining",
        )


def activate(db, intent, proof):
    validate_payment(proof, intent)
    existing = db.scalar(
        select(Entitlement).where(Entitlement.chain == proof.chain, Entitlement.transaction_id == proof.transaction_id)
    )
    if existing:
        if (
            existing.user_id == intent.user_id
            and existing.service == intent.service
            and existing.workspace_id == intent.workspace_id
        ):
            return existing
        raise HTTPException(409, "Payment already redeemed")
    duplicate = db.scalar(
        select(Entitlement).where(
            Entitlement.service == intent.service,
            or_(
                Entitlement.user_id == intent.user_id,
                Entitlement.workspace_id == intent.workspace_id,
                (Entitlement.chain == intent.chain) & (Entitlement.wallet == intent.wallet),
            ),
        )
    )
    if duplicate:
        raise HTTPException(409, "Trial already used")
    entitlement = Entitlement(
        workspace_id=intent.workspace_id,
        user_id=intent.user_id,
        service=intent.service,
        chain=proof.chain,
        wallet=intent.wallet,
        transaction_id=proof.transaction_id,
        expires_at=now() + timedelta(days=7),
        remaining=settings().trial_services[intent.service],
    )
    db.add(entitlement)
    db.commit()
    return entitlement


def trial(db, wid):
    return db.scalar(
        select(Entitlement)
        .where(Entitlement.workspace_id == wid, Entitlement.service == "agent-desktop", Entitlement.expires_at > now())
        .with_for_update()
    )


def legacy_balance(db, w):
    if w.subscription in ("active", "trialing") and (not w.period_end or w.period_end > now()):
        return max(0, w.included + w.topup)
    t = trial(db, w.id)
    return max(0, t.remaining) if t else 0


def balance(db, w):
    return legacy_balance(db, w) + platform_credits.available(db, w.id) // platform_credits.price("cubicle")


def can_run(db, w):
    """A workspace may run computers on a live pass even with no credits left."""
    from . import plans

    return plans.active(db, w.id) is not None or balance(db, w) > 0


def charge(db, w, computer_id, bucket):
    from . import plans

    w = platform_credits.lock_workspace(db, w.id)
    key = f"usage:{computer_id}:{bucket}"
    previous = db.get(Ledger, key)
    if previous:
        if previous.workspace_id != w.id:
            raise HTTPException(409, "Usage key belongs to another workspace")
        return True
    if plans.covers_computer(db, w.id, computer_id):
        # Included in the pass: the minute is recorded for reporting, but nothing is spent.
        db.add(Ledger(id=key, workspace_id=w.id, amount=0, reason="included-in-pass"))
        return True
    if legacy_balance(db, w) > 0:
        if w.subscription in ("active", "trialing") and (not w.period_end or w.period_end > now()):
            if w.included > 0:
                w.included -= 1
            else:
                w.topup -= 1
        else:
            trial(db, w.id).remaining -= 1
    elif not platform_credits.debit(db, w.id, "cubicle", 1, key):
        return False
    db.add(Ledger(id=key, workspace_id=w.id, amount=-1, reason="computer-minute"))
    return True

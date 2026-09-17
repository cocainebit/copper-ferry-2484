"""Shared x402 prepaid billing. Credit only independently verified chain receipts."""

import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import func, select

from .config import settings
from .crypto_models import PaymentInvoice
from .db import Session, Workspace, database, now, uid
from .payment_models import PlatformEntry
from .platform_credits import available, debit, grant, lock_workspace, price
from .security import identity, member, seal, unseal

router = APIRouter()
log = logging.getLogger("cubicle-payments")


def rail():
    from . import x402_rail

    return x402_rail


def prices():
    services = {"cubicle", *settings().platform_service_prices}
    return [
        {"service": service, "unit": "minute" if service == "cubicle" else "unit", "price_micro_usdc": price(service)}
        for service in sorted(services)
    ]


def required(invoice):
    return {
        "x402Version": 2,
        "resource": {
            "url": invoice.resource_url,
            "description": "Platform prepaid credits",
            "mimeType": "application/json",
        },
        "accepts": [invoice.requirements],
    }


def public(invoice):
    status = invoice.status
    if status == "open" and invoice.expires_at <= now():
        status = "expired"
    return {
        "id": invoice.id,
        "workspace_id": invoice.workspace_id,
        "status": status,
        "amount_micro_usdc": invoice.amount_micro_usdc,
        "network": invoice.network,
        "asset": invoice.asset,
        "recipient": invoice.recipient,
        "test_network": invoice.network in ("eip155:84532", "eip155:31337"),
        "expires_at": invoice.expires_at.isoformat() + "Z",
        "created_at": invoice.created_at.isoformat() + "Z",
        "paid_at": invoice.paid_at.isoformat() + "Z" if invoice.paid_at else None,
        "transaction": invoice.transaction,
        "error": invoice.error,
        "payment_required": required(invoice) if status == "open" else None,
    }


def owned_invoice(db, iid, user, owner=False, lock=False):
    invoice = db.get(PaymentInvoice, iid)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    member(db, invoice.workspace_id, user, owner=owner, lock=lock)
    if lock:
        lock_workspace(db, invoice.workspace_id)
        db.refresh(invoice, with_for_update=True)
    return invoice


def enabled():
    status = rail().configuration_status()
    if not status["enabled"]:
        raise HTTPException(503, status.get("reason") or "Crypto payments are not configured")
    return status


@router.get("/v1/workspaces/{wid}/payments")
def overview(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    status = rail().configuration_status()
    entries = db.scalars(
        select(PlatformEntry)
        .where(PlatformEntry.workspace_id == wid)
        .order_by(PlatformEntry.created_at.desc())
        .limit(50)
    ).all()
    invoices = db.scalars(
        select(PaymentInvoice)
        .where(PaymentInvoice.workspace_id == wid)
        .order_by(PaymentInvoice.created_at.desc())
        .limit(50)
    ).all()
    return {
        **status,
        "balance_micro_usdc": available(db, wid),
        "prices": prices(),
        "invoices": [public(invoice) for invoice in invoices],
        "entries": [
            {
                "id": entry.id,
                "service": entry.service,
                "amount": entry.amount,
                "units": entry.units,
                "unit_price": entry.unit_price,
                "reason": entry.reason,
                "created_at": entry.created_at.isoformat() + "Z",
            }
            for entry in entries
        ],
    }


class InvoiceBody(BaseModel):
    amount_micro_usdc: StrictInt = Field(ge=1_000_000, le=1_000_000_000)


@router.post("/v1/workspaces/{wid}/payments/invoices", status_code=201)
async def create_invoice(
    wid: str,
    body: InvoiceBody,
    idempotency_key: str = Header(min_length=8, max_length=100),
    user=Depends(identity),
    db=Depends(database),
):
    member(db, wid, user, owner=True)
    enabled()
    db.commit()  # Never hold a synchronous DB lock across an async RPC call.
    try:
        creation_block = await rail().current_block()
    except Exception:
        raise HTTPException(503, "Payment network is unavailable; no invoice was created") from None
    lock_workspace(db, wid)
    old = db.scalar(
        select(PaymentInvoice).where(PaymentInvoice.workspace_id == wid, PaymentInvoice.request_id == idempotency_key)
    )
    if old:
        if old.amount_micro_usdc != body.amount_micro_usdc:
            raise HTTPException(409, "Idempotency key already used for a different amount")
        return public(old)
    enabled()
    recent = db.scalar(
        select(func.count())
        .select_from(PaymentInvoice)
        .where(PaymentInvoice.workspace_id == wid, PaymentInvoice.created_at > now() - timedelta(minutes=15))
    )
    pending = db.scalar(
        select(func.count())
        .select_from(PaymentInvoice)
        .where(PaymentInvoice.workspace_id == wid, PaymentInvoice.status == "settlement_pending")
    )
    if pending:
        raise HTTPException(409, "A payment is still being reconciled; wait before creating another invoice")
    if recent >= 10:
        raise HTTPException(429, "Too many invoices; reuse an existing invoice or try again later")
    quote = rail().payment_requirements(body.amount_micro_usdc)
    nonce = "0x" + secrets.token_hex(32)
    quote = {**quote, "extra": {**quote.get("extra", {}), "invoiceNonce": nonce}}
    iid = uid()
    invoice = PaymentInvoice(
        id=iid,
        workspace_id=wid,
        user_id=user["id"],
        request_id=idempotency_key,
        amount_micro_usdc=body.amount_micro_usdc,
        network=quote["network"],
        asset=quote["asset"],
        recipient=quote["payTo"],
        nonce=nonce,
        requirements=quote,
        resource_url=settings().public_url.rstrip("/") + f"/api/v1/payment-invoices/{iid}/pay",
        expires_at=now() + timedelta(seconds=settings().x402_max_timeout_seconds),
        settlement_from_block=creation_block,
    )
    db.add(invoice)
    db.commit()
    return public(invoice)


def decode_payment(encoded):
    if len(encoded) > 24_000:
        raise HTTPException(400, "Payment authorization is too large")
    try:
        value = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid PAYMENT-SIGNATURE encoding") from None


def attach_receipt(db, invoice, proof):
    # Every caller locks workspace first; grant follows the same lock order.
    lock_workspace(db, invoice.workspace_id)
    db.refresh(invoice, with_for_update=True)
    if invoice.status == "paid":
        return
    if invoice.status != "settlement_pending" or not proof:
        raise ValueError("Invoice is not awaiting settlement")
    expected = (
        invoice.network,
        invoice.asset.lower(),
        invoice.recipient.lower(),
        str(invoice.amount_micro_usdc),
        invoice.nonce.lower(),
        invoice.payer,
    )
    actual = (
        proof.get("network"),
        str(proof.get("asset", "")).lower(),
        str(proof.get("recipient", "")).lower(),
        str(proof.get("amount")),
        str(proof.get("nonce", "")).lower(),
        str(proof.get("payer", "")).lower(),
    )
    if expected != actual or not re.fullmatch(r"0x[0-9a-fA-F]{64}", proof.get("transaction", "")):
        raise ValueError("Receipt does not match the saved invoice")
    grant(db, invoice.workspace_id, invoice.amount_micro_usdc, "crypto:" + invoice.id, "x402 payment")
    invoice.status = "paid"
    invoice.transaction = proof["transaction"].lower()
    invoice.paid_at = now()
    invoice.error = None
    invoice.signed_payload = None
    db.commit()


async def reconcile_invoice(iid):
    with Session() as db:
        invoice = db.get(PaymentInvoice, iid)
        if not invoice or invoice.status != "settlement_pending" or not invoice.signed_payload:
            return
        lock_workspace(db, invoice.workspace_id)
        db.refresh(invoice, with_for_update=True)
        if invoice.status != "settlement_pending" or (
            invoice.checked_at and now() - invoice.checked_at < timedelta(seconds=5)
        ):
            return
        invoice.checked_at = now()
        encrypted_payload = invoice.signed_payload
        quote = invoice.requirements
        from_block = invoice.settlement_from_block
        db.commit()
    try:
        payload = json.loads(unseal(encrypted_payload))
        proof = await rail().reconcile(payload, quote, from_block=from_block)
    except Exception:
        # Network failure is not proof that a payment failed. Keep it recoverable.
        return
    if proof:
        with Session() as db:
            invoice = db.get(PaymentInvoice, iid)
            attach_receipt(db, invoice, proof)
    else:
        try:
            expired = await rail().expired_unsettled(payload, quote, from_block=from_block)
        except Exception:
            return
        if expired:
            with Session() as db:
                invoice = db.get(PaymentInvoice, iid)
                lock_workspace(db, invoice.workspace_id)
                db.refresh(invoice, with_for_update=True)
                if invoice.status == "settlement_pending":
                    invoice.status = "failed"
                    invoice.signed_payload = None
                    invoice.error = "Authorization expired without payment. You can create a new invoice."
                    db.commit()


async def reconcile_pending(limit=10):
    with Session() as db:
        ids = list(
            db.scalars(
                select(PaymentInvoice.id)
                .where(PaymentInvoice.status == "settlement_pending")
                .order_by(PaymentInvoice.checked_at.asc().nulls_first())
                .limit(limit)
            )
        )
    for iid in ids:
        try:
            await reconcile_invoice(iid)
        except Exception as exc:
            log.error("Invoice reconciliation interrupted: %s (%s)", iid, type(exc).__name__)


@router.get("/v1/payment-invoices/{iid}")
async def get_invoice(iid: str, user=Depends(identity), db=Depends(database)):
    invoice = owned_invoice(db, iid, user)
    pending = invoice.status == "settlement_pending"
    db.commit()
    if pending:
        await reconcile_invoice(iid)
        db.expire_all()
        invoice = db.get(PaymentInvoice, iid)
    return public(invoice)


@router.post("/v1/payment-invoices/{iid}/pay")
async def pay_invoice(iid: str, request: Request, user=Depends(identity), db=Depends(database)):
    invoice = owned_invoice(db, iid, user, owner=True, lock=True)
    if invoice.status == "paid":
        return public(invoice)
    if invoice.status == "settlement_pending":
        return JSONResponse(public(invoice), status_code=202)
    if invoice.status != "open" or invoice.expires_at <= now():
        raise HTTPException(409, "Invoice is closed or expired; create a new invoice")
    current = enabled()
    if (current["network"], current["asset"].lower(), current["recipient"].lower()) != (
        invoice.network,
        invoice.asset.lower(),
        invoice.recipient.lower(),
    ):
        raise HTTPException(409, "Payment configuration changed; create a new invoice")
    encoded = request.headers.get("payment-signature")
    if not encoded:
        challenge = required(invoice)
        return JSONResponse(
            challenge,
            status_code=402,
            headers={"PAYMENT-REQUIRED": base64.b64encode(json.dumps(challenge).encode()).decode()},
        )
    payload = decode_payment(encoded)
    try:
        validated = rail().validate_payload(payload, invoice.requirements)
        authorization = payload["payload"]["authorization"]
        if int(authorization["validBefore"]) > int(invoice.expires_at.replace(tzinfo=timezone.utc).timestamp()) + 30:
            raise ValueError("Authorization exceeds invoice expiry")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "Payment authorization does not match this invoice") from None
    start_block = invoice.settlement_from_block
    if start_block is None:
        raise HTTPException(409, "Invoice has no recovery checkpoint; create a new invoice")
    # Persist before ANY external settlement. Never clear an uncertain authorization for a new payment.
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    invoice.signed_payload = seal(canonical_payload)
    invoice.payload_digest = hashlib.sha256(canonical_payload.encode()).hexdigest()
    invoice.settlement_from_block = start_block
    invoice.payer = validated["payer"]
    invoice.status = "settlement_pending"
    invoice.submitted_at = now()
    invoice.error = None
    db.commit()
    try:
        verification = await rail().verify(payload, invoice.requirements)
        if not verification.get("isValid"):
            # Verification can reject an already-settled authorization. Check chain before calling it failed.
            proof = await rail().reconcile(payload, invoice.requirements, from_block=start_block)
            if proof:
                attach_receipt(db, invoice, proof)
                return public(invoice)
            invoice.error = "Payment verification was not accepted. Awaiting reconciliation; do not pay again."
            db.commit()
            return JSONResponse(public(invoice), status_code=202)
        result = await rail().settle(payload, invoice.requirements)
        proof = await rail().reconcile(
            payload, invoice.requirements, transaction=result.get("transaction"), from_block=start_block
        )
        if proof:
            attach_receipt(db, invoice, proof)
            response = JSONResponse(public(invoice))
            response.headers["PAYMENT-RESPONSE"] = base64.b64encode(
                json.dumps(
                    {
                        "success": True,
                        "transaction": proof["transaction"],
                        "network": invoice.network,
                        "payer": invoice.payer,
                    }
                ).encode()
            ).decode()
            return response
    except Exception:
        db.rollback()
        invoice = db.get(PaymentInvoice, iid)
        if invoice.status == "paid":
            return public(invoice)
    invoice.error = "Settlement is being checked. Do not pay again; your authorization is saved for recovery."
    db.commit()
    return JSONResponse(public(invoice), status_code=202)


class UsageBody(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=80)
    units: StrictInt = Field(ge=1, le=1_000_000)


@router.post("/internal/platform/usage")
def consume(
    body: UsageBody,
    authorization: str = Header(default=""),
    idempotency_key: str = Header(min_length=8, max_length=100),
    db=Depends(database),
):
    token = settings().platform_service_tokens.get(body.service, "")
    # Service-specific secrets cannot charge on behalf of another service.
    if not token or not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(401, "Service authentication required")
    if not db.get(Workspace, body.workspace_id):
        raise HTTPException(404, "Workspace not found")
    charged = debit(
        db,
        body.workspace_id,
        body.service,
        body.units,
        "service:"
        + hashlib.sha256(json.dumps([body.service, body.workspace_id, idempotency_key]).encode()).hexdigest(),
    )
    if not charged:
        raise HTTPException(402, "Insufficient platform credits")
    db.commit()
    return {"charged": True, "balance_micro_usdc": available(db, body.workspace_id)}

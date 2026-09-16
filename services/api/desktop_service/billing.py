from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Computer, Ledger, Webhook, Workspace, database, now
from .security import identity, member

router = APIRouter()


@router.post("/v1/workspaces/{wid}/billing/{kind}")
def checkout(
    wid: str,
    kind: str,
    idempotency_key: str | None = Header(default=None, min_length=8, max_length=100),
    user=Depends(identity),
    db=Depends(database),
):
    w = member(db, wid, user, owner=True, lock=True)
    s = settings()
    if not s.stripe_secret_key or not s.launch_enabled:
        raise HTTPException(503, "Checkout is not open yet")
    if not idempotency_key and kind != "portal":
        raise HTTPException(400, "Idempotency-Key is required for checkout")
    if kind not in ("portal", "subscription", "topup"):
        raise HTTPException(404, "Unknown checkout")
    stripe.api_key = s.stripe_secret_key
    if kind != "portal":
        price = s.stripe_subscription_price if kind == "subscription" else s.stripe_topup_price
        if not price:
            raise HTTPException(503, "Price is not configured")
        configured = stripe.Price.retrieve(price)
        recurring = configured.get("recurring")
        valid = (
            configured.get("active")
            and configured.get("currency") == "usd"
            and configured.get("unit_amount") == (2900 if kind == "subscription" else 1000)
        )
        valid = valid and (
            bool(recurring and recurring.get("interval") == "month" and recurring.get("interval_count") == 1)
            if kind == "subscription"
            else not recurring
        )
        if not valid:
            raise HTTPException(503, "Configured price does not match the published plan")
    if kind == "portal" and not w.customer_id:
        raise HTTPException(409, "No billing account exists yet")
    if not w.customer_id:
        customer = stripe.Customer.create(
            email=user["email"], metadata={"workspace_id": wid}, idempotency_key="customer:" + wid
        )
        w.customer_id = customer.id
        db.commit()
    if kind == "portal":
        return {
            "url": stripe.billing_portal.Session.create(
                customer=w.customer_id, return_url=s.public_url + "/app?view=billing"
            ).url
        }
    if kind not in ("subscription", "topup"):
        raise HTTPException(404, "Unknown checkout")
    if kind == "subscription" and w.subscription in ("active", "trialing"):
        raise HTTPException(409, "Manage your existing subscription in the billing portal")
    if kind == "topup" and w.subscription != "active":
        raise HTTPException(402, "An active subscription is required")
    if (
        kind == "subscription"
        and db.scalar(select(func.count()).select_from(Computer).where(Computer.status.in_(["running", "starting"])))
        >= s.max_desktops
    ):
        raise HTTPException(409, "Launch capacity is full. Please try again later.")
    price = s.stripe_subscription_price if kind == "subscription" else s.stripe_topup_price
    if not price:
        raise HTTPException(503, "Price is not configured")
    args = {
        "customer": w.customer_id,
        "mode": "subscription" if kind == "subscription" else "payment",
        "line_items": [{"price": price, "quantity": 1}],
        "metadata": {"workspace_id": wid, "kind": kind},
        "success_url": s.public_url + "/app?view=billing&checkout=success",
        "cancel_url": s.public_url + "/app?view=billing",
    }
    if kind == "subscription":
        args["subscription_data"] = {"metadata": {"workspace_id": wid}}
    return {
        "url": stripe.checkout.Session.create(**args, idempotency_key=f"checkout:{wid}:{kind}:{idempotency_key}").url
    }


def subscription_plan_matches(current):
    price = settings().stripe_subscription_price
    if not price:
        raise HTTPException(503, "Subscription price is not configured")
    items = current.get("items", {}) if hasattr(current, "get") else getattr(current, "items", {})
    rows = items.get("data", [])
    return len(rows) == 1 and rows[0].get("quantity") == 1 and rows[0].get("price", {}).get("id") == price


def apply_event(db, ev):
    if db.get(Webhook, ev["id"]):
        return
    obj = ev["data"]["object"]
    typ = ev["type"]
    customer = obj.get("customer")
    if not customer or not isinstance(customer, str):
        return
    w = db.scalar(select(Workspace).where(Workspace.customer_id == customer).with_for_update())
    if not w:
        return
    if typ == "invoice.paid":
        sub = obj.get("subscription") or obj.get("parent", {}).get("subscription_details", {}).get("subscription")
        # Never grant subscription credits for arbitrary invoices or prorations.
        if sub and obj.get("billing_reason") in ("subscription_create", "subscription_cycle"):
            period = max(
                (line.get("period", {}).get("end", 0) for line in obj.get("lines", {}).get("data", [])), default=0
            )
            end = datetime.fromtimestamp(period, timezone.utc).replace(tzinfo=None)
            current = stripe.Subscription.retrieve(sub)
            if current.customer != w.customer_id:
                raise ValueError("Subscription customer mismatch")
            if (
                current.status == "active"
                and subscription_plan_matches(current)
                and (
                    not w.stripe_subscription_id
                    or w.stripe_subscription_id == sub
                    or w.subscription in ("canceled", "unpaid", "incomplete_expired")
                )
                and not db.get(Ledger, "invoice:" + obj["id"])
                and (not w.period_end or end > w.period_end)
            ):
                w.subscription = "active"
                w.stripe_subscription_id = sub
                w.included = 6000
                w.period_end = end
                w.canceled_at = None
                db.add(Ledger(id="invoice:" + obj["id"], workspace_id=w.id, amount=6000, reason="subscription"))
    elif (
        typ in ("checkout.session.completed", "checkout.session.async_payment_succeeded")
        and obj.get("mode") == "payment"
        and obj.get("payment_status") == "paid"
    ):
        if (
            obj.get("metadata", {}).get("kind") == "topup"
            and obj.get("metadata", {}).get("workspace_id") == w.id
            and obj.get("currency") == "usd"
            and obj.get("amount_total") == 1000
        ):
            lines = stripe.checkout.Session.list_line_items(obj["id"], limit=2)
            items = lines.get("data", [])
            if (
                len(items) != 1
                or items[0].get("quantity") != 1
                or items[0].get("price", {}).get("id") != settings().stripe_topup_price
            ):
                raise ValueError("Top-up price mismatch")
            key = "topup:" + obj["id"]
            if not db.get(Ledger, key):
                w.topup += 3000
                db.add(Ledger(id=key, workspace_id=w.id, amount=3000, reason="topup"))
    elif typ in ("customer.subscription.updated", "customer.subscription.deleted"):
        # Retrieve current truth so out-of-order subscription events cannot restore stale access.
        current = stripe.Subscription.retrieve(obj["id"])
        if current.customer != w.customer_id:
            raise ValueError("Subscription customer mismatch")
        if current.status == "active" and not subscription_plan_matches(current):
            raise ValueError("Subscription price mismatch")
        if (
            not w.stripe_subscription_id
            or w.stripe_subscription_id == obj["id"]
            or (w.subscription in ("canceled", "unpaid", "incomplete_expired") and current.status == "active")
        ):
            w.stripe_subscription_id = obj["id"]
            w.subscription = current.status
            if current.status in ("canceled", "unpaid"):
                w.canceled_at = now()
    db.add(Webhook(id=ev["id"]))


@router.post("/v1/billing/webhook")
async def webhook(request: Request, db=Depends(database)):
    s = settings()
    if not s.stripe_webhook_secret or not s.stripe_secret_key:
        raise HTTPException(503, "Billing is not configured")
    stripe.api_key = s.stripe_secret_key
    try:
        ev = stripe.Webhook.construct_event(
            await request.body(), request.headers.get("stripe-signature", ""), s.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature") from None
    try:
        apply_event(db, ev)
        db.commit()
    except IntegrityError:
        db.rollback()
        if not db.get(Webhook, ev["id"]):
            raise HTTPException(503, "Billing event could not be applied; retry required") from None
    return {"received": True}

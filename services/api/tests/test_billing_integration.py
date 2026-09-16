from types import SimpleNamespace

import pytest

from desktop_service.billing import apply_event
from desktop_service.config import settings
from desktop_service.db import Webhook, Workspace


def event(kind, obj, eid="evt_test"):
    return {"id": eid, "type": kind, "data": {"object": obj}}


def test_missing_customer_never_matches_unassigned_workspace(db):
    apply_event(db, event("customer.subscription.deleted", {"id": "sub"}))
    assert db.get(Workspace, "w").subscription == "active"
    assert not db.get(Webhook, "evt_test")


def test_topup_checks_price_and_deduplicates_different_events(db, monkeypatch):
    w = db.get(Workspace, "w")
    w.customer_id = "cus"
    db.commit()
    monkeypatch.setattr(settings(), "stripe_topup_price", "price_topup")
    monkeypatch.setattr(
        "stripe.checkout.Session.list_line_items",
        lambda *a, **k: {"data": [{"price": {"id": "price_topup"}, "quantity": 1}]},
    )
    obj = {
        "id": "cs",
        "customer": "cus",
        "mode": "payment",
        "payment_status": "paid",
        "currency": "usd",
        "amount_total": 1000,
        "metadata": {"workspace_id": "w", "kind": "topup"},
    }
    apply_event(db, event("checkout.session.async_payment_succeeded", obj))
    db.commit()
    apply_event(db, event("checkout.session.completed", obj, "evt_again"))
    db.commit()
    assert w.topup == 3000


def test_subscription_update_checks_customer(db, monkeypatch):
    db.get(Workspace, "w").customer_id = "cus"
    db.commit()
    monkeypatch.setattr("stripe.Subscription.retrieve", lambda _: SimpleNamespace(customer="wrong", status="active"))
    with pytest.raises(ValueError, match="customer mismatch"):
        apply_event(db, event("customer.subscription.updated", {"customer": "cus", "id": "sub"}))


def test_price_mismatch_fails_before_customer_creation(client, monkeypatch):
    monkeypatch.setattr(settings(), "stripe_secret_key", "sk_test_example")
    monkeypatch.setattr(settings(), "launch_enabled", True)
    monkeypatch.setattr(settings(), "stripe_subscription_price", "price_test")
    monkeypatch.setattr("stripe.Price.retrieve", lambda _: {"active": True, "currency": "usd", "unit_amount": 9999})
    result = client.post("/v1/workspaces/w/billing/subscription", headers={"Idempotency-Key": "checkout-test"})
    assert result.status_code == 503
    assert "published plan" in result.json()["detail"]


def test_invalid_webhook_signature(client, monkeypatch):
    monkeypatch.setattr(settings(), "stripe_secret_key", "sk_test_example")
    monkeypatch.setattr(settings(), "stripe_webhook_secret", "whsec_test")
    result = client.post("/v1/billing/webhook", content="{}", headers={"stripe-signature": "invalid"})
    assert result.status_code == 400


def test_unrelated_subscription_cannot_grant_credits(db, monkeypatch):
    w = db.get(Workspace, "w")
    w.customer_id = "cus"
    w.included = 0
    db.commit()
    monkeypatch.setattr(settings(), "stripe_subscription_price", "our_price")
    monkeypatch.setattr(
        "stripe.Subscription.retrieve",
        lambda _: SimpleNamespace(
            customer="cus", status="active", items={"data": [{"quantity": 1, "price": {"id": "other_product"}}]}
        ),
    )
    obj = {
        "id": "inv",
        "customer": "cus",
        "subscription": "sub",
        "billing_reason": "subscription_cycle",
        "lines": {"data": [{"period": {"end": 2000000000}}]},
    }
    apply_event(db, event("invoice.paid", obj))
    db.commit()
    assert w.included == 0


def test_customer_can_resubscribe_after_cancellation(db, monkeypatch):
    w = db.get(Workspace, "w")
    w.customer_id = "cus"
    w.subscription = "canceled"
    w.stripe_subscription_id = "old_sub"
    w.included = 0
    db.commit()
    monkeypatch.setattr(settings(), "stripe_subscription_price", "our_price")
    monkeypatch.setattr(
        "stripe.Subscription.retrieve",
        lambda _: SimpleNamespace(
            customer="cus", status="active", items={"data": [{"quantity": 1, "price": {"id": "our_price"}}]}
        ),
    )
    obj = {
        "id": "inv_new",
        "customer": "cus",
        "subscription": "new_sub",
        "billing_reason": "subscription_create",
        "lines": {"data": [{"period": {"end": 2000000000}}]},
    }
    apply_event(db, event("invoice.paid", obj))
    db.commit()
    assert w.included == 6000
    assert w.stripe_subscription_id == "new_sub"
    assert w.subscription == "active"

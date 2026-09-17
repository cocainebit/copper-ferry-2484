from datetime import timedelta

import pytest

from desktop_service import operations
from desktop_service.config import settings
from desktop_service.db import ServiceHeartbeat, now


@pytest.mark.asyncio
async def test_ready_requires_worker(db, monkeypatch):
    async def healthy():
        return True

    monkeypatch.setattr(operations, "sandbox_healthy", healthy)
    db.get(ServiceHeartbeat, "desktop-worker").updated_at = now() - timedelta(minutes=1)
    db.commit()
    response = await operations.ready(db)
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_ready_requires_runtime(db, monkeypatch):
    async def unhealthy():
        return False

    monkeypatch.setattr(operations, "sandbox_healthy", unhealthy)
    assert (await operations.ready(db)).status_code == 503


def test_metrics_require_separate_operator_token(client, monkeypatch):
    monkeypatch.setattr(settings(), "ops_token", "operator-secret")
    assert client.get("/internal/metrics").status_code == 401
    response = client.get("/internal/metrics", headers={"Authorization": "Bearer operator-secret"})
    assert response.status_code == 200
    assert "desktop_worker_heartbeat_age_seconds" in response.text
    assert "operator-secret" not in response.text


def test_crypto_metrics_expose_only_aggregate_status(client, monkeypatch):
    monkeypatch.setattr(settings(), "ops_token", "operator-secret")
    response = client.get("/internal/metrics", headers={"Authorization": "Bearer operator-secret"})
    assert "platform_payment_worker_heartbeat_age_seconds -1" in response.text
    assert "platform_oldest_pending_payment_age_seconds 0" in response.text
    assert "platform_payments_enabled" in response.text
    assert "PAYMENT-SIGNATURE" not in response.text


@pytest.mark.asyncio
async def test_enabled_payments_require_reconciliation_worker(db, monkeypatch):
    async def healthy():
        return True

    monkeypatch.setattr(operations, "sandbox_healthy", healthy)
    monkeypatch.setattr(settings(), "x402_enabled", True)
    assert (await operations.ready(db)).status_code == 503
    db.add(ServiceHeartbeat(id="payment-worker"))
    db.commit()
    assert (await operations.ready(db)).status_code == 200

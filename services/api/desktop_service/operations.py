"""Health probes and private Prometheus metrics for operators."""

import secrets
import time
from collections import Counter
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text

from .config import settings
from .db import Computer, Run, ServiceHeartbeat, database, now

router = APIRouter()
started = time.monotonic()
requests = Counter()


async def sandbox_healthy():
    s = settings()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{s.opensandbox_protocol}://{s.opensandbox_domain}/health")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("/health/ready")
async def ready(db=Depends(database)):
    try:
        db.execute(text("SELECT 1"))
        heartbeat = db.get(ServiceHeartbeat, "desktop-worker")
        worker = bool(heartbeat and now() - heartbeat.updated_at < timedelta(seconds=30))
    except Exception:
        return JSONResponse({"ready": False, "database": False, "worker": False}, status_code=503)
    sandbox = await sandbox_healthy()
    return JSONResponse(
        {"ready": worker and sandbox, "database": True, "worker": worker, "desktop_runtime": sandbox},
        status_code=200 if worker and sandbox else 503,
    )


@router.get("/internal/metrics")
def metrics(authorization: str | None = Header(default=None), db=Depends(database)):
    key = settings().ops_token
    if not key:
        raise HTTPException(503, "Operator metrics are not configured")
    if not authorization or not secrets.compare_digest(authorization, "Bearer " + key):
        raise HTTPException(401, "Operator authentication required")
    heartbeat = db.get(ServiceHeartbeat, "desktop-worker")
    age = max(0, (now() - heartbeat.updated_at).total_seconds()) if heartbeat else -1
    lines = [
        "# TYPE desktop_worker_heartbeat_age_seconds gauge",
        f"desktop_worker_heartbeat_age_seconds {age}",
        "# TYPE desktop_api_uptime_seconds gauge",
        f"desktop_api_uptime_seconds {time.monotonic() - started:.2f}",
    ]
    for status, count in db.execute(select(Computer.status, func.count()).group_by(Computer.status)):
        if status not in {"starting", "running", "stopping", "stopped", "failed", "deleted", "copying", "customizing"}:
            status = "other"
        lines.append(f'desktop_computers{{status="{status}"}} {count}')
    for status, count in db.execute(select(Run.status, func.count()).group_by(Run.status)):
        if status not in {"queued", "running", "paused", "awaiting_approval", "completed", "interrupted", "canceled"}:
            status = "other"
        lines.append(f'desktop_runs{{status="{status}"}} {count}')
    for status, count in sorted(requests.items()):
        lines.append(f'desktop_http_responses_total{{status="{status}"}} {count}')
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

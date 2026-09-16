"""Owner-only readiness signals. Configuration is not a claim of live verification."""

from fastapi import APIRouter, Depends

from .config import settings
from .db import Credential, database
from .security import identity, member

router = APIRouter()


@router.get("/v1/workspaces/{wid}/setup")
def setup(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user, owner=True)
    s = settings()
    return {
        "development_mode": s.dev_mode,
        "agent": {
            "configured": db.get(Credential, wid) is not None,
            "model": s.anthropic_model,
            "action": "Add your Anthropic API key in Settings.",
        },
        "authentication": {
            "configured": bool(s.supabase_url),
            "action": "Configure Supabase and its Google, GitHub, and email providers.",
        },
        "billing": {
            "configured": bool(
                s.stripe_secret_key and s.stripe_webhook_secret and s.stripe_subscription_price and s.stripe_topup_price
            ),
            "checkout_enabled": s.launch_enabled,
            "action": "Configure Stripe prices and signed webhooks, then complete test checkout.",
        },
        "database": {"provider": "sqlite" if s.database_url.startswith("sqlite") else "postgresql"},
        "note": "Configured services still require an end-to-end integration test before public launch.",
    }

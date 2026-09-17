"""Restart-safe payment reconciliation; does not sign or rebroadcast payments."""

import asyncio
import logging

from .crypto_payments import reconcile_pending
from .db import ServiceHeartbeat, Session, now

log = logging.getLogger("cubicle-payments")


async def main():
    while True:
        try:
            await reconcile_pending()
            with Session() as db:
                heartbeat = db.get(ServiceHeartbeat, "payment-worker")
                if heartbeat:
                    heartbeat.updated_at = now()
                else:
                    db.add(ServiceHeartbeat(id="payment-worker"))
                db.commit()
        except Exception as exc:
            # Never print wallet authorization payloads or provider credentials.
            log.error("Reconciliation interrupted (%s)", type(exc).__name__)
        await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())

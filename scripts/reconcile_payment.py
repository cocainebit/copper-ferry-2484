"""Reconcile one saved invoice against a known transaction. Read-only by default.
Run from services/api. --apply commits only an independently verified receipt.
Never signs, sends, repeats or refunds a payment.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service.crypto_models import PaymentInvoice
from desktop_service.crypto_payments import attach_receipt
from desktop_service.db import Session
from desktop_service.security import unseal
from desktop_service.x402_rail import reconcile


async def main(args):
    with Session() as db:
        invoice = db.get(PaymentInvoice, args.invoice)
        if not invoice:
            raise SystemExit("Invoice not found")
        if invoice.status == "paid":
            print("Invoice already credited; no change")
            return
        if invoice.status != "settlement_pending" or not invoice.signed_payload:
            raise SystemExit("Only a pending invoice with its original authorization can be reconciled")
        payload = json.loads(unseal(invoice.signed_payload))
        requirements = invoice.requirements
        from_block = invoice.settlement_from_block
    proof = await reconcile(payload, requirements, transaction=args.transaction, from_block=from_block)
    if not proof:
        raise SystemExit("No confirmed matching receipt; balance unchanged")
    if args.apply:
        with Session() as db:
            attach_receipt(db, db.get(PaymentInvoice, args.invoice), proof)
        print("Verified payment credited exactly once")
    else:
        print("Matching receipt verified. Re-run with --apply to credit the saved invoice")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invoice", required=True)
    parser.add_argument("--transaction")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))

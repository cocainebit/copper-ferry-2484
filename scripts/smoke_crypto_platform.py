#!/usr/bin/env python3
"""Real local x402 invoice -> chain settlement -> shared service credits.
Run smoke_x402_rail.py first. Uses disposable SQLite and Anvil test funds only.
"""

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))
KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def main():
    fixture = json.loads((ROOT / ".local/x402-smoke.json").read_text())
    assert fixture["X402_NETWORK"] == "eip155:31337"
    assert fixture["X402_RPC_URL"] == "http://127.0.0.1:8547"
    assert fixture["X402_FACILITATOR_URL"] == "http://127.0.0.1:8403"
    w3 = Web3(Web3.HTTPProvider(fixture["X402_RPC_URL"]))
    assert w3.eth.chain_id == 31337
    payer = Account.from_key(KEY)
    artifact = json.loads(
        (ROOT / "infra/crypto-test/out/MockUSDC.sol/MockUSDC.json").read_text()
    )
    token = w3.eth.contract(address=fixture["X402_ASSET"], abi=artifact["abi"])
    token.functions.mint(payer.address, 20_000_000).transact({"from": payer.address})
    treasury_start = token.functions.balanceOf(fixture["X402_PAY_TO"]).call()
    service_secret = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(
        prefix="crypto-platform-", dir=ROOT / ".local"
    ) as directory:
        env = dict(os.environ, **fixture)
        env.update(
            DEV_MODE="true",
            DATABASE_URL="sqlite:///" + directory + "/billing.db",
            ENCRYPTION_KEY=Fernet.generate_key().decode(),
            X402_FACILITATOR_PRIVATE_KEY=KEY,
            PUBLIC_URL="http://localhost:3000",
            PLATFORM_SERVICE_PRICES=json.dumps({"research": 5000}),
            PLATFORM_SERVICE_TOKENS=json.dumps({"research": service_secret}),
        )
        os.environ.update(env)
        from desktop_service.config import settings

        settings.cache_clear()
        from desktop_service import x402_rail
        from desktop_service.db import Session, Workspace
        from desktop_service.entitlements import charge
        from desktop_service.main import app
        from desktop_service.platform_credits import available
        from fastapi.testclient import TestClient

        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/run_x402_facilitator.py")],
            cwd=ROOT / "services/api",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError("Local facilitator failed to start")
                try:
                    response = httpx.get(
                        fixture["X402_FACILITATOR_URL"] + "/supported",
                        headers={
                            "Authorization": "Bearer "
                            + fixture["X402_FACILITATOR_TOKEN"]
                        },
                    )
                    if response.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Local facilitator unavailable")
            with TestClient(
                app, headers={"Authorization": "Bearer local-development-only"}
            ) as client:
                workspace = client.post(
                    "/v1/workspaces", json={"name": "Crypto smoke"}
                ).json()
                wid = workspace["id"]
                endpoint = f"/v1/workspaces/{wid}/payments"
                assert client.get(endpoint).json()["balance_micro_usdc"] == 0

                def invoice(key):
                    response = client.post(
                        endpoint + "/invoices",
                        json={"amount_micro_usdc": 1_000_000},
                        headers={"Idempotency-Key": key},
                    )
                    assert response.status_code == 201, response.text
                    return response.json()

                def signature(inv):
                    req = inv["payment_required"]["accepts"][0]
                    auth = {
                        "from": payer.address,
                        "to": req["payTo"],
                        "value": req["amount"],
                        "validAfter": str(int(time.time()) - 30),
                        "validBefore": str(
                            int(
                                datetime.fromisoformat(
                                    inv["expires_at"].replace("Z", "+00:00")
                                ).timestamp()
                            )
                        ),
                        "nonce": req["extra"]["invoiceNonce"],
                    }
                    data = x402_rail.typed_data(req, auth)
                    signed = payer.sign_message(
                        encode_typed_data(
                            domain_data=data["domain"],
                            message_types=data["types"],
                            message_data=data["message"],
                        )
                    )
                    payload = {
                        "x402Version": 2,
                        "accepted": req,
                        "payload": {
                            "signature": "0x" + signed.signature.hex(),
                            "authorization": auth,
                        },
                    }
                    return {
                        "PAYMENT-SIGNATURE": base64.b64encode(
                            json.dumps(payload).encode()
                        ).decode()
                    }

                first = invoice("smoke-invoice-one")
                assert invoice("smoke-invoice-one")["id"] == first["id"]
                pay_url = f"/v1/payment-invoices/{first['id']}/pay"
                challenge = client.post(pay_url)
                assert challenge.status_code == 402 and challenge.headers.get(
                    "PAYMENT-REQUIRED"
                )
                signed = signature(first)
                response = client.post(pay_url, headers=signed)
                assert (
                    response.status_code == 200 and response.json()["status"] == "paid"
                ), response.text
                assert response.headers.get("PAYMENT-RESPONSE")
                assert client.post(pay_url, headers=signed).json()["status"] == "paid"
                assert client.get(endpoint).json()["balance_micro_usdc"] == 1_000_000
                assert (
                    token.functions.balanceOf(fixture["X402_PAY_TO"]).call()
                    == treasury_start + 1_000_000
                )

                # Simulate provider response loss AFTER the real on-chain transfer.
                second = invoice("smoke-invoice-two")
                original_settle = x402_rail.settle

                async def lost_response(payload, requirements):
                    result = await original_settle(payload, requirements)
                    assert result["success"]
                    raise httpx.ReadTimeout("Simulated response loss")

                x402_rail.settle = lost_response
                response = client.post(
                    f"/v1/payment-invoices/{second['id']}/pay",
                    headers=signature(second),
                )
                assert response.status_code == 202, response.text
                x402_rail.settle = original_settle
                assert (
                    client.get(f"/v1/payment-invoices/{second['id']}").json()["status"]
                    == "paid"
                )
                assert client.get(endpoint).json()["balance_micro_usdc"] == 2_000_000
                third = invoice("smoke-invoice-three")
                assert (
                    client.post(
                        f"/v1/payment-invoices/{third['id']}/pay", headers=signed
                    ).status_code
                    == 400
                )

                usage = {"workspace_id": wid, "service": "research", "units": 3}
                headers = {
                    "Authorization": "Bearer " + service_secret,
                    "Idempotency-Key": "research-smoke-one",
                }
                for _ in range(2):
                    response = client.post(
                        "/internal/platform/usage", json=usage, headers=headers
                    )
                    assert response.status_code == 200, response.text
                computer = client.post(
                    f"/v1/workspaces/{wid}/computers",
                    json={"name": "Prepaid desktop"},
                    headers={"Idempotency-Key": "prepaid-desktop-one"},
                )
                assert computer.status_code == 201, computer.text
                with Session() as db:
                    workspace = db.get(Workspace, wid)
                    assert (
                        workspace.included == 0 and workspace.subscription == "inactive"
                    )
                    assert charge(db, workspace, computer.json()["id"], "smoke-minute")
                    assert charge(db, workspace, computer.json()["id"], "smoke-minute")
                    db.commit()
                    assert (
                        available(db, wid)
                        == 2_000_000 - 15_000 - settings().cubicle_minute_micro_usdc
                    )
                assert (
                    token.functions.balanceOf(fixture["X402_PAY_TO"]).call()
                    == treasury_start + 2_000_000
                )
                print(
                    "PASS: real x402 invoice/402/signature/settlement/receipt, idempotent credit, lost-response recovery, cross-invoice rejection, two-service metering, prepaid desktop access"
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()

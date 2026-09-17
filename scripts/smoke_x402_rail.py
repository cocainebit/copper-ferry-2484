#!/usr/bin/env python3
"""Real local signature -> HTTP facilitator -> EVM transaction -> receipt recovery.
Only accepts localhost Anvil chain 31337, uses its public throwaway accounts.
Start compose.crypto.yaml and forge-build infra/crypto-test first. No real money.
"""

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))
# Well-known Anvil DEVELOPMENT key. No private/real wallet is read by this script.
KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
RPC = "http://127.0.0.1:8547"


async def main():
    w3 = Web3(Web3.HTTPProvider(RPC))
    assert w3.eth.chain_id == 31337, "Refusing non-local test chain"
    artifact = json.loads((ROOT / "infra/crypto-test/out/MockUSDC.sol/MockUSDC.json").read_text())
    payer = Account.from_key(KEY)
    treasury = w3.eth.accounts[1]
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    deployment = w3.eth.wait_for_transaction_receipt(factory.constructor().transact({"from": payer.address}))
    token = w3.eth.contract(address=deployment.contractAddress, abi=artifact["abi"])
    w3.eth.wait_for_transaction_receipt(
        token.functions.mint(payer.address, 10_000_000).transact({"from": payer.address})
    )
    env = dict(
        os.environ,
        DEV_MODE="true",
        X402_ENABLED="true",
        X402_NETWORK="eip155:31337",
        X402_ASSET=token.address,
        X402_PAY_TO=treasury,
        X402_RPC_URL=RPC,
        X402_FACILITATOR_URL="http://127.0.0.1:8403",
        X402_FACILITATOR_PORT="8403",
        X402_FACILITATOR_TOKEN=secrets.token_hex(32),
        X402_FACILITATOR_PRIVATE_KEY=KEY,
        X402_CONFIRMATIONS="1",
        X402_TOKEN_NAME="USDC",
        X402_TOKEN_VERSION="2",
    )
    os.environ.update(env)
    from desktop_service import x402_rail as rail
    from desktop_service.config import settings

    settings.cache_clear()
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/run_x402_facilitator.py")],
        env=env,
        cwd=ROOT / "services/api",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        async with httpx.AsyncClient() as http:
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    reply = await http.get(
                        env["X402_FACILITATOR_URL"] + "/supported",
                        headers={"Authorization": "Bearer " + env["X402_FACILITATOR_TOKEN"]},
                    )
                    if reply.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("Facilitator did not start")
        requirements = rail.payment_requirements(1_000_000)
        requirements["extra"]["invoiceNonce"] = "0x" + secrets.token_hex(32)
        auth = {
            "from": payer.address,
            "to": treasury,
            "value": "1000000",
            "validAfter": str(int(time.time()) - 30),
            "validBefore": str(int(time.time()) + 200),
            "nonce": requirements["extra"]["invoiceNonce"],
        }
        data = rail.typed_data(requirements, auth)
        signature = payer.sign_message(
            encode_typed_data(domain_data=data["domain"], message_types=data["types"], message_data=data["message"])
        )
        payload = dict(
            x402Version=2,
            accepted=requirements,
            payload=dict(signature="0x" + signature.signature.hex(), authorization=auth),
        )
        block = await rail.current_block()
        assert (await rail.verify(payload, requirements))["isValid"]
        result = await rail.settle(payload, requirements)
        assert result["success"], result
        proof = await rail.reconcile(payload, requirements, result["transaction"])
        assert proof and proof["amount"] == "1000000"
        recovered = await rail.reconcile(payload, requirements, from_block=block)
        assert recovered["transaction"] == proof["transaction"], "Lost-response recovery failed"
        assert token.functions.balanceOf(treasury).call() == 1_000_000
        try:
            await rail.verify(payload, requirements)
        except ValueError:
            pass
        else:
            raise AssertionError("Reused authorization was accepted")
        # Save public local fixture for the platform integration smoke; never the facilitator signer key.
        fixture = {k: v for k, v in env.items() if k.startswith("X402_") and k != "X402_FACILITATOR_PRIVATE_KEY"}
        path = ROOT / ".local/x402-smoke.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(fixture))
        path.chmod(0o600)
        print(
            "PASS: real EOA signature, official x402 HTTP verify/settle, EVM transfer, independent receipt, lost-response nonce recovery, replay rejection"
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    asyncio.run(main())

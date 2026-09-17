#!/usr/bin/env python3
"""Disposable full browser payment test; known Anvil accounts, no real money."""

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"


def main():
    fixture = json.loads((ROOT / ".local/x402-smoke.json").read_text())
    assert (
        fixture["X402_NETWORK"] == "eip155:31337"
        and fixture["X402_RPC_URL"] == "http://127.0.0.1:8547"
    )
    w3 = Web3(Web3.HTTPProvider(fixture["X402_RPC_URL"]))
    assert w3.eth.chain_id == 31337
    artifact = json.loads(
        (ROOT / "infra/crypto-test/out/MockUSDC.sol/MockUSDC.json").read_text()
    )
    token = w3.eth.contract(address=fixture["X402_ASSET"], abi=artifact["abi"])
    w3.eth.wait_for_transaction_receipt(
        token.functions.mint(w3.eth.accounts[0], 25_000_000).transact(
            {"from": w3.eth.accounts[0]}
        )
    )
    treasury_start = token.functions.balanceOf(fixture["X402_PAY_TO"]).call()
    processes = []
    with (
        tempfile.TemporaryDirectory(
            prefix="crypto-browser-", dir=ROOT / ".local"
        ) as directory,
        ExitStack() as handles,
    ):
        env = dict(os.environ, **fixture)
        env.update(
            DEV_MODE="true",
            DATABASE_URL="sqlite:///" + directory + "/browser.db",
            ENCRYPTION_KEY=Fernet.generate_key().decode(),
            SIGNING_KEY=secrets.token_hex(32),
            X402_FACILITATOR_PRIVATE_KEY=KEY,
            X402_FACILITATOR_PORT="8404",
            X402_FACILITATOR_URL="http://127.0.0.1:8404",
            PUBLIC_URL="http://127.0.0.1:3108",
            LAUNCH_ENABLED="false",
            NEXT_PUBLIC_DEV_MODE="true",
            NEXT_PUBLIC_SUPABASE_URL="",
            NEXT_PUBLIC_SUPABASE_ANON_KEY="",
            NEXT_DIST_DIR=".next-crypto",
            API_INTERNAL_URL="http://127.0.0.1:8108",
            CUBICLE_TEST_PYTHON=sys.executable,
        )

        def start(command, cwd, label):
            output = handles.enter_context(
                open(Path(directory) / (label + ".log"), "w+")
            )
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            processes.append((process, output, label))
            return process

        def wait(url, timeout=90, headers=None):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for process, output, label in processes:
                    if process.poll() is not None:
                        output.seek(0)
                        raise RuntimeError(label + " exited: " + output.read()[-3000:])
                try:
                    if httpx.get(url, headers=headers, timeout=3).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.3)
            raise RuntimeError("Timed out: " + url)

        try:
            start(
                [sys.executable, str(ROOT / "scripts/run_x402_facilitator.py")],
                ROOT / "services/api",
                "facilitator",
            )
            wait(
                env["X402_FACILITATOR_URL"] + "/supported",
                headers={"Authorization": "Bearer " + env["X402_FACILITATOR_TOKEN"]},
            )
            start(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "desktop_service.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8108",
                    "--no-access-log",
                ],
                ROOT / "services/api",
                "api",
            )
            wait("http://127.0.0.1:8108/health")
            headers = {"Authorization": "Bearer local-development-only"}
            workspaces = httpx.get(
                "http://127.0.0.1:8108/v1/workspaces", headers=headers
            )
            workspaces.raise_for_status()
            wid = workspaces.json()[0][
                "id"
            ]  # Isolated DEV bootstrap workspace also selected by the UI.
            start(
                [
                    "node",
                    str(ROOT / "node_modules/next/dist/bin/next"),
                    "dev",
                    "--port",
                    "3108",
                    "--hostname",
                    "127.0.0.1",
                ],
                ROOT / "apps/web",
                "frontend",
            )
            wait("http://127.0.0.1:3108", timeout=120)
            subprocess.run(
                ["node", str(ROOT / "scripts/smoke_crypto_browser.mjs")],
                cwd=ROOT,
                env=env,
                check=True,
                timeout=180,
            )
            balance = httpx.get(
                f"http://127.0.0.1:8108/v1/workspaces/{wid}/payments", headers=headers
            ).json()
            assert balance["balance_micro_usdc"] == 10_000_000
            assert (
                token.functions.balanceOf(fixture["X402_PAY_TO"]).call()
                == treasury_start + 10_000_000
            )
            assert (
                len(balance["invoices"]) == 1
                and balance["invoices"][0]["status"] == "paid"
            )
            print(
                "PASS: independent database and chain balances agree; no normal application data used"
            )
        finally:
            for process, output, label in reversed(processes):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                output.close()


if __name__ == "__main__":
    main()

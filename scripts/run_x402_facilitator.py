#!/usr/bin/env python3
"""Run private Cubicle facilitator; gas key stays here, never in the API or browser.

From services/api: .venv/bin/python ../../scripts/run_x402_facilitator.py
Environment: X402_FACILITATOR_PRIVATE_KEY, X402_FACILITATOR_TOKEN, X402_RPC_URL,
X402_NETWORK, X402_ASSET, X402_PAY_TO and X402_ENABLED=true.
"""

import asyncio
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from x402 import x402Facilitator
from x402.mechanisms.evm.exact.facilitator import ExactEvmScheme, ExactEvmSchemeConfig
from x402.mechanisms.evm.signers import FacilitatorWeb3Signer
from x402.schemas import PaymentPayload, PaymentRequirements

from desktop_service.config import Settings
from desktop_service.x402_rail import configuration_status, validate_payload


def create_app():
    s = Settings()
    readiness = configuration_status(s)
    if not readiness["enabled"]:
        raise RuntimeError(readiness["reason"])
    token = s.x402_facilitator_token
    if len(token) < 32:
        raise RuntimeError("Set a private facilitator bearer token of at least 32 characters")
    key_file = os.environ.get("X402_FACILITATOR_PRIVATE_KEY_FILE")
    private_key = Path(key_file).read_text().strip() if key_file else os.environ["X402_FACILITATOR_PRIVATE_KEY"]
    signer = FacilitatorWeb3Signer(private_key, s.x402_rpc_url)
    if signer.get_chain_id() != int(s.x402_network.split(":")[1]):
        raise RuntimeError("Facilitator RPC chain mismatch")
    facilitator = x402Facilitator().register(
        [s.x402_network], ExactEvmScheme(signer, ExactEvmSchemeConfig(simulate_in_settle=True))
    )
    app = FastAPI(title="Cubicle private x402 facilitator", docs_url=None, redoc_url=None)
    lock = asyncio.Lock()  # one signer nonce stream; run exactly one worker

    class Request(BaseModel):
        x402Version: int
        paymentPayload: dict
        paymentRequirements: dict

    def authenticate(authorization):
        if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "Facilitator authorization required")

    def check(body):
        r = body.paymentRequirements
        if (
            body.x402Version != 2
            or r.get("maxTimeoutSeconds") != s.x402_max_timeout_seconds
            or r.get("network") != s.x402_network
            or r.get("asset", "").lower() != s.x402_asset.lower()
            or r.get("payTo", "").lower() != s.x402_pay_to.lower()
            or r.get("extra", {}).get("name") != s.x402_token_name
            or r.get("extra", {}).get("version") != s.x402_token_version
        ):
            raise HTTPException(400, "Unsupported payment requirements")
        try:
            validate_payload(body.paymentPayload, r)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "Invalid payment authorization") from None
        return PaymentPayload.model_validate(body.paymentPayload), PaymentRequirements.model_validate(r)

    @app.get("/supported")
    async def supported(authorization: str | None = Header(None)):
        authenticate(authorization)
        return facilitator.get_supported().model_dump(by_alias=True, exclude_none=True)

    @app.post("/verify")
    async def verify(body: Request, authorization: str | None = Header(None)):
        authenticate(authorization)
        payload, requirements = check(body)
        result = await facilitator.verify(payload, requirements)
        return result.model_dump(by_alias=True, exclude_none=True)

    @app.post("/settle")
    async def settle(body: Request, authorization: str | None = Header(None)):
        authenticate(authorization)
        payload, requirements = check(body)
        async with lock:
            result = await facilitator.settle(payload, requirements)
        return result.model_dump(by_alias=True, exclude_none=True)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        create_app(),
        host=os.environ.get("X402_FACILITATOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("X402_FACILITATOR_PORT", "8402")),
        access_log=False,
    )

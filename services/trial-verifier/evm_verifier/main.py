"""Private, opt-in verifier for reviewed, non-rebasing, non-proxy ERC-20 tokens."""

import re
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import keccak
from eth_utils.exceptions import ValidationError as EthereumValidationError
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TRANSFER = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ]{0,39} trial enrollment")

def address(value):
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise HTTPException(422, "Invalid EVM address")
    return value.lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERIFIER_", env_file=".env", extra="ignore"
    )
    key: str = ""
    chain: str = ""
    chain_id: int = 0
    rpc_url: str = ""
    token: str = ""
    recipient: str = ""
    decimals: int = Field(default=18, ge=0, le=30)
    origin: str = ""
    token_code_hash: str = ""
    reviewed_standard_token: bool = False
    allow_local_rpc: bool = False

    def ready(self):
        if (
            len(self.key) < 32
            or not self.chain
            or self.chain_id <= 0
            or not self.origin.startswith("https://")
            or not self.reviewed_standard_token
            or not HASH.fullmatch(self.token_code_hash)
        ):
            raise HTTPException(503, "Verifier configuration is incomplete")
        address(self.token)
        address(self.recipient)
        if not self.rpc_url.startswith("https://"):
            from urllib.parse import urlsplit

            u = urlsplit(self.rpc_url)
            if not (
                self.allow_local_rpc
                and u.scheme == "http"
                and u.hostname in ("localhost", "127.0.0.1", "host.docker.internal")
            ):
                raise HTTPException(503, "A trusted HTTPS RPC is required")


@lru_cache
def settings():
    return Settings()


def authorized(authorization: Annotated[str | None, Header()] = None):
    s = settings()
    s.ready()
    if not secrets.compare_digest(authorization or "", "Bearer " + s.key):
        raise HTTPException(401, "Unauthorized")
    return s


class SignatureRequest(BaseModel):
    chain: str = Field(max_length=100)
    wallet: str = Field(max_length=42)
    message: str = Field(max_length=4096)
    signature: str = Field(max_length=132)


class PaymentRequest(BaseModel):
    chain: str = Field(max_length=100)
    transaction_id: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    token: str = Field(max_length=42)
    wallet: str = Field(max_length=42)
    recipient: str = Field(max_length=42)


class RPC:
    def __init__(self, url):
        self.url = url

    async def call(self, method, params):
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                response = await client.post(
                    self.url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": params,
                    },
                )
                response.raise_for_status()
                body = response.json()
                if body.get("error") or "result" not in body:
                    raise ValueError("Unsupported RPC response")
                return body["result"]
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                503, "Trusted chain RPC unavailable or unsupported"
            ) from None


async def bound_rpc(s):
    rpc = RPC(s.rpc_url)
    try:
        chain_id = int(await rpc.call("eth_chainId", []), 16)
    except (TypeError, ValueError):
        raise HTTPException(503, "Invalid RPC chain identity") from None
    if chain_id != s.chain_id:
        raise HTTPException(503, "RPC chain does not match configuration")
    return rpc


def verify_signature(req, s):
    wallet = address(req.wallet)
    if req.chain != s.chain:
        raise HTTPException(400, "Wrong chain")
    lines = req.message.splitlines()
    names = [
        "Origin",
        "Chain",
        "Wallet",
        "User",
        "Workspace",
        "Service",
        "Nonce",
        "Expires",
    ]
    # The first line is a display label each service brands ("Cubicle trial enrollment"); the bound
    # fields below, not the label, carry the semantics the signature commits to.
    if (
        len(lines) != 10
        or not HEADER.fullmatch(lines[0])
        or lines[-1]
        != "This signature verifies wallet ownership. It does not authorize a token transfer."
    ):
        raise HTTPException(400, "Invalid enrollment message")
    fields = {}
    for name, line in zip(names, lines[1:9], strict=True):
        if not line.startswith(name + ": ") or not line[len(name) + 2 :]:
            raise HTTPException(400, "Invalid enrollment fields")
        fields[name] = line[len(name) + 2 :]
    if (
        fields["Origin"] != s.origin
        or fields["Chain"] != s.chain
        or address(fields["Wallet"]) != wallet
    ):
        raise HTTPException(400, "Enrollment domain or wallet mismatch")
    try:
        expires = datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00"))
        if (
            expires.tzinfo is None
            or not 0 < (expires - datetime.now(timezone.utc)).total_seconds() <= 1805
        ):
            raise ValueError()
        recovered = Account.recover_message(
            encode_defunct(text=req.message), signature=req.signature
        )
    except (
        ValueError,
        TypeError,
        OverflowError,
        BadSignature,
        EthereumValidationError,
    ):
        return {"valid": False, "canonical_wallet": wallet}
    return {"valid": address(recovered) == wallet, "canonical_wallet": wallet}


def require(condition, detail):
    if not condition:
        raise HTTPException(400, detail)


async def verify_payment(req, s, rpc):
    wallet, token, recipient = (
        address(req.wallet),
        address(req.token),
        address(req.recipient),
    )
    require(
        req.chain == s.chain
        and token == address(s.token)
        and recipient == address(s.recipient),
        "Payment configuration mismatch",
    )
    require(wallet != recipient, "Sender cannot be treasury")
    txid = req.transaction_id.lower()
    tx = await rpc.call("eth_getTransactionByHash", [txid])
    receipt = await rpc.call("eth_getTransactionReceipt", [txid])
    require(
        tx is not None and receipt is not None and receipt.get("blockHash"),
        "Payment is not mined",
    )
    require(
        tx.get("hash", "").lower() == txid
        and receipt.get("transactionHash", "").lower() == txid,
        "Transaction mismatch",
    )
    block_hash = receipt["blockHash"]
    require(tx.get("blockHash") == block_hash, "Transaction block mismatch")
    block = await rpc.call("eth_getBlockByHash", [block_hash, False])
    finalized = await rpc.call("eth_getBlockByNumber", ["finalized", False])
    require(
        block is not None
        and finalized is not None
        and int(block["number"], 16) <= int(finalized["number"], 16),
        "Payment is not finalized",
    )
    canonical = await rpc.call("eth_getBlockByNumber", [block["number"], False])
    require(
        canonical is not None and canonical["hash"] == block_hash,
        "Payment block is not canonical",
    )
    index = int(receipt["transactionIndex"], 16)
    require(
        0 <= index < len(block["transactions"])
        and block["transactions"][index].lower() == txid,
        "Invalid transaction index",
    )
    unit = 10**s.decimals
    expected_input = "0xa9059cbb" + recipient[2:].rjust(64, "0") + format(unit, "064x")
    require(
        int(receipt["status"], 16) == 1
        and address(tx["from"]) == wallet
        and address(tx["to"]) == token
        and tx.get("input", "").lower() == expected_input
        and int(tx.get("value", "0x0"), 16) == 0,
        "Payment must be one direct successful ERC-20 transfer",
    )
    state = {"blockHash": block_hash, "requireCanonical": True}
    code = await rpc.call("eth_getCode", [token, state])
    require(
        "0x" + keccak(bytes.fromhex(code[2:])).hex() == s.token_code_hash.lower(),
        "Token bytecode differs from reviewed contract",
    )
    decimals = await rpc.call("eth_call", [{"to": token, "data": "0x313ce567"}, state])
    require(int(decimals, 16) == s.decimals, "Token decimals mismatch")
    logs = [
        log
        for log in receipt["logs"]
        if address(log["address"]) == token and log.get("topics", [None])[0] == TRANSFER
    ]
    expected_topics = [
        TRANSFER,
        "0x" + wallet[2:].rjust(64, "0"),
        "0x" + recipient[2:].rjust(64, "0"),
    ]
    require(
        len(logs) == 1
        and logs[0]["topics"] == expected_topics
        and int(logs[0]["data"], 16) == unit
        and not logs[0].get("removed", False),
        "Transfer event must match exact amount and parties",
    )
    # Block-end balance is transaction-post-state only if no later transaction affects this holder.
    # Restrict to reviewed standard tokens: no rebase, hidden balance changes, proxy upgrades or fees.
    block_logs = await rpc.call(
        "eth_getLogs",
        [{"blockHash": block_hash, "address": token, "topics": [TRANSFER]}],
    )
    wallet_topic = expected_topics[1]
    require(
        not any(
            int(log["transactionIndex"], 16) > index
            and wallet_topic in log.get("topics", [])[1:3]
            for log in block_logs
        ),
        "Historical balance is ambiguous: later same-block transfers affect this wallet; payment requires manual review",
    )
    balance_hex = await rpc.call(
        "eth_call",
        [{"to": token, "data": "0x70a08231" + wallet[2:].rjust(64, "0")}, state],
    )
    require(len(balance_hex) == 66, "Malformed balance response")
    balance = int(balance_hex, 16)
    require(balance >= 10000 * unit, "At least 10000 tokens must remain after payment")
    return {
        "chain": s.chain,
        "transaction_id": txid,
        "token": token,
        "sender": wallet,
        "recipient": recipient,
        "amount_atomic": unit,
        "balance_after_atomic": balance,
        "successful": True,
        "finalized": True,
        "direct_transfer": True,
        "block_time": int(block["timestamp"], 16),
    }


app = FastAPI(
    title="Private EVM trial verifier", docs_url=None, redoc_url=None, openapi_url=None
)


@app.get("/health")
def health():
    return {"status": "up"}


@app.post("/verify-signature")
async def signature(req: SignatureRequest, s: Settings = Depends(authorized)):
    await bound_rpc(s)
    return verify_signature(req, s)


@app.post("/verify-payment")
async def payment(req: PaymentRequest, s: Settings = Depends(authorized)):
    rpc = await bound_rpc(s)
    try:
        return await verify_payment(req, s, rpc)
    except (KeyError, TypeError, ValueError, IndexError):
        raise HTTPException(503, "Malformed chain response; no proof issued") from None

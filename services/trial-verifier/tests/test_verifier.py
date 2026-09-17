from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak
from evm_verifier.main import (
    TRANSFER,
    PaymentRequest,
    Settings,
    SignatureRequest,
    app,
    settings,
    verify_payment,
    verify_signature,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient

W = "0x" + "11" * 20
T = "0x" + "22" * 20
R = "0x" + "33" * 20
H = "0x" + "44" * 32
B = "0x" + "55" * 32
UNIT = 10**18


def config():
    return Settings(
        key="x" * 32,
        chain="optional-test-evm",
        chain_id=31337,
        rpc_url="https://rpc.invalid",
        token=T,
        recipient=R,
        origin="https://platform.example",
        token_code_hash="0x" + keccak(bytes.fromhex("6000")).hex(),
        reviewed_standard_token=True,
    )


def request():
    return PaymentRequest(
        chain="optional-test-evm", wallet=W, token=T, recipient=R, transaction_id=H
    )


class FakeRPC:
    def __init__(self):
        self.tx = {
            "hash": H,
            "blockHash": B,
            "from": W,
            "to": T,
            "input": "0xa9059cbb" + R[2:].rjust(64, "0") + format(UNIT, "064x"),
            "value": "0x0",
        }
        self.log = {
            "address": T,
            "topics": [
                TRANSFER,
                "0x" + W[2:].rjust(64, "0"),
                "0x" + R[2:].rjust(64, "0"),
            ],
            "data": hex(UNIT),
            "transactionIndex": "0x0",
        }
        self.receipt = {
            "transactionHash": H,
            "blockHash": B,
            "status": "0x1",
            "transactionIndex": "0x0",
            "logs": [self.log],
        }
        self.block = {
            "number": "0x10",
            "hash": B,
            "transactions": [H],
            "timestamp": "0x12345",
        }
        self.finalized = {"number": "0x10"}
        self.canonical = self.block
        self.logs = [self.log]
        self.balance = 10000 * UNIT
        self.calls = []
        self.code = "0x6000"

    async def call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_getTransactionByHash":
            return self.tx
        if method == "eth_getTransactionReceipt":
            return self.receipt
        if method == "eth_getBlockByHash":
            return self.block
        if method == "eth_getBlockByNumber":
            return self.finalized if params[0] == "finalized" else self.canonical
        if method == "eth_getCode":
            return self.code
        if method == "eth_getLogs":
            return self.logs
        if method == "eth_call":
            return "0x" + format(
                18 if params[0]["data"] == "0x313ce567" else self.balance, "064x"
            )
        raise AssertionError(method)


async def test_exact_finalized_payment_uses_hash_pinned_historical_state():
    rpc = FakeRPC()
    proof = await verify_payment(request(), config(), rpc)
    assert proof["balance_after_atomic"] == 10000 * UNIT
    assert proof["transaction_id"] == H
    for method, params in rpc.calls:
        if method in ("eth_call", "eth_getCode"):
            assert params[1] == {"blockHash": B, "requireCanonical": True}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.tx.update({"from": R}),
        lambda r: r.tx.update({"to": R}),
        lambda r: r.tx.update({"input": "0x23b872dd"}),
        lambda r: r.tx.update({"value": "0x1"}),
        lambda r: r.receipt.update({"status": "0x0"}),
        lambda r: r.finalized.update({"number": "0xf"}),
        lambda r: setattr(r, "canonical", {"hash": H}),
        lambda r: r.log.update({"data": hex(UNIT - 1)}),
        lambda r: r.receipt["logs"].append(deepcopy(r.log)),
        lambda r: setattr(r, "code", "0x6001"),
        lambda r: setattr(r, "balance", 10000 * UNIT - 1),
        lambda r: r.receipt.update({"transactionIndex": "0x1"}),
    ],
)
async def test_rejects_invalid_payment(mutation):
    rpc = FakeRPC()
    mutation(rpc)
    with pytest.raises(HTTPException):
        await verify_payment(request(), config(), rpc)


async def test_later_same_block_transfer_rejected():
    rpc = FakeRPC()
    later = deepcopy(rpc.log)
    later["transactionIndex"] = "0x1"
    rpc.logs.append(later)
    with pytest.raises(HTTPException) as exc:
        await verify_payment(request(), config(), rpc)
    assert "ambiguous" in exc.value.detail


async def test_later_unrelated_transfer_is_allowed_for_reviewed_standard_token():
    rpc = FakeRPC()
    rpc.logs.append(
        {
            "transactionIndex": "0x1",
            "topics": [TRANSFER, "0x" + "a" * 64, "0x" + "b" * 64],
        }
    )
    assert (await verify_payment(request(), config(), rpc))["successful"]


def signed_request(header="Cubicle trial enrollment"):
    account = Account.create()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=29)
    # Mirrors the exact message desktop_service.entitlements.create_intent signs.
    message = (
        f"{header}\nOrigin: https://platform.example\nChain: optional-test-evm\nWallet: {account.address}\n"
        f"User: u\nWorkspace: w\nService: agent-desktop\nNonce: random-nonce\nExpires: {expiry.isoformat()}\n"
        "This signature verifies wallet ownership. It does not authorize a token transfer."
    )
    sig = Account.sign_message(
        encode_defunct(text=message), account.key
    ).signature.hex()
    return SignatureRequest(
        chain="optional-test-evm",
        wallet=account.address,
        message=message,
        signature="0x" + sig.removeprefix("0x"),
    )


def test_signature_cryptographic_and_canonical():
    req = signed_request()
    assert verify_signature(req, config()) == {
        "valid": True,
        "canonical_wallet": req.wallet.lower(),
    }
    req.message = req.message.replace("User: u", "User: attacker")
    assert not verify_signature(req, config())["valid"]


def test_signature_rejects_foreign_origin():
    req = signed_request()
    req.message = req.message.replace(
        "https://platform.example", "https://attacker.example"
    )
    with pytest.raises(HTTPException):
        verify_signature(req, config())


def test_private_api_requires_bearer_and_configuration():
    settings.cache_clear()
    import evm_verifier.main as main

    old = main.settings
    main.settings = config
    try:
        response = TestClient(app).post("/verify-payment", json=request().model_dump())
        assert response.status_code == 401
    finally:
        main.settings = old
        app.dependency_overrides.clear()


def test_malformed_signature_returns_invalid():
    req = signed_request()
    req.signature = "0x" + "00" * 65
    assert not verify_signature(req, config())["valid"]


def test_unconfigured_service_fails_closed():
    with pytest.raises(HTTPException):
        Settings(_env_file=None).ready()


@pytest.mark.parametrize("header", ["Cubicle trial enrollment", "Floatlane trial enrollment", "Plotform trial enrollment"])
def test_signature_accepts_service_branded_headers(header):
    assert verify_signature(signed_request(header), config())["valid"]


@pytest.mark.parametrize(
    "header",
    ["trial enrollment", "Cubicle", "Cubicle trial enrollment extra", "Cubicle: trial enrollment", "x" * 41 + " trial enrollment"],
)
def test_signature_rejects_malformed_headers(header):
    with pytest.raises(HTTPException):
        verify_signature(signed_request(header), config())

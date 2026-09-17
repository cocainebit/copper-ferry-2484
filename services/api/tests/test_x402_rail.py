import copy
import time
from types import SimpleNamespace

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from desktop_service import x402_rail as rail


@pytest.fixture
def payment(monkeypatch):
    s = SimpleNamespace(
        dev_mode=True,
        x402_enabled=True,
        x402_network="eip155:84532",
        x402_asset="0x" + "11" * 20,
        x402_pay_to="0x" + "22" * 20,
        x402_token_name="USDC",
        x402_token_version="2",
        x402_max_timeout_seconds=300,
        x402_rpc_url="http://rpc",
        x402_facilitator_url="http://facilitator",
        x402_facilitator_token="",
        x402_confirmations=3,
    )
    monkeypatch.setattr(rail, "settings", lambda: s)
    account = Account.create()
    requirements = rail.payment_requirements(1000000)
    requirements["extra"]["invoiceNonce"] = "0x" + "ab" * 32
    auth = dict(
        from_=account.address,
        to=s.x402_pay_to,
        value="1000000",
        validAfter=str(int(time.time()) - 10),
        validBefore=str(int(time.time()) + 200),
        nonce="0x" + "ab" * 32,
    )
    auth["from"] = auth.pop("from_")
    data = rail.typed_data(requirements, auth)
    sig = account.sign_message(
        encode_typed_data(domain_data=data["domain"], message_types=data["types"], message_data=data["message"])
    )
    payload = dict(
        x402Version=2, accepted=requirements, payload=dict(authorization=auth, signature="0x" + sig.signature.hex())
    )
    return payload, requirements, s


def test_real_signature(payment):
    payload, r, s = payment
    assert rail.validate_payload(payload, r)["amount"] == "1000000"


@pytest.mark.parametrize(
    "mutation",
    [
        "amount",
        "recipient",
        "network",
        "asset",
        "nonce",
        "payer",
        "signature",
        "accepted",
        "missing_nonce",
        "permit2",
        "mixed_protocol",
        "expired",
    ],
)
def test_binding_rejects_tamper(payment, mutation):
    payload, r, s = payment
    payload = copy.deepcopy(payload)
    if mutation == "amount":
        payload["payload"]["authorization"]["value"] = "999999"
    if mutation == "recipient":
        payload["payload"]["authorization"]["to"] = "0x" + "33" * 20
    if mutation == "network":
        payload["accepted"]["network"] = "eip155:8453"
    if mutation == "asset":
        payload["accepted"]["asset"] = "0x" + "33" * 20
    if mutation == "nonce":
        payload["payload"]["authorization"]["nonce"] = "0x" + "ff" * 32
    if mutation == "payer":
        payload["payload"]["authorization"]["from"] = "0x" + "33" * 20
    if mutation == "signature":
        payload["payload"]["signature"] = "0x" + "00" * 65
    if mutation == "accepted":
        payload["accepted"]["extra"]["version"] = "1"
    if mutation == "missing_nonce":
        payload["accepted"]["extra"].pop("invoiceNonce")
    if mutation == "permit2":
        payload["payload"] = {"permit2Authorization": {}}
    if mutation == "mixed_protocol":
        payload["payload"]["permit2Authorization"] = {"nonce": "0"}
    if mutation == "expired":
        payload["payload"]["authorization"]["validBefore"] = "1"
    with pytest.raises((ValueError, TypeError)):
        rail.validate_payload(payload, r)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["none", "missing_nonce", "wrong_transfer", "unconfirmed", "reorg", "wrong_chain", "reverted"]
)
async def test_receipt_proof(payment, monkeypatch, bad):
    payload, r, s = payment
    auth = payload["payload"]["authorization"]
    payer = "0x" + auth["from"][2:].lower().rjust(64, "0")
    recipient = "0x" + r["payTo"][2:].rjust(64, "0")
    tx = "0x" + "dd" * 32
    receipt = dict(
        status="0x1",
        blockNumber="0x64",
        blockHash="0x" + "bb" * 32,
        logs=[
            dict(address=r["asset"], topics=[rail.USED, payer, auth["nonce"]], data="0x"),
            dict(address=r["asset"], topics=[rail.TRANSFER, payer, recipient], data=hex(1000000)),
        ],
    )
    if bad == "missing_nonce":
        receipt["logs"].pop(0)
    if bad == "wrong_transfer":
        receipt["logs"][1]["data"] = "0x1"
    if bad == "reverted":
        receipt["status"] = "0x0"

    async def rpc(method, params):
        return {
            "eth_call": "0x6",
            "eth_chainId": hex(8453 if bad == "wrong_chain" else 84532),
            "eth_blockNumber": "0x64" if bad == "unconfirmed" else "0x70",
            "eth_getTransactionReceipt": receipt,
            "eth_getBlockByNumber": {"hash": "0xwrong" if bad == "reorg" else receipt["blockHash"]},
            "eth_getLogs": [{"transactionHash": tx}],
        }[method]

    monkeypatch.setattr(rail, "_rpc", rpc)
    if bad in ("missing_nonce", "wrong_transfer", "wrong_chain"):
        with pytest.raises(ValueError):
            await rail.reconcile(payload, r, from_block=90)
    else:
        proof = await rail.reconcile(payload, r, from_block=90)
        assert bool(proof) == (bad == "none")
        if proof:
            assert proof["transaction"] == tx


def test_disabled_fail_closed(payment):
    _, _, s = payment
    s.x402_enabled = False
    with pytest.raises(ValueError):
        rail.payment_requirements(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("used,expired", [(False, True), (True, True), (False, False)])
async def test_expiry_requires_finalized_unused_authorization(payment, monkeypatch, used, expired):
    payload, r, s = payment

    async def rpc(method, params):
        if method == "eth_chainId":
            return hex(84532)
        if method == "eth_blockNumber":
            return "0x100"
        if method == "eth_getBlockByNumber":
            return dict(
                number="0xff", hash="0x" + "aa" * 32, timestamp=hex(int(time.time()) + (1000 if expired else 0))
            )
        if method == "eth_call":
            if params[0]["data"] == "0x313ce567":
                return "0x6"
            assert params[1] == {"blockHash": "0x" + "aa" * 32, "requireCanonical": True}
            return "0x" + ("1" if used else "0").rjust(64, "0")
        raise AssertionError(method)

    monkeypatch.setattr(rail, "_rpc", rpc)
    assert await rail.expired_unsettled(payload, r, from_block=100) == (expired and not used)


def test_production_rejects_custom_token(payment):
    _, _, s = payment
    s.dev_mode = False
    assert not rail.configuration_status()["enabled"]


@pytest.mark.parametrize(
    "field,value", [("x402_network", "eip155:1"), ("x402_max_timeout_seconds", 0), ("x402_max_timeout_seconds", 901)]
)
def test_configuration_rejects_unsupported_rail(payment, field, value):
    _, _, s = payment
    setattr(s, field, value)
    assert not rail.configuration_status()["enabled"]

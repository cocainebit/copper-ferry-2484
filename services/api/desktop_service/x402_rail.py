"""x402 v2 exact EIP-3009 rail. Settlement credit requires independent RPC proof."""

import re
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_keys.exceptions import BadSignature
from eth_utils import keccak
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.mechanisms.evm.types import AUTHORIZATION_TYPES
from x402.schemas import PaymentPayload, PaymentRequirements

from .config import settings

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
HEX32 = re.compile(r"0x[0-9a-fA-F]{64}\Z")
TRANSFER = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
USED = "0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex()


def configuration_status(s=None):
    s = s or settings()
    reason = ""
    if not s.x402_enabled:
        reason = "Crypto payments are disabled"
    elif not all((s.x402_rpc_url, s.x402_facilitator_url)):
        reason = "RPC and facilitator URLs are required"
    elif not all(ADDRESS.fullmatch(x) and int(x, 16) for x in (s.x402_asset, s.x402_pay_to)):
        reason = "Token contract and treasury addresses are required"
    elif s.x402_network not in ("eip155:8453", "eip155:84532", "eip155:31337"):
        reason = "Supported networks are Base, Base Sepolia and local Anvil"
    elif not 30 <= s.x402_max_timeout_seconds <= 900:
        reason = "Payment signing window must be between 30 and 900 seconds"
    elif not s.x402_token_name or not s.x402_token_version or s.x402_confirmations < 1:
        reason = "Token signing domain and confirmation count are required"
    canonical = {
        "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    }
    if (
        not reason
        and not getattr(s, "dev_mode", False)
        and s.x402_asset.lower() != canonical.get(s.x402_network, "unsupported").lower()
    ):
        reason = "Production supports canonical native USDC on Base or Base Sepolia only"
    if not reason and not getattr(s, "dev_mode", False):
        expected_name = "USD Coin" if s.x402_network == "eip155:8453" else "USDC"
        if s.x402_token_name != expected_name or s.x402_token_version != "2":
            reason = "Token signing domain does not match native USDC on this network"
    return dict(
        enabled=not reason,
        reason=reason,
        network=s.x402_network,
        asset=s.x402_asset,
        recipient=s.x402_pay_to,
        test_network=s.x402_network in ("eip155:84532", "eip155:31337"),
    )


def payment_requirements(amount: int):
    if not configuration_status()["enabled"]:
        raise ValueError(configuration_status()["reason"])
    if type(amount) is not int or not 0 < amount < 2**128:
        raise ValueError("Invalid atomic payment amount")
    s = settings()
    return dict(
        scheme="exact",
        network=s.x402_network,
        asset=s.x402_asset,
        amount=str(amount),
        payTo=s.x402_pay_to,
        maxTimeoutSeconds=s.x402_max_timeout_seconds,
        extra=dict(name=s.x402_token_name, version=s.x402_token_version),
    )


def payment_required(resource_url: str, amount: int):
    return dict(
        x402Version=2,
        resource=dict(url=resource_url, description="Cubicle platform credits", mimeType="application/json"),
        accepts=[payment_requirements(amount)],
    )


def typed_data(requirements, authorization):
    return dict(
        domain=dict(
            name=requirements["extra"]["name"],
            version=requirements["extra"]["version"],
            chainId=int(requirements["network"].split(":")[1]),
            verifyingContract=requirements["asset"],
        ),
        types={"TransferWithAuthorization": AUTHORIZATION_TYPES["TransferWithAuthorization"]},
        message={k: int(v) if k in ("value", "validAfter", "validBefore") else v for k, v in authorization.items()},
    )


def validate_payload(payload: dict, requirements: dict, *, check_time=True):
    """Validate immutable invoice binding and EOA signature before network calls.

    Root must persist the invoice nonce before returning its quote, and enforce
    one invoice per (network, token, payer, nonce) before settling.
    """
    if payload.get("x402Version") != 2 or payload.get("accepted") != requirements:
        raise ValueError("Payment does not match the invoice requirements")
    PaymentPayload.model_validate(payload)
    if set(payload["payload"]) != {"signature", "authorization"}:
        raise ValueError("Only EIP-3009 authorization payloads are supported")
    if requirements["scheme"] != "exact":
        raise ValueError("Only exact payments are supported")
    auth = payload["payload"].get("authorization", {})
    if set(auth) != {"from", "to", "value", "validAfter", "validBefore", "nonce"}:
        raise ValueError("EIP-3009 authorization required")
    for field in ("from", "to"):
        if not isinstance(auth[field], str) or not ADDRESS.fullmatch(auth[field]):
            raise ValueError("Invalid address")
    for field in ("value", "validAfter", "validBefore"):
        if (
            not isinstance(auth[field], str)
            or not re.fullmatch(r"0|[1-9][0-9]*", auth[field])
            or int(auth[field]) >= 2**256
        ):
            raise ValueError("Invalid authorization integer")
    nonce = requirements.get("extra", {}).get("invoiceNonce", "")
    if not HEX32.fullmatch(nonce) or auth["nonce"].lower() != nonce.lower():
        raise ValueError("Authorization nonce does not match invoice")
    if auth["to"].lower() != requirements["payTo"].lower() or auth["value"] != requirements["amount"]:
        raise ValueError("Wrong payment recipient or amount")
    now = int(time.time())
    if int(auth["validAfter"]) >= int(auth["validBefore"]):
        raise ValueError("Invalid authorization interval")
    if check_time and (
        int(auth["validAfter"]) >= now
        or not now + 5 < int(auth["validBefore"]) <= now + requirements["maxTimeoutSeconds"] + 30
    ):
        raise ValueError("Authorization expired or exceeds invoice window")
    signature = payload["payload"].get("signature", "")
    if not isinstance(signature, str) or not re.fullmatch(r"0x[0-9a-fA-F]{130}", signature):
        raise ValueError("An EOA wallet signature is required")
    data = typed_data(requirements, auth)
    signed = encode_typed_data(domain_data=data["domain"], message_types=data["types"], message_data=data["message"])
    try:
        recovered = Account.recover_message(signed, signature=signature)
    except BadSignature:
        raise ValueError("Invalid wallet signature") from None
    if recovered.lower() != auth["from"].lower():
        raise ValueError("Invalid wallet signature")
    return dict(payer=auth["from"].lower(), nonce=nonce.lower(), amount=auth["value"], network=requirements["network"])


async def _facilitator(operation, payload, requirements):
    s = settings()
    headers = {"Authorization": f"Bearer {s.x402_facilitator_token}"} if s.x402_facilitator_token else {}
    async with httpx.AsyncClient(headers=headers, timeout=60, follow_redirects=False) as http:
        client = HTTPFacilitatorClient(FacilitatorConfig(url=s.x402_facilitator_url, http_client=http))
        result = await getattr(client, operation)(
            PaymentPayload.model_validate(payload), PaymentRequirements.model_validate(requirements)
        )
        return result.model_dump(by_alias=True, exclude_none=True)


async def verify(payload, requirements):
    binding = validate_payload(payload, requirements)
    result = await _facilitator("verify", payload, requirements)
    if not result.get("isValid") or result.get("payer", "").lower() != binding["payer"]:
        raise ValueError("Facilitator rejected payment")
    return result


async def settle(payload, requirements):
    validate_payload(payload, requirements)
    # A timeout is an UNKNOWN outcome, never evidence of failed payment.
    result = await _facilitator("settle", payload, requirements)
    tx = result.get("transaction", "")
    if re.fullmatch(r"[0-9a-fA-F]{64}", tx):
        result["transaction"] = "0x" + tx
    return result


async def _rpc(method, params):
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
        response = await http.post(
            settings().x402_rpc_url, json=dict(jsonrpc="2.0", id=1, method=method, params=params)
        )
        response.raise_for_status()
        body = response.json()
    if body.get("error") or "result" not in body:
        raise ValueError("Payment RPC unavailable")
    return body["result"]


async def current_block():
    if int(await _rpc("eth_chainId", []), 16) != int(settings().x402_network.split(":")[1]):
        raise ValueError("RPC network mismatch")
    decimals = await _rpc("eth_call", [{"to": settings().x402_asset, "data": "0x313ce567"}, "latest"])
    if int(decimals, 16) != 6:
        raise ValueError("Configured payment token must have six decimals")
    return int(await _rpc("eth_blockNumber", []), 16)


async def reconcile(payload, requirements, transaction=None, *, from_block=None):
    """Recover by persisted pre-settlement block and invoice nonce; never rebroadcast.

    Returns None until a canonical receipt has enough confirmations. If no hash
    was returned (timeout/crash), scan bounded 2k-block chunks from the persisted
    start block. Caller must retry errors/pending without granting credit.
    """
    binding = validate_payload(payload, requirements, check_time=False)
    if (
        requirements["network"] != settings().x402_network
        or requirements["asset"].lower() != settings().x402_asset.lower()
    ):
        raise ValueError("Historical invoice needs its original configured chain/token")
    head = await current_block()
    payer_topic = "0x" + binding["payer"][2:].rjust(64, "0")
    if transaction is None:
        if from_block is None:
            return None
        if head - int(from_block) > 100_000:
            raise ValueError("Recovery requires archived/manual RPC reconciliation")
        matches = []
        for start in range(int(from_block), head + 1, 2000):
            matches.extend(
                await _rpc(
                    "eth_getLogs",
                    [
                        dict(
                            address=requirements["asset"],
                            fromBlock=hex(start),
                            toBlock=hex(min(start + 1999, head)),
                            topics=[USED, payer_topic, binding["nonce"]],
                        )
                    ],
                )
            )
        hashes = {log["transactionHash"] for log in matches if not log.get("removed")}
        if not hashes:
            return None
        if len(hashes) != 1:
            raise ValueError("Ambiguous authorization settlement")
        transaction = hashes.pop()
    if not isinstance(transaction, str) or not HEX32.fullmatch(transaction):
        raise ValueError("Invalid settlement transaction")
    receipt = await _rpc("eth_getTransactionReceipt", [transaction])
    if not receipt or int(receipt["status"], 16) != 1:
        return None
    block = int(receipt["blockNumber"], 16)
    if head - block + 1 < settings().x402_confirmations:
        return None
    canonical = await _rpc("eth_getBlockByNumber", [hex(block), False])
    if not canonical or canonical["hash"].lower() != receipt["blockHash"].lower():
        return None
    logs = [
        log
        for log in receipt["logs"]
        if log["address"].lower() == requirements["asset"].lower() and not log.get("removed")
    ]
    authorized = [
        log
        for log in logs
        if [t.lower() for t in log["topics"]] == [USED.lower(), payer_topic.lower(), binding["nonce"]]
    ]
    destination = "0x" + requirements["payTo"][2:].lower().rjust(64, "0")
    transfers = [
        log
        for log in logs
        if [t.lower() for t in log["topics"]] == [TRANSFER.lower(), payer_topic.lower(), destination]
        and int(log["data"], 16) == int(requirements["amount"])
    ]
    if len(authorized) != 1 or len(transfers) != 1:
        raise ValueError("Receipt does not prove the exact invoice payment")
    return dict(
        transaction=transaction.lower(),
        payer=binding["payer"],
        network=requirements["network"],
        amount=requirements["amount"],
        asset=requirements["asset"],
        recipient=requirements["payTo"],
        nonce=binding["nonce"],
        block=block,
        block_hash=receipt["blockHash"],
    )


async def expired_unsettled(payload, requirements, from_block=None):
    """Only terminally fail when a finalized block proves expired and unused.

    A used/cancelled nonce remains pending for receipt recovery or operator review.
    No finalized RPC support means callers must keep the invoice pending.
    """
    binding = validate_payload(payload, requirements, check_time=False)
    await current_block()
    if (
        requirements["network"] != settings().x402_network
        or requirements["asset"].lower() != settings().x402_asset.lower()
    ):
        raise ValueError("Historical invoice needs its original chain/token")
    block = await _rpc("eth_getBlockByNumber", ["finalized", False])
    if not block or int(block["timestamp"], 16) <= int(payload["payload"]["authorization"]["validBefore"]):
        return False
    if from_block is not None and int(block["number"], 16) < from_block:
        return False
    selector = keccak(text="authorizationState(address,bytes32)").hex()[:8]
    data = "0x" + selector + binding["payer"][2:].rjust(64, "0") + binding["nonce"][2:]
    result = await _rpc(
        "eth_call",
        [{"to": requirements["asset"], "data": data}, {"blockHash": block["hash"], "requireCanonical": True}],
    )
    if not isinstance(result, str) or not HEX32.fullmatch(result):
        raise ValueError("RPC returned invalid authorization state")
    return int(result, 16) == 0

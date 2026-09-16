# Optional EVM trial adapter

This adapter is an implementation option, **not a decision that the platform token uses Ethereum/EVM**. It is disabled by default. Non-EVM native coins, native EVM currency, smart-contract wallets (ERC-1271), proxy tokens, rebasing tokens, fee-on-transfer tokens, routed payments and transferFrom are unsupported.

## What it verifies

The private FastAPI service implements the existing [trial contract](TRIAL_INTEGRATION.md). It verifies EIP-191 personal-sign ownership of the exact enrollment message, domain, chain, wallet and expiration; returns lowercase EVM addresses; and queries a fixed operator-configured RPC whose chain ID must match configuration.

Payments must be successful direct calls to ERC-20 `transfer(address,uint256)`, with exactly one matching Transfer event for exactly one token. The receipt must be in a canonical finalized block. Runtime token bytecode must match a reviewed hash, and token decimals must match configuration. Historical calls use the block hash with `requireCanonical: true`. Neither client-supplied balances nor a later current balance is accepted.

### Historical balance restriction — review before activation

An RPC balance at a block means **end-of-block**, not immediately after an arbitrary transaction. For a reviewed, immutable, standard ERC-20 (all holder balance changes reflected by Transfer events), this adapter accepts end-of-block balance only when no subsequent same-block Transfer affects the sender. It rejects ambiguous payments instead of granting access using a potentially incorrect balance. Later same-block activity cannot be fixed simply by retrying; these payments need manual review and a transaction-state-capable adapter. A user could have already paid when rejection occurs. Do not activate this adapter for customers until the product provides a reviewed reconciliation/refund process or a full transaction-state implementation.

The bytecode hash does not itself prove ERC-20 behavior. Operators must review the actual contract and dependencies: no proxy/delegatecall upgradeability, rebases, hidden balance mutations, fees or other nonstandard semantics. Chain `finalized` must have the finality semantics required by the product; an L2 tag is not automatically equivalent to Ethereum L1 finality. RPCs lacking archive state or EIP-1898 fail closed.

## Local checks

```sh
uv sync --project services/trial-verifier --frozen
cd services/trial-verifier
.venv/bin/python -m pytest -q
```

Tests use signed real EOA messages and a deterministic fake JSON-RPC response fixture to cover invalid amounts/parties, finality, forks, token code, balance, and same-block ambiguity. They **do not constitute testnet/live-chain validation**.

## Configure after platform decisions

1. Copy `services/trial-verifier/.env.example` to `.env` in that directory.
2. Supply a random bearer key of at least 32 characters, network identifier, numeric chain ID, trusted HTTPS archive RPC, lowercase token and treasury addresses, decimals, exact enrollment origin, and reviewed bytecode hash. Set the review flag only after contract review.
3. Run `docker compose -f compose.trials.yaml up -d --build`. The HTTP port binds loopback only. Production must put the adapter behind a private HTTPS endpoint; do not expose it publicly.
4. In the main API set `TRIAL_ADAPTER_URL`, `TRIAL_ADAPTER_KEY`, `TRIAL_CHAIN`, `TRIAL_TOKEN`, `TRIAL_RECIPIENT`, and `TRIAL_DECIMALS` to matching values. **Token and recipient must be lowercase**, because the current backend compares configured proof fields exactly. `PUBLIC_URL` must exactly match `VERIFIER_ORIGIN`.
5. Test on the chosen network's testnet, including a finalized transaction, same-block ambiguity, payment replay and trial redemption concurrency, before enabling main-site payment instructions.

The `/health` endpoint proves process liveness only; it does not prove configuration, RPC availability or readiness to accept payments. The service never holds a private wallet key or signs/transmits a payment. Do not manually transfer funds as an installation test.

## Sources

- [EIP-20: transfer and Transfer event](https://eips.ethereum.org/EIPS/eip-20)
- [EIP-191: signed data format](https://eips.ethereum.org/EIPS/eip-191)
- [EIP-1898: canonical block-hash state queries](https://eips.ethereum.org/EIPS/eip-1898)
- [Ethereum JSON-RPC](https://ethereum.org/en/developers/docs/apis/json-rpc/)

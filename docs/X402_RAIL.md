# Cubicle x402 payment rail

Cubicle uses the official `x402[evm]==2.8.0` Python SDK for v2 `exact` EIP-3009 verification and settlement. The API independently verifies the resulting receipt before crediting the platform balance. Real payments are disabled until configured.

## Supported initial scope

- Injected EVM wallets using 65-byte EOA signatures. Smart contract wallets, Permit2, Solana, arbitrary tokens, and recurring wallet debits are not supported by this integration yet.
- Native USDC, six decimals. Production configuration accepts Base and Base Sepolia native contract addresses only. Local custom tokens require `DEV_MODE=true`.
- The default network is **Base Sepolia testnet** (`eip155:84532`). No recipient or facilitator is invented.
- An invoice quotes an exact atomic USDC amount and server-issued `extra.invoiceNonce`. Signers must use that nonce in `authorization.nonce`. This binds a public, reusable-looking authorization to one persisted invoice/workspace. Generic x402 clients which always generate a random nonce need the Cubicle client wrapper/custom signer. Do not advertise generic drop-in middleware compatibility.

## Configuration

| Variable | Purpose |
| --- | --- |
| `X402_ENABLED` | Explicit activation; default false |
| `X402_NETWORK` | `eip155:84532` testnet or `eip155:8453` mainnet |
| `X402_ASSET` | Exact native USDC contract from Circle's registry |
| `X402_PAY_TO` | Your treasury's public wallet address |
| `X402_RPC_URL` | Trusted RPC supporting receipts, logs and historical EIP-1898 `eth_call` |
| `X402_FACILITATOR_URL` | Private self-hosted facilitator or compatible trusted endpoint |
| `X402_FACILITATOR_TOKEN` | Bearer token shared between API and private facilitator |
| `X402_TOKEN_NAME` | `USDC` on Base Sepolia; `USD Coin` on Base mainnet |
| `X402_TOKEN_VERSION` | `2` |
| `X402_CONFIRMATIONS` | Receipt confirmation threshold; default 3; review before launch |
| `X402_MAX_TIMEOUT_SECONDS` | Short signing window; default 300 |

The facilitator additionally reads `X402_FACILITATOR_PRIVATE_KEY` from its own environment. This is a separate wallet holding ETH **for gas**, not the treasury or customer key. Keep it out of the API/browser environment. Give the process only a limited gas balance. The local facilitator binds `127.0.0.1:8402` by default and requires a bearer token of at least 32 characters. Run exactly one process/worker per signing key, so concurrent settlements serialize wallet transaction nonces.

From `services/api`, run:

```sh
.venv/bin/python ../../scripts/run_x402_facilitator.py
```

The API calls authenticated `/verify` and `/settle`. The private facilitator restricts network, token and recipient and invokes the SDK's exact EVM mechanism with settlement simulation. It is not a publicly exposed arbitrary gas sponsor. Production service supervision, secret injection, firewalling and gas-balance alerts must be configured on the chosen server.

## Crediting and recovery

1. Persist a quote, server-issued authorization nonce and invoice owner before signing.
2. Validate every signed field and recover the wallet's EIP-712 signature locally.
3. Persist the payload, settlement state and current chain block **before** invoking the facilitator.
4. The facilitator simulates and broadcasts the token's `transferWithAuthorization` call.
5. Independently query the configured RPC. Check the chain/token, six decimals, successful canonical receipt and confirmations, plus matching `AuthorizationUsed` and exact `Transfer` events.
6. Credit atomically once in the shared ledger. Facilitator/browser success is never enough.

If the API or facilitator times out after broadcast, the outcome is unknown. Reconciliation scans the fixed token's `AuthorizationUsed` event by payer and invoice nonce starting at the persisted pre-settlement block. It does not blindly send another payment. A canonical finalized block proving expiry **and** `authorizationState=false` allows the invoice to fail safely. An unavailable/faulty RPC, cancelled nonce, or ambiguous receipt keeps it pending for investigation.

The current log scan uses 2,000-block chunks with a 100,000-block recovery ceiling. Long outages beyond that need an archive-RPC/manual reconciliation procedure. Do not change token/network while old invoices are pending; they require their original network. Three confirmations are not finality, and a deep reorganization after credit remains an operational risk: production confirmation policy, audit and reorg response need review.

## Reproducible local chain verification

This uses disposable Anvil accounts and a **fake** USDC contract. Never send real assets to test accounts.

```sh
docker compose -f compose.crypto.yaml up -d
docker run --rm --entrypoint forge \
  -v "$PWD/infra/crypto-test:/work" -w /work \
  ghcr.io/foundry-rs/foundry:v1.3.1 build
cd services/api
.venv/bin/python ../../scripts/smoke_x402_rail.py
```

The smoke deploys and funds the test contract, signs a real EIP-712 authorization, starts the private HTTP facilitator, verifies and settles through the official SDK, checks the on-chain recipient balance and independent receipt, recovers a deliberately omitted transaction hash by nonce, and rejects reuse of the authorization. It stops its facilitator afterward. Stop the test network with `docker compose -f compose.crypto.yaml stop` from the repository root.

Unit tests separately cover tampered chain/token/amount/recipient/nonce/signature, missing receipt events, insufficient confirmations, reorganization, and finalized unused-expiry checks.

## Primary references

- [Official x402 source and Python SDK](https://github.com/x402-foundation/x402/tree/main/python/x402)
- [x402 exact EVM specification](https://github.com/x402-foundation/x402/tree/main/specs/schemes/exact)
- [Circle native USDC contract registry](https://developers.circle.com/stablecoins/usdc-contract-addresses)
- [EIP-3009 transfer authorization](https://eips.ethereum.org/EIPS/eip-3009)

### Private facilitator container

`compose.x402.yaml` builds a separate facilitator image and joins the production `agent-desktop-control` network. It publishes **no host port**. It does not inherit API/database/Supabase secrets. Only the facilitator mounts the gas-signing key file.

Set `X402_FACILITATOR_KEY_FILE` to an absolute host file path. The file must contain only the gas wallet's private key and be readable by container UID `65532` (for example, a root-managed secret directory with the file owned by UID 65532 and mode 0400 on Linux). Set the shared bearer token and payment variables above in your protected deployment environment. The API and payment worker should use `X402_FACILITATOR_URL=http://facilitator:8402`; they must not receive the private key or its file mount.

```sh
docker compose -f compose.x402.yaml build
docker compose -f compose.x402.yaml up -d
```

The production control network must already exist. Do not scale this service beyond one replica per gas key. Stop it separately with `docker compose -f compose.x402.yaml stop`. Deployment lifecycle, gas-balance alerts and log retention are operator responsibilities. Container schema and image builds can be tested without starting a real network payment service.

### Actual browser checkout verification

After the rail smoke has prepared the local chain fixture:

```sh
services/api/.venv/bin/python scripts/smoke_crypto_browser.py
```

This starts an isolated API on port 8108 with disposable SQLite, a frontend on 3108, and a private facilitator on 8404. Playwright injects a local development wallet and signs the **actual TypeScript-generated EIP-712 request** using Anvil's known test account. It checks the paid invoice, 10 test-USDC balance, one signature, no browser exceptions, the API ledger, and the on-chain treasury balance. A screenshot is saved to ignored `test-results/crypto-browser-paid.png`.

The script stops all three temporary services and removes their database afterward, leaving the normal app and its balances untouched. It leaves the Anvil test node running for further tests. This verifies browser-to-chain interoperability; a real wallet extension and public Base Sepolia/mainnet still require launch acceptance testing.

# Operating Cubicle crypto billing

The code supports x402 v2 exact EIP-3009 payments, a shared workspace credit ledger, Cubicle minute charging and authenticated charges from other platform services. Local tests use an isolated Anvil blockchain and a fake six-decimal token; this is not evidence of a mainnet payment. Native USDC on Base is the supported initial mainnet rail; the default configuration is disabled Base Sepolia testnet.

## Run the services

The API creates invoices and accepts signed payments. A separate facilitator spends its own ETH for gas to submit the authorized token transfer. The payment worker independently reconciles receipts after crashes or timeouts. It does not sign or rebroadcast payments. The desktop worker meters Cubicle usage independently of payment RPC latency.

Local application startup `sh scripts/dev.sh` now runs the API, desktop worker, payment worker and frontend. Start the project's database/runtime/auth services as described in the README first. Run one private facilitator separately using [X402_RAIL.md](X402_RAIL.md). Production `compose.production.yaml` includes the payment worker; `compose.x402.yaml` provides the opt-in private facilitator deployment. Keep the facilitator signer key out of the API, frontend and treasury configuration.

## Configure the payment rail

Use `.env.example` and [X402_RAIL.md](X402_RAIL.md). At minimum set network, canonical token, treasury public address, RPC URL, facilitator URL/bearer token and the correct token signing domain. Then explicitly enable x402. Start with testnet and a separate test database. Review confirmations, fees, service rates and refund terms before enabling real payments.

Use separate databases/environments for fake local tokens, public testnet funds and real USDC. Never migrate a test credit balance into production. Keep the original token/network/RPC available while invoices remain pending. Configuration changes cannot reinterpret a saved invoice: its requirements and authorization nonce are frozen.

Current Cubicle pricing defaults to **3,334 micro-USDC per minute**, or approximately 0.20 USDC/hour. This is a provisional engineering default, not a profitability calculation or approved public price. Set `CUBICLE_MINUTE_MICRO_USDC` before launch. Existing development/trial minutes are consumed before purchased credits. Trial enrollment remains service-specific under the existing `agent-desktop` identifier.

## Other platform services

Set `PLATFORM_SERVICE_PRICES` to a JSON map of service IDs to integer micro-USDC per unit. Set `PLATFORM_SERVICE_TOKENS` to a separate random backend secret for each service. The `cubicle` rate comes from its dedicated setting. Keep those secrets in service backends only.

A trusted service calls `POST /internal/platform/usage` with its bearer token, an `Idempotency-Key`, and `{workspace_id, service, units}`. The unit price comes from server configuration. The ledger rejects invalid units, mismatched replay parameters and insufficient funds, and handles concurrent charges without negative balances. Keys are scoped to workspace and service. Authenticate and authorize each customer request in that service before asking billing to charge it. This private billing endpoint is not a substitute for service-level authorization.

The production reverse proxy blocks `/internal/*` and `/api/internal/*`; other service backends need a private route to the API. `packages/platform-billing` provides the customer-facing invoice/balance and wallet-signing client. Connecting another website requires its repository, origin and shared identity configuration; it is not done automatically.

## Invoice lifecycle and recovery

- **open:** a quote exists; no submitted authorization. Expiry is calculated in responses.
- **settlement_pending:** encrypted authorization and recovery block are saved before external verification/settlement. This is an unknown outcome, never proof that funds were not sent. New invoices are blocked for that workspace until resolved.
- **paid:** the chain receipt and invoice fields match, and the ledger grant is committed atomically once. Repeated callbacks or requests do not credit again.
- **failed:** a canonical finalized block proves the authorization expired unused. Creating another invoice is safe.

The recovery checkpoint is captured when the invoice is created, so even a transfer broadcast before the pay endpoint receives its payload can be found. Workers rotate pending invoices; one corrupted payload or RPC failure cannot prevent every other invoice from being processed. Restoring the original application encryption key is required to read saved authorizations.

If the process crashes before broadcast, the invoice remains pending until the unused authorization expires. It is deliberately not resubmitted automatically. If the response is lost after broadcast, the worker finds the on-chain authorization event and verifies the receipt. RPC failure or inadequate confirmations keeps the invoice pending. A canceled authorization also needs investigation. Long outages beyond the bounded log scan require an archive RPC or a known transaction hash.

For a known transaction, verify without modifying the balance:

```sh
cd services/api
.venv/bin/python ../../scripts/reconcile_payment.py --invoice INVOICE_ID --transaction 0xTRANSACTION
```

After review, append `--apply` to commit the verified credit. This command never signs or sends a transfer. There is no automated refund withdrawal feature; treasury refunds and credit adjustments need a defined, reviewed operational procedure before public launch.

## Monitoring and backups

The private metrics endpoint now exposes payment-worker heartbeat age, invoice counts by status, payment enablement and oldest pending payment age. Prometheus rules alert on stale workers and payments pending over ten minutes. Alert delivery itself still needs configuration; local Prometheus only evaluates the rules.

Backups include invoices, balances and ledger entries. Stop API, desktop worker, payment worker and facilitator before a quiescent backup, and wait 30 seconds. The script checks worker heartbeats and locks all application tables. Preserve the encryption key separately. A database backup alone is not sufficient to protect in-flight payments: upon recovery, reconcile pending authorizations against the chain before accepting another payment.

## Verification

```sh
cd services/api
.venv/bin/python -m pytest -q
.venv/bin/python ../../scripts/check_platform_credits.py
# With the isolated Anvil network and contract artifact from X402_RAIL.md:
.venv/bin/python ../../scripts/smoke_x402_rail.py
.venv/bin/python ../../scripts/smoke_crypto_platform.py
```

The full platform smoke creates a disposable SQLite database, signs real EIP-712 authorizations, submits transactions through the SDK facilitator, verifies receipts, applies credits once, simulates a lost settlement response, rejects cross-invoice reuse, and meters two services including Cubicle. It leaves the actual workspace database untouched. PostgreSQL checks use a disposable schema to prove concurrent ledger correctness.

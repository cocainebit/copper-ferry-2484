# Shared crypto payments for Cubicle and the platform

Updated September 16, 2026. **Implemented locally; production payments are not live.** The owner selected crypto and x402 for all platform services. The platform's final payment network, treasury, native token and production pricing are not yet approved.

## Implemented payment flow

1. A signed-in workspace owner chooses a USDC top-up and creates an invoice. The server fixes the integer micro-USDC amount, network, canonical token, recipient, expiration and a unique authorization nonce. Members can view billing but cannot pay on behalf of the workspace.
2. Cubicle validates the invoice and asks an injected Ethereum-compatible wallet to sign an EIP-3009 `TransferWithAuthorization`. The signature approves the exact transfer; it is not a login signature or unlimited allowance.
3. The browser sends the base64 x402 v2 payload in `PAYMENT-SIGNATURE`. A configured facilitator verifies and submits the transfer. The backend independently checks chain settlement before granting balance; browser success is insufficient.
4. Settlement grants the invoice amount once to the workspace's shared prepaid balance. Amounts use integer micro-USDC: one USDC equals 1,000,000 units. Concurrent service debits lock the account and reject insufficient funds.
5. Cubicle charges the configured per-minute rate. Other services can charge their configured per-unit rates through the private usage endpoint. Credits are for platform consumption; customer-to-customer transfers and withdrawals are not implemented.

The UI offers 10, 25 and 50 USDC invoices, displays server-configured rates and payment history, supports wallet cancellation, and polls pending settlement without requesting another signature automatically. A pending invoice must be resolved before attempting another payment for it.

## Network and wallet compatibility

The default development asset is native USDC on **Base Sepolia**, an EVM test network. Payments remain disabled until the configured rail passes its configuration checks. Test USDC and test credits have no cash value. A mainnet configuration is not a claim of production readiness; it requires the acceptance checks in [crypto operations](CRYPTO_OPERATIONS.md).

The implemented rail supports x402 **v2**, the **exact** scheme, EIP-3009 transfers and **EOA wallets**. It does not support smart-contract wallets, Permit2, Solana Pay, Bitcoin, QR/manual deposits, or arbitrary ERC-20 assets.

### Invoice binding extension

Each server quote includes `extra.invoiceNonce`. Our shared client copies that exact 32-byte nonce into the signed authorization. This binds an authorization to one invoice instead of allowing a public on-chain transfer to be claimed for another account.

Use our `@platform/billing` client or explicitly implement this extension. A generic x402 client that generates its own nonce is incompatible with this invoice flow. Preserve the server's complete accepted requirements in the signed payload. Do not change its amount, asset, recipient, expiration rules or nonce.

## Integrating the main website and other services

`packages/platform-billing` exports the shared TypeScript client and wallet signer. See its [integration example](../packages/platform-billing/README.md). Use the same Supabase identity and workspace ID across services; sharing a Supabase project does not automatically share browser sessions between origins.

Browser-facing routes:

- `GET /v1/workspaces/{workspace_id}/payments`: balance, service rates, recent invoices and ledger entries.
- `POST /v1/workspaces/{workspace_id}/payments/invoices`: owner-only invoice creation with an `Idempotency-Key` and `amount_micro_usdc`.
- `GET /v1/payment-invoices/{invoice_id}`: authenticated invoice status.
- `POST /v1/payment-invoices/{invoice_id}/pay`: submit the x402 `PAYMENT-SIGNATURE`; without a signature, receive the standard payment-required challenge.

Other services call `POST /internal/platform/usage` from their backend with a service-specific secret, workspace, service, units and idempotency key. Prices are configured centrally; callers cannot supply their own debit amount. Keep these secrets out of browsers. The private endpoint is intentionally blocked at the public production proxy. Service backends must authorize their own customer's workspace before charging it.

The shared balance belongs to a workspace. It is not a single personal wallet balance spanning unrelated workspaces. Registering additional service prices and credentials enables shared billing; it does not create those services or their access-control integration automatically.

## Token-holder trials remain separate

The existing seven-day trial flow still requires proof of wallet ownership, an exact one-token payment, and the configured minimum holding. Its optional EVM adapter is separate from USDC billing and remains disabled pending the actual platform token configuration. A trial grants a service-specific allowance, not general spendable USDC credits.

The legacy trial service identifier `agent-desktop` remains for compatibility, while the product and prepaid service are named **Cubicle** (`cubicle`). Do not migrate trial IDs merely to rename the UI.

## Configuration and evidence

Read [crypto operations](CRYPTO_OPERATIONS.md) for rail configuration, facilitator operation, reconciliation and acceptance checks, and [ROADBLOCKS.md](../ROADBLOCKS.md) for remaining deployment inputs. Never submit treasury seed phrases or private keys in chat. The receiving address is public; facilitator signing credentials, where needed, belong only in protected server configuration.

Automated coverage includes invoice authorization, duplicate settlement protection, balance concurrency, wallet cancellation and signature validation. These checks do not prove a live production transaction has settled. A funded test-wallet transaction, real facilitator/RPC checks, outage/reconciliation exercise and operational review are required before accepting customer funds.

Protocol references: [x402 upstream](https://github.com/x402-foundation/x402), [Circle native USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses). The open protocol and a hosted facilitator are separate choices; a hosted provider may impose its own credentials, fees and policies.

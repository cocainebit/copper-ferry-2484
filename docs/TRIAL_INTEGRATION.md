# Shared platform trial service

The main website and desktop subsite should use the **same Supabase project** so the authenticated `sub` is a stable platform-user ID. Use the `@platform/trials` client or the FastAPI OpenAPI endpoints. Each future service is registered explicitly in `TRIAL_SERVICES`; unknown IDs are rejected. Entitlements are keyed by user, workspace, wallet, chain and service. Desktop access consumes the `agent-desktop` entitlement; another service must enforce its own entitlement server-side.

```ts
import {PlatformTrials} from '@platform/trials';
const trials = new PlatformTrials('/platform-api', async () => session.access_token);
const intent = await trials.createIntent(workspace.id, 'agent-desktop', wallet.address);
const signature = await wallet.signMessage(intent.message); // chain-specific encoding belongs to the wallet adapter
const instructions = await trials.verifyWallet(intent.id, signature);
// Explicitly show token, network, exact recipient, 1-token cost and deadline.
const transactionId = await wallet.sendToken(instructions);
const entitlement = await trials.redeem(intent.id, transactionId);
```

Do not accept a balance supplied by the browser or issue an entitlement merely because a transaction ID exists. The API calls a **private chain verifier** over HTTPS with a server-held bearer key. The concrete chain adapter remains blocked until network, token mint/contract, decimals, treasury, and signature format are supplied. No mock or local balance can activate a production trial.

## Adapter contract

`POST /verify-signature`: `{chain, wallet, message, signature}` → `{valid: boolean, canonical_wallet: string}`. Independently validate cryptographic ownership of the exact message, including domain, user, service, nonce and expiration. Canonicalization must be chain-specific; never lowercase a case-sensitive wallet encoding.

`POST /verify-payment`: `{chain, transaction_id, token, wallet, recipient}` →

```json
{
  "chain": "configured-network",
  "transaction_id": "canonical-transaction-id",
  "token": "configured-token",
  "sender": "canonical-wallet",
  "recipient": "canonical-treasury",
  "amount_atomic": 1000000000,
  "balance_after_atomic": 10000000000000,
  "successful": true,
  "finalized": true,
  "direct_transfer": true,
  "block_time": 1800000000
}
```

Amounts above illustrate a 9-decimal token, not the actual platform token. Return integers, never floating-point token quantities. Derive finality, exact successful transfer, sender, recipient, mint/contract and **historical post-transaction balance** from trusted chain data. Do not use the wallet's later current balance. Reject fee-on-transfer, aggregate, routed, partial and failed transfers unless a separately reviewed adapter explicitly defines equivalent semantics. Do not accept a user-selected RPC URL. Bind proof retrieval to the configured network.

The enrollment window is 30 minutes. The payment's block time must fall inside it; finalization/redemption may complete within seven additional days. No transaction, wallet/user/service pair, or workspace/service pair can grant the same trial twice. Database unique constraints provide the final concurrency guard. One payment buys one service trial. Trial access lasts exactly 168 hours from successful redemption. Holders need 10,000 tokens **after** payment. A trial has no automatic subscription conversion.

## Main site integration

Either reverse-proxy `/platform-api/*` to this service (strip that prefix) or configure `ALLOWED_ORIGINS` with the exact main-site HTTPS origin. Never expose backend database credentials, treasury keys, verifier keys, or provider keys. The customer initiates the transfer in their wallet; this service never signs financial transactions or holds wallet private keys. Customer funds are not refunded by this implementation.

For now `/trial` supports a manual wallet-signature and transaction-ID flow after configuration. A native wallet-connect button depends on the chain-specific adapter. Keep `TRIAL_ADAPTER_URL` unset until independently tested on that chain's test network. See ROADBLOCKS.md for outstanding platform decisions.

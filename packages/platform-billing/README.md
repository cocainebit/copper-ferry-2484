# Shared platform billing client

Use `PlatformBilling` from any first-party service with the platform API base URL and a callback supplying the current Supabase access token. Never expose a service API key in a browser.

```ts
const billing = new PlatformBilling("https://api.example.com", accessToken);
const account = await billing.overview(workspaceId);
const invoice = await billing.createInvoice(workspaceId, 10_000_000, crypto.randomUUID());
const signature = await signInvoice(window.ethereum, invoice, account, 10_000_000);
const result = await billing.pay(invoice.id, signature);
// Only result.status === "paid" is confirmed. Poll invoice(id) for pending settlement.
```

Amounts are integer micro-USDC: 1 USDC = 1,000,000 units. Keep the same idempotency key when retrying an invoice creation after a network failure. Do not automatically re-sign or resubmit a payment after an ambiguous network error. Check the existing invoice first.

`signInvoice` supports injected EIP-1193 EOA wallets, x402 v2 exact EVM payment requirements and EIP-3009 transfer authorization. It validates the amount, chain, token, recipient, expiry and required invoice nonce before requesting wallet access. It does not support smart contract wallets, Permit2 or arbitrary tokens. Wallet approval authorizes a transfer; it is not a login signature.

Service API calls that consume balances remain server-to-server. Workspace membership and invoice ownership are enforced by the backend. Never use client balances as authorization.

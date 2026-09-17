# Shared crypto payment rails

Research date: September 16, 2026. The platform owner selected crypto payments across services. This is a researched proposal; no gateway is installed, treasury configured, chain selected or real payment accepted. The local platform remains stopped.

## Recommendation

Build one platform billing service with stablecoin prepaid credits and per-service usage debits. Keep token-holder trial entitlements separate: the existing exact-one-token payment and holding requirement grants a particular service's trial, not a general spendable credit balance.

Start with one network and one canonical stablecoin. The native platform token's network is still unknown. If it is Solana, use native USDC with Solana Pay. If it is EVM-based, assess its network first; native USDC on Base is a reasonable default candidate if there is no existing chain preference. Circle lists native USDC on both Base and Solana. This network recommendation is our engineering judgment, not an implemented selection. [Circle contract registry](https://developers.circle.com/stablecoins/usdc-contract-addresses).

## Shortlist

| Rail or gateway | Verified capabilities | Fit and limitations |
| --- | --- | --- |
| Direct native USDC on Base | Circle identifies the canonical native USDC contract on Base. Transfers can settle directly to a merchant wallet. | Suitable for an EVM-oriented platform. We must implement checkout, invoice attribution, finality verification and reconciliation; a token transfer alone is not a billing system. |
| Solana Pay + native USDC | Open payment protocol, JavaScript SDK, SOL/SPL transfer requests and reference keys for finding and attributing payments. | Strong fit if the platform token/community uses Solana. Payment reference must be checked alongside token, recipient, amount and finalized execution. It does not supply our cross-service balance ledger. |
| Bitcart | Self-hosted, open-source, non-custodial gateway; publishes ETH, BSC, Tron and Polygon/token support, including USDT/USDC. | Best ready-made stablecoin gateway candidate to evaluate. Confirm the exact chain/token adapter in a test installation before selection; do not infer Base or Solana support merely from generic token support. |
| BTCPay Server | Self-hosted Bitcoin payments; its documentation lists additional coins/plugins, including a Tron USDT plugin. | Suitable as an optional Bitcoin rail. Stablecoin support depends on the particular plugin and must be reviewed; it is not a universal native USDC gateway. |
| x402 | Open protocol and SDKs for payment-authorized HTTP requests. | Useful later for agents purchasing API calls directly. It does not replace customer accounts, service pricing, entitlements or our accounting ledger. Self-hosted verification/settlement and a hosted facilitator are different deployment choices. |

Sources and code:

- [Solana Pay specification](https://docs.solanapay.com/spec), [SDK and reference implementations](https://docs.solanapay.com/).
- [Bitcart](https://bitcart.ai/), [supported networks](https://bitcart.ai/coins), [repository](https://github.com/bitcart/bitcart).
- [BTCPay altcoin/plugin support](https://docs.btcpayserver.org/FAQ/Altcoin/), [self-hosting model](https://docs.btcpayserver.org/BTCPayVsOthers/).
- [Maintained x402 repository](https://github.com/x402-foundation/x402). The Coinbase fork inspected during research points to this upstream.
- [Coinbase hosted facilitator](https://docs.cdp.coinbase.com/x402/seller/facilitator): requires CDP API credentials, performs transaction screening, and has a usage-based fee schedule. The open protocol does not imply every hosted facilitator has identical onboarding or acceptance policies.

## Proposed platform flow

1. Signed-in customer requests a top-up invoice for a platform account/workspace. The server fixes amount, chain, canonical token, recipient, expiry and invoice identity; the browser cannot choose these authoritative fields.
2. Wallet checkout or a payment QR requests the transfer. Bind it to the invoice using the chosen rail's verified attribution mechanism. Matching amount alone is insufficient.
3. A payment worker checks the chain result, canonical asset, recipient, exact base-unit amount, success and required finality. A browser success message or unverified webhook is not settlement evidence.
4. A database transaction records the unique chain payment and credits the balance exactly once. Deduplicate using chain plus transaction/event identity. Use integer units, never floating-point token amounts.
5. Each service reserves or spends credits through the central ledger with its own service identifier and idempotency key. Concurrent services must not overspend the shared balance.
6. Show usage and receipts centrally. Customers top up manually in the first release; no automatic wallet debit or unlimited token approval.

The existing app tracks desktop minutes per workspace. A shared monetary/credit ledger and price conversion per service are new work. These credits should initially purchase our services only; transferability and customer withdrawals are outside this proposal.

## Implementation and acceptance work

- Connect a wallet checkout and implement authenticated invoice creation/status.
- Test finality/reorganizations, duplicate notifications, wrong token/network/recipient, late and partial payments, overpayments, and concurrent credits/debits.
- Define refund/reconciliation policy and a controlled treasury-signing process. An inbound-payment verifier should not need the treasury spending key.
- Add durable reconciliation, RPC outage recovery, accounting export, receipt history and operations alerts.
- Pin and inspect any gateway dependency/version and its license before integration. A listed repository has not been security-audited or boot-tested during this research.
- Do not repurpose the existing trial verifier unchanged for USDC: it currently accepts reviewed immutable standard ERC-20 code and rejects proxies. Stablecoin payment verification needs its own asset policy and adapter.
- Budget for hosting, blockchain RPC access and network fees. Self-hosted software without a processor percentage is not cost-free infrastructure.

## Inputs needed before a live setup

Platform token network/address; preferred customer payment network; public treasury receiving address; pricing/credit denomination and refund policy. Never send seed phrases or private keys in chat. Local business obligations and any exchange/off-ramp onboarding are separate from using permissionless payment protocols.

## Research artifacts

Saved source material: `/Users/achi/.firecrawl/rails-*.json` and `/Users/achi/.firecrawl/rails-*.md`. Provider claims and network support should be rechecked when pinning an implementation version.

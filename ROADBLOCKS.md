# Roadblocks and deployment requirements

Updated September 16, 2026. This records review items without interrupting implementation.

## Implemented and verified locally

- Real Linux desktops, authenticated live VNC viewing, visible browser/terminal control, pause/takeover, persistent home volumes and system snapshots.
- Dedicated Postgres now backs the running app. Existing SQLite data migrated without deleting the original. Real Postgres tests cover duplicate billing, last-credit races, trial uniqueness and scheduler locks.
- Local Supabase email sign-in, asymmetric JWT validation, session refresh/logout and workspace isolation pass against the running API. Explicit local preview access preserves the original development workspace.
- Desktop cloning copies home and system state independently. System-only templates omit home data and survive deletion of their source/template. CPU/RAM choices are enforced by Docker and tested with real desktops. Failed copies cannot be started or controlled.
- Worker lifecycle tests exposed and now cover stale workers overwriting replacement leases/results. No uncertain tool operation is automatically replayed.
- Readiness checks cover database, worker heartbeat and runtime. Local Prometheus successfully scrapes the protected metrics endpoint; basic alert rules are loaded.
- An encrypted backup of database, runtime metadata, homes and snapshot images passed integrity checks and a fresh disposable Postgres restore/count comparison. Local-only recovery is not off-host disaster protection.
- Production API and frontend Docker images build. A dedicated-Linux deployment scaffold requires gVisor and a scoped firewall; no production firewall or public deployment was applied here.
- Optional EVM verifier implements signed wallet ownership, exact ERC-20 transfer, finalized historical holdings, replay protection and fail-closed handling of ambiguous transaction ordering. This is an available adapter, not a selection of the platform chain.

## External configuration needed

- Anthropic key: no key exists in the local workspace. The agent implementation and mocked lifecycle tests pass; a real model-driven task remains unverified.
- Production Supabase project, Google/GitHub OAuth applications, production SMTP and redirect domains. Local email authentication works; public OAuth/email delivery has not been tested.
- Payment direction changed to shared crypto billing across services. Stripe integration remains disabled and is no longer the default launch dependency. Crypto invoices, a shared credit ledger, a selected chain/asset and treasury configuration still need implementation; see docs/CRYPTO_PAYMENTS.md.
- Cloud account, dedicated Linux host, production Postgres, domain/DNS/TLS and stable secret storage. Local Postgres is running; it is not a deployed managed production database.
- Platform network, token address/mint, decimals, treasury, confirmation policy and wallet UX. If EVM is selected, the adapter requires a reviewed immutable standard-token runtime code hash and real testnet checks. Other networks require their own adapter. No user should send payment until the selected adapter and policy are tested.
- Broader main website repository and identity/domain design. The reusable trial client/API exists; cross-subdomain SSO and main-site embedding require that integration context.
- Product Design plugin installation was not confirmed; frontend implementation proceeded independently.

## Policies to review

- One seven-day trial per wallet AND platform user per service. Exactly one token buys one service trial; no stacking, automatic conversion or cross-service activation.
- Holdings are checked once immediately after payment: at least 10,000 tokens must remain, requiring at least 10,001 beforehand for the standard transfer. This is not continuous token locking. Chain gas is separate.
- Trial defaults: 10 desktop-hours during the week, one running/saved computer, customer Anthropic key. Review capacity before launch.
- EVM transfers with ambiguous later same-block holder activity fail closed. Define payment reconciliation/refund handling before accepting funds.

## Production work remaining

- Run Linux/gVisor acceptance tests for tenant isolation, Chromium sandbox compatibility, network/metadata restrictions and direct-port access. macOS development Chromium uses --no-sandbox only under DEV_MODE=true; never expose development mode publicly.
- Enforce hard storage quotas; current 20 GiB copy bounds are not filesystem capacity enforcement. Windows/macOS desktops, arbitrary hardware sizes and live memory snapshots are not implemented.
- Configure off-host scheduled backups, retention, alert delivery and a complete fresh-host desktop recovery drill. Local backup tooling requires a stopped service and sufficient staging space.
- Add deployment-grade abuse/rate limiting, lifecycle/retention policy, versioned schema migrations and broader load/security tests. Current upgrades are additive and startup-oriented.
- Agent approval is model-mediated. An unrestricted shell/browser can bypass it; do not promise guaranteed action approval enforcement without stronger controls.
- Snapshot-on-stop does not protect unsaved system changes from sudden host loss.
- The application remains local in /Users/achi/agent-desktop; the separate application repository has not been published. Upstream fork: https://github.com/cocainebit/OpenSandbox.

## Verification summary

85 backend tests, 20 optional EVM verifier tests and three isolated Playwright flows pass. Live checks cover local Supabase authentication, Postgres concurrency, desktop cloning/templates/cgroup limits, Prometheus scraping and encrypted backup restoration. Production container builds pass. These checks do not establish public production readiness or real Stripe/Anthropic/chain-provider integration.

## Automatic approval review restriction

Automatic approval review rejected execution of the optional Anthropic provider-preflight script because it could decrypt a stored key and send it to Anthropic without destination-specific authorization. No request was sent. A real provider check remains deferred; the local workspace also has no Anthropic key configured.

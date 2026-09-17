# Roadblocks and deployment requirements

Updated September 17, 2026. This records review items without interrupting implementation.

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
- Shared crypto billing and x402 wallet checkout are implemented. Real payments remain disabled until a public receiving wallet, reviewed Base USDC configuration, reliable RPC and separately funded facilitator gas signer are supplied. No business-country/bank-account onboarding is part of the current direct-crypto implementation. Stripe is retained only as dormant legacy code. See docs/CRYPTO_OPERATIONS.md.
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

148 backend tests, 20 optional platform-token verifier tests and five isolated Playwright flows pass. The full real-signature browser-to-local-blockchain checkout and PostgreSQL concurrent financial checks also pass. API, frontend and self-hosted facilitator Docker images build successfully. Live checks cover local Supabase authentication, Postgres concurrency, desktop cloning/templates/cgroup limits, Prometheus scraping and encrypted backup restoration. Production container builds pass. These checks do not establish public production readiness or real Stripe/Anthropic/chain-provider integration.

## Automatic approval review restriction

Automatic approval review rejected execution of the optional Anthropic provider-preflight script because it could decrypt a stored key and send it to Anthropic without destination-specific authorization. No request was sent. A real provider check remains deferred; the local workspace also has no Anthropic key configured.


## Cubicle crypto implementation — September 17

- Product name is **Cubicle**; existing `agent-desktop` trial identifiers remain for compatibility. The broader platform name and repository are still unspecified.
- Shared integer micro-USDC ledger, server-priced cross-service debits, wallet checkout, invoices, receipts/activity history, dedicated payment worker, monitoring and reconciliation tools are implemented.
- Real local test-chain verification passes from browser signature through official x402 facilitator settlement to independent receipt verification and exactly-once credit. A separate API smoke proves lost-response recovery, two-service charging and prepaid desktop access. Tests use fake Anvil tokens and separate disposable databases; existing user balances are untouched.
- Initial supported payment scope: native USDC on Base/Base Sepolia, EOA EIP-3009 signatures and our invoice-nonce client extension. Solana, arbitrary payment tokens, smart-contract wallets, Permit2 and automatic renewals are not implemented. Generic x402 clients must use the invoice nonce; this is not a claim of universal client compatibility.
- Receipt confirmation count defaults to three; this is not guaranteed finality. Review the mainnet confirmation/reorganization policy and treasury gas-budget/alerting before launch. Real Base Sepolia and Base-mainnet transfers have not been performed.
- Configure another service's server price and scoped backend secret, then integrate its private usage calls and shared account identity. This repository supplies the shared API/TypeScript client; unknown external repositories are not automatically integrated.
- There is no automated treasury refund or withdrawal UI. Establish refund terms and an operator reconciliation/adjustment procedure before accepting public payments. Do not merge test credits into a production balance database.
- Proposed default Cubicle price is 3,334 micro-USDC/minute (~0.20 USDC/hour); pricing and infrastructure margins need review before live activation.
- The previous Anthropic approval-review restriction still applies. No Anthropic key was supplied, so real autonomous model-driven desktop execution remains unverified.

## Completion specification and creation controls

- [Production completion specification](docs/COMPLETION_SPEC.md) defines twelve milestones, dependencies and measurable launch gates.
- Create computer now accepts CPU/RAM and ready private templates, with atomic resource persistence, inline errors and copy progress. Supported sizes remain 1/2 CPU and 2/4 GiB; hard storage quotas and display resolution controls remain unfinished.
- Latest verification: 154 backend tests and seven browser tests pass; TypeScript and Python lint checks pass. These checks do not change the external configuration or production acceptance blockers above.

## Display customization and broader parity

- Three display presets work in creation/settings, template inheritance and runtime startup. Actual X dimensions were verified in disposable network-isolated Docker containers for all presets. Startup rejects scripts that ignore selected geometry.
- Existing database rows receive the default through an additive upgrade, tested for repeatability and legacy data preservation. Run upgrade before API/worker restart; production versioned migrations remain open.
- [Full parity audit](docs/ORGO_PARITY.md) extends the intermediate v1 with OS providers, SDK/CLI/MCP, app integrations, resource addons, richer templates and streaming. These remain requirements of the full objective.
- Current verification: 159 backend tests, seven browser tests, TypeScript checks and desktop image build pass. Public production readiness remains unproven.

## Configurable idle stop

- Creation and stopped-desktop settings now support idle timeouts, including Always on (zero). API allows integer 0–1440 minutes; default stays 15. Clones/templates inherit the policy and callers can override it.
- Worker reconciliation tests verify always-on keeps running without dashboard activity, usage continues to be deducted, selected finite timeouts stop inactive desktops and depleted credits still stop always-on desktops. Guest background processes do not reset idle activity; use Always on for them.
- Optional profile updates now preserve omitted CPU/RAM/display/idle values. Additive database upgrade preserves existing 15-minute defaults and is tested for repeat execution.
- 172 backend tests and seven browser tests pass; TypeScript and Python lint pass. Local API/worker restarted after migration. A real production-duration unattended-workload soak remains unverified.

## File uploads

- Added owner/controller-only upload into Home at `POST /v1/computers/{id}/upload`, with a 20 MiB limit, base64 validation, safe path enforcement and dashboard file picker. The desktop helper creates missing parent directories and refuses directory targets.
- 174 backend tests and frontend typecheck pass. Streaming multipart uploads, progress/resume, delete/export endpoints and production storage quotas remain open parity work.

## File deletion

- Added controller-only `POST /v1/computers/{id}/delete-file` and a file-browser delete action. The runtime refuses Home itself, directories, missing paths and paths that resolve outside Home.
- 180 backend tests and frontend typecheck pass. Binary streaming, resumable transfers, bulk operations and production disk quotas remain open.

## Storage tiers

- Profiles, templates and creation bodies accept `storage_gib` in {20, 50, 100}; clones and templates inherit it and template consumers can override it. The additive upgrade adds the column with default 20.
- Enforcement is runtime-dependent and reported truthfully: `storage_quota_enforced` in the profile response comes from `STORAGE_QUOTA_ENFORCED` (default false). Docker named volumes ignore the requested size, so locally the tier only bounds the clone copy (source home must fit the target tier) and is shown against measured usage. OpenSandbox's Kubernetes runtime sizes the claim from the same value. Hard quota acceptance under M2 therefore still requires the Kubernetes runtime or a filesystem quota on the Docker host.
- `/v1/config` now advertises Cubicle's per-minute USDC price instead of the retired Stripe plan.

## Terminal, clipboard, rename and developer platform (September 17, 2026, Claude Code)

- Interactive terminal: `desktop_service/guest/pty_server.py` is injected through the sandbox entrypoint at every boot and launched as root before the desktop drops privileges, so saved snapshots never pin an old copy. It binds the sandbox interfaces (the OpenSandbox proxy connects over the bridge network) and refuses handshakes without the per-computer token in `Computer.pty_secret`. The API relays it at `/v1/computers/{id}/pty` for the person in control only. The OpenSandbox proxy strips `Authorization`, so the token is sent as a query parameter on the proxied URL and the worker rotates it at every start; keep OpenSandbox proxy logs private. Desktop images need the `websockets` package (added to the image); older saved systems fall back to the one-shot runner.
- API keys and computer API: keys act as their creator inside one workspace with read/control/manage scopes enforced per matched route; session-only routes (keys, credential, members, invitations, trials, payments) answer 403 to keys. The operator rule lets any workspace member or key drive a computer while no human holds control and no built-in task is leased. The rate limiter is per API process.
- SDK/CLI/MCP were exercised against a live desktop on 2026-09-17 (CLI screenshot/key/type/bash, Python SDK screenshot/upload/download/bash, MCP screenshot as image content plus bash). The MCP server depends on `@modelcontextprotocol/sdk` and `zod`.
- Docker host hygiene: the orphan `desktop-*` volumes and the `crypto-check`/`production-check` images were removed on 2026-09-17 with the owner's approval. Deleting a computer wipes its home but leaves the empty named volume behind; a periodic reconciliation of volumes against non-deleted computers is still missing (M8).

## Trial enrollment header (September 17, 2026)

- The API signs `Cubicle trial enrollment` while the shared verifier required `Agent Desktop trial enrollment`, so every real enrollment would have been rejected with 400 once trials were configured (found by a read-only audit from the Plotform session). The verifier now accepts a service-branded first line (`<name> trial enrollment`, up to 40 characters); the eight bound fields and the fixed footer are unchanged and remain what the signature commits to. Contract tests on both sides pin the exact API message. No live-chain trial has been run yet.

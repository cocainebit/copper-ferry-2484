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


## Cubicle crypto implementation, September 17

- Product name is **Cubicle**; the platform it sits on is **Instance** (instanceOS), shared with Floatlane and Plotform (owner decision, September 17, 2026). Existing `agent-desktop` identifiers stay for compatibility. Domain, repository and the trial token are still undecided.
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

## Parity build: templates, apps, secrets, automations, screens, audio, fleet, providers (September 17, 2026)

- Verified live on this host: template registry build and launch, app catalog install, secret injection into login shells, webhook and file-watch automations, multiple screens in the API and viewer, audio streaming (tone measured through the API), fleet overview and bulk start with plan-limit refusals.
- Guest tooling (tools.py, pty_server.py, screen.sh, audio_server.py) is injected from the API at every boot, so saved snapshots never pin old copies. Audio additionally needs PulseAudio in the system: the rebuilt image has it; older saved systems need it installed (the catalog cannot yet do this) or a template rebuild.
- Windows and GPU computers are config-gated (`WINDOWS_ENABLED`, `GPU_ENABLED`) and unit-tested only; they need a KVM host and an NVIDIA host running OpenSandbox. Windows computers support the viewer and lifecycle automations; agent control, files, apps and the terminal are Linux-only for now. macOS is not offered.
- Automation `agent_task` actions and template `requires_secrets` for provider keys are wired but cannot be exercised end to end without an Anthropic key.
- Limits worth reviewing before launch: 20 automations per computer, 300 executions per day, 10 template definitions and 20 versions, 50 secrets, four screens, and plan limits now in settings (`PAID_SAVED_COMPUTERS`, `PAID_RUNNING_COMPUTERS`, `TRIAL_*`).

## Billing shape (September 17, 2026, owner decision)

- Cubicle sells a **day pass (24 h)** and a **monthly pass (30 days)** next to per-minute pay as you go. A pass gives unlimited runtime inside its own computer and resource limits; passes never auto-renew (x402 cannot), and buying again extends from the current expiry.
- Prices are unset in code. Set them as `PLATFORM_SERVICE_PRICES` SKUs `cubicle-pass-day` and `cubicle-pass-month` (micro-USDC); until then the plans are listed as not for sale and the dashboard shows "price not set". The per-minute rate remains the reviewed-but-provisional 3,334 micro-USDC.
- Open pricing questions for M1: the actual numbers, whether an annual pass exists, and whether the token-holder trial becomes a pass variant.
- When the shared platform ledger takes over, plan purchases need their own SKUs there too (`cubicle.pass.day`, `cubicle.pass.month`) alongside the per-minute `cubicle.minute.*` SKUs.

## Platform billing v0.2 (September 17, 2026)

- The platform dropped balances: pay per action, one charge per payable thing, no recurring anything. Cubicle now sells runtime as hour blocks per computer (SKU per resource tier) plus day and monthly passes, each one charge. Owner decisions: hour blocks plus passes, and warn-then-stop when the next block is unpaid.
- Configuration: `PLATFORM_URL` and `PLATFORM_SERVICE_TOKEN` (service token from `pnpm admin service create cubicle cubicle`, stored in the gitignored `.env`). Unset means Cubicle keeps its own credit ledger and per-minute metering.
- SKUs needing prices before anyone is charged: `cubicle.hour.cpu1-mem2`, `cubicle.hour.cpu2-mem4` (and `-gpu` variants when GPU hosts exist), `cubicle.pass.day`, `cubicle.pass.month`. Unpriced means free.
- Platform behaviour to know: creating any charge fails with 503 while the platform has no payment options configured, including for unpriced SKUs, so Cubicle checks `/internal/v1/prices` first and only asks for a charge when the SKU is priced. Reported to the platform session.
- Set `docker.strict_resource_limits = true` on the OpenSandbox deployment before Cubicle bills anyone (fork commit da1232e). Cubicle only ever sends `memory`, `cpu` and `gpu`, so it costs nothing today, and it means a future typo in `feature_runtime.resource_for` fails the desktop at creation instead of quietly running it unenforced while the tier SKU still charges. Not set on the local dev server, whose engine image predates the flag and would reject the unknown key.
- Swap is not capped for any desktop. Docker allows twice the memory limit in swap when nothing sets `memswap_limit`, and the engine never did, so a 4 GiB desktop can take another 4 GiB of host disk and IO. The fork now has a `docker.swap_ratio` setting (cocainebit/OpenSandbox e85b770) that caps it, defaulting to today's behaviour. Turning it on is a real trade and not made here: capping swap turns a memory spike into a killed process rather than a slow desktop, so the owner should choose before it goes anywhere near a shared host.
- The billed shape is enforced, checked on a live desktop September 17, 2026: a cpu2-mem4 computer's container came back with `NanoCpus 2000000000` and `Memory 4294967296`, so `cubicle.hour.cpu2-mem4` prices something the engine actually holds the desktop to. Disk is the exception and always was: Docker ignores the PVC size, which is why `storage_quota_enforced` exists and says so. Note `MemorySwap` is twice `Memory`, so a desktop can reach that much again in host swap.
- Failure policy: a platform outage or misconfiguration never stops or fails a running desktop. It keeps running, records one event, and retries. That is deliberate and means an outage can give away runtime.
- Not done: identity cutover (JWKS in `security.identity`), mapping workspaces to platform organizations, and remapping stored user ids. The credit ledger and Cubicle's own x402 rail stay until then.

## Identity cutover (September 17, 2026)

- Cubicle verifies Instance platform tokens (JWKS at `{PLATFORM_ISSUER}/jwks`, audience `PLATFORM_AUDIENCE`) and still accepts Supabase sessions, the local development token and `cbk_` API keys. Supabase is not removed yet; it stays until every account has moved.
- The platform signs with **Ed25519 (EdDSA)**, not ES256 or RS256. A verifier pinned to the usual pair rejects every real token.
- Linking is one way and runs on first platform sign-in: verified email first, linked wallet address second, then rewriting stored user ids in one transaction. Ambiguity is never resolved by guessing; the account becomes a new member instead and the legacy data is untouched.
- Wallet-only platform accounts have no email at all, so email-only matching silently misses them. That is why wallet matching exists.
- Charges carry the platform organization id once a workspace is mapped; before that they carry nothing rather than Cubicle's own workspace id.
- Verified against the real platform on September 17, 2026 with two tokens minted by the platform session: an account with a verified email adopted its legacy user by email, and a wallet-only account (`email: null`) adopted its legacy user by an `eip155` address that was stored here in a different case. Both workspaces came out mapped to the right personal organization.
- `aud` is an **array** in real tokens: the provider lists its own `/oauth2/userinfo` beside our resource. Accept a token whose audience contains our resource. PyJWT does this correctly with `audience=`, and there is now a test so a refactor cannot quietly break it.
- The browser half is verified as far as the platform's own sign-in page: `/login` sends a correct PKCE S256 request and the platform renders "Sign in to continue to Cubicle" with Ethereum wallet, Solana wallet and email-code options. A mismatched `state` on the way back is refused without exchanging anything.
- Cubicle is registered as a **confidential** client (`client_secret_post`), but its token exchange runs in the browser with PKCE and no secret, which is the wrong pair. Asked the platform session to re-register it as public (`token_endpoint_auth_method: none`). `PLATFORM_CLIENT_SECRET` was unused by any code here and has been removed from `services/api/.env`.
- Still open: nothing removes Supabase or Cubicle's own credit ledger yet, no production identity project exists, and no SKU is priced on the platform (`/internal/v1/prices` is empty), so all runtime is free until the owner sets prices.

## Per-second runtime with a monthly cap (September 19, 2026)

- Hour blocks are gone. Runtime is bought in packs of whole hours per computer and metered by the second while it runs, capped at 190 hours per computer in any 30 days (`docs/PRICING.md` sections 6 to 8, approved by the owner).
- This fixed a latent bug: under hour blocks a new computer booted, then its first tick found the first hour unpaid and stopped it, so with any price set no computer could ever start. A computer with no paid time now waits in `starting` until its charge is paid.
- The old `runtime_hours` table stays in existing databases, unused. No real money ever moved through it: no `cubicle.hour.*` SKU has ever been priced, so every block was free.
- A worker outage is not charged: a tick more than 120 seconds after the last one counts as 120. A platform outage keeps desktops running unmetered, as before.
- Verified by 26 unit tests (each of eight deliberate breakages of the meter is caught by at least one), a browser test that renders the strip in all eight billing states at full and phone width, and the platform's own source for how it prices `units` above 1. Not verified live against the real platform: the machine had rebooted, the platform service was down, and no tier is priced, so a live run would only have exercised the free path.
- **Owner action needed:** price every `cubicle.hour.*` tier together (table in `docs/PRICING.md` section 8). Pricing one tier alone makes the others free.
- Corrected the same day, found while writing the public docs: the tier list covered a 4 CPU size nobody can create and missed `cpu1-mem4` and `cpu2-mem2`, which would have run free once the listed tiers were priced. Tiers now derive from the sizes the API accepts, with a test tying them together.
- Also found then: every agent task was refused with 402 "No credits remaining" on Instance billing, because task creation still checked Cubicle's old credit balance, which is always zero there. It now uses the same `can_run` rule as starting a computer, with regression tests for both billing modes.


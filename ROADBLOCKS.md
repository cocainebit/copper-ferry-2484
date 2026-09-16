# Roadblocks and deployment requirements

Updated during implementation. Items here are not requests to interrupt work.

## Resolved
- Disk was full. Cleared only the regenerable npm download cache (about 2.6 GB), without deleting projects.
- GitHub authentication worked outside the network sandbox. Fork created: https://github.com/cocainebit/OpenSandbox
- Docker Desktop’s hung backend was recovered without deleting its data. OpenSandbox and the actual desktop now run locally.

## External configuration required
- Product Design plugin: suggested through Codex; installation has not been confirmed. Frontend work continues independently.
- Supabase project/OAuth credentials, transactional email delivery, Stripe account/price IDs/webhook secret, Anthropic test key, cloud hosting credentials, and domain/DNS are not supplied.
- The broader website repository/domain and shared identity configuration are unknown. Implementing a standalone embeddable trial page and versioned entitlement API for integration.
- Token trials: blockchain/network, token contract or mint, decimals, treasury recipient, confirmation policy, and wallet-signature standard are unknown. Live verification MUST fail closed until a concrete verified chain adapter is configured.
- Trial policy defaults for review: one seven-day trial per wallet AND platform user per service; holdings checked at the finalized payment block immediately AFTER the exact one-token transfer (requires at least 10,001 tokens beforehand); transfers must be direct from the verified wallet; no reuse of payment proofs; no trial stacking or resets. One payment activates one service, not every service.
- Trial capacity default: 10 total desktop-hours during the week, one running computer, one saved computer, customer Anthropic key required. No automatic paid conversion. These limits protect shared launch capacity and remain configurable per service.

## Verification and remaining launch work

- **Docker integration resolved:** real provisioning, VNC handshake, screenshots, visible browser control and home/system persistence pass the disposable smoke test. The dashboard also connects to the live desktop; takeover, terminal execution and a dashboard stop/save/restart cycle pass. An installed `jq` package survives the system snapshot and restart. A stale backend process and cross-bridge network connectivity caused the earlier failures.
- **Public deployment is not done.** No paid cloud resources were provisioned, no real payment was collected, and checkout remains disabled by default.
- Hard 20 GiB storage quotas, hardened tenant isolation/egress rules, encrypted backup/restore automation, cancellation retention, rate limiting/abuse controls and production monitoring remain required. See `docs/DEPLOYMENT.md`. The UI does not claim an enforced storage cap.
- Agent approval is model-mediated; the unrestricted shell/browser can bypass it. The pause/approval state machine is implemented, but adversarial testing and stronger restrictions are required before promising guaranteed approval enforcement.
- Trial holdings default is a one-time finalized post-payment check, not continuous token locking or monitoring. Holders can later move tokens. Chain fees require separate native gas funds where applicable. Review this policy before launch.
- A chain adapter and native wallet-connect UI cannot be completed correctly until the platform token/network is identified. Current manual signature/transaction flow fails closed without configuration.
- Main-site SSO across subdomains is not implemented; shared Supabase identity alone does not share localStorage sessions. Integration requires the broader website code/domain.
- An additive database upgrade now adds system-snapshot tracking and worker heartbeats. A general versioned migration framework is still required. Production concurrency tests on Postgres remain outstanding; local tests use isolated SQLite databases.
- App source is local at `/Users/achi/agent-desktop`. The upstream OpenSandbox fork exists on GitHub; the separate app repository has not been published.

## Validation completed

- 42 backend tests: authentication/workspace isolation, quotas, encrypted credentials, idempotency, metering, billing ordering, exact token units/holdings, trial expiration/replay, in-flight task leases, runtime adapter behavior and download path containment.
- Three Playwright browser flows pass against a real isolated API: responsive landing/sign-in, workspace creation/settings/billing, and unavailable trials never requesting payment.
- Production frontend build passes, including the noVNC module. A real browser also connected to the running noVNC desktop.
- JavaScript dependency audit: zero known vulnerabilities after patching PostCSS. Python dependencies have not received a separate vulnerability audit.
- Supabase, Stripe, Anthropic and chain-verifier behavior has not been tested with live credentials. The local workspace has no Anthropic key, so an actual model-driven task remains unverified. No claim of production readiness is made.

## Customization milestone — September 16

- Normal stop waits for an asynchronous system snapshot before destroying the sandbox; start restores it alongside the persistent home volume. Default theme initialization runs only once.
- The API refuses new starts while the worker heartbeat is missing/stale, instead of leaving requests silently queued.
- Current customization includes home/browser settings and system applications via the administrator dashboard terminal. Templates, cloning, resource/display controls and other operating systems remain future work.
- Development Chromium uses `--no-sandbox` only under `DEV_MODE=true`. Public deployment must provide a hardened runtime compatible with Chromium's own sandbox. Do not enable public access to the local preview.
- Snapshot-on-stop is not backup/continuous autosave. Host loss before snapshot can lose recent system changes; home backups are still outstanding.
- Customer guides added: `docs/GETTING_STARTED.md` and `docs/CUSTOMIZING_DESKTOPS.md`.

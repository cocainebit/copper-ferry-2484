# Roadblocks and deployment requirements

Updated during implementation. Items here are not requests to interrupt work.

## Resolved
- Disk was full. Cleared only the regenerable npm download cache (about 2.6 GB), without deleting projects.
- GitHub authentication worked outside the network sandbox. Fork created: https://github.com/cocainebit/OpenSandbox
- Docker Desktop was initially stopped; started for integration checks.

## External configuration required
- Product Design plugin: suggested through Codex; installation has not been confirmed. Frontend work continues independently.
- Supabase project/OAuth credentials, transactional email delivery, Stripe account/price IDs/webhook secret, Anthropic test key, cloud hosting credentials, and domain/DNS are not supplied.
- The broader website repository/domain and shared identity configuration are unknown. Implementing a standalone embeddable trial page and versioned entitlement API for integration.
- Token trials: blockchain/network, token contract or mint, decimals, treasury recipient, confirmation policy, and wallet-signature standard are unknown. Live verification MUST fail closed until a concrete verified chain adapter is configured.
- Trial policy defaults for review: one seven-day trial per wallet AND platform user per service; holdings checked at the finalized payment block immediately AFTER the exact one-token transfer (requires at least 10,001 tokens beforehand); transfers must be direct from the verified wallet; no reuse of payment proofs; no trial stacking or resets. One payment activates one service, not every service.
- Trial capacity default: 10 total desktop-hours during the week, one running computer, one saved computer, customer Anthropic key required. No automatic paid conversion. These limits protect shared launch capacity and remain configurable per service.

## Verification and remaining launch work

- **Docker integration blocked:** Docker Desktop starts, but `docker info` returns `Error reading remote info: EOF`; restart did not restore a usable engine. No factory reset or Docker data deletion was performed. The real desktop image, VNC stream, visible Chromium, SDK provisioning and persistent-home lifecycle remain unverified end to end. A disposable integration smoke test is provided in `scripts/smoke_desktop.py`.
- **Public deployment is not done.** No paid cloud resources were provisioned, no real payment was collected, and checkout remains disabled by default.
- Hard 20 GiB storage quotas, hardened tenant isolation/egress rules, encrypted backup/restore automation, cancellation retention, rate limiting/abuse controls and production monitoring remain required. See `docs/DEPLOYMENT.md`. The UI does not claim an enforced storage cap.
- Agent approval is model-mediated; the unrestricted shell/browser can bypass it. The pause/approval state machine is implemented, but adversarial testing and stronger restrictions are required before promising guaranteed approval enforcement.
- Trial holdings default is a one-time finalized post-payment check, not continuous token locking or monitoring. Holders can later move tokens. Chain fees require separate native gas funds where applicable. Review this policy before launch.
- A chain adapter and native wallet-connect UI cannot be completed correctly until the platform token/network is identified. Current manual signature/transaction flow fails closed without configuration.
- Main-site SSO across subdomains is not implemented; shared Supabase identity alone does not share localStorage sessions. Integration requires the broader website code/domain.
- Database initialization supports a fresh schema; versioned upgrades are not implemented. Production concurrency tests on Postgres remain outstanding; local tests use isolated SQLite databases.
- App source is local at `/Users/achi/agent-desktop`. The upstream OpenSandbox fork exists on GitHub; the separate app repository has not been published.

## Validation completed

- 40 backend tests: authentication/workspace isolation, quotas, encrypted credentials, idempotency, metering, billing ordering, exact token units/holdings, trial expiration/replay, in-flight task leases, runtime adapter behavior and download path containment.
- Three Playwright browser flows pass against a real isolated API: responsive landing/sign-in, workspace creation/settings/billing, and unavailable trials never requesting payment.
- Production frontend build passes, including the noVNC module. Live noVNC connection still requires the Docker integration test.
- JavaScript dependency audit: zero known vulnerabilities after patching PostCSS. Python dependencies have not received a separate vulnerability audit.
- Supabase, Stripe, Anthropic and chain-verifier behavior has not been tested with live credentials. No claim of production readiness is made.

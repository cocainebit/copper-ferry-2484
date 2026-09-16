# Deployment checklist

This is a deployment guide, not a record of a completed deployment. Keep public paid access disabled until the checks below pass.

## Services

1. Provision Postgres and a Supabase Auth project. Configure Google, GitHub and email OTP/link delivery, production site URL and allowed redirects for `/app` and invitations. Share this identity project with the main website. A shared identity provider does not automatically share browser sessions across subdomains; implement main-site SSO/session exchange if needed.
2. Supply backend environment variables from `.env.example`; set `DEV_MODE=false`. Generate a Fernet key with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` and a separate random signing key. Store them in the hosting secret manager.
3. Run `uv run python -m desktop_service.migrate` from `services/api` against a new database. This creates the initial schema and revokes browser-role table access. Introduce versioned migrations before changing an existing production schema.
4. Build the desktop image on a dedicated Linux host. Deploy OpenSandbox privately with a rotated API key and a hardened runtime. The checked-in Compose and TOML files are for local development. Do not publish its API, Docker socket, VNC, execd or CDP ports.
5. Start the API and one worker from `services/api`: `uv run uvicorn desktop_service.main:app --host 127.0.0.1 --port 8000` and `uv run python -m desktop_service.worker`. Use a supervisor with restart-on-failure. More API replicas may share Postgres; one scheduler owns its advisory lock.
6. Build the frontend with production Supabase values and `NEXT_PUBLIC_DEV_MODE=false`. Leave `NEXT_PUBLIC_WS_URL` unset behind Caddy. Run `npm run start --workspace apps/web`. Deploy Caddy with the real `APP_DOMAIN`, HTTPS and the supplied same-origin `/api` routing.
7. Create Stripe recurring $29/month and one-time $10 prices, configure the customer portal, and register `/api/v1/billing/webhook` for `invoice.paid`, `checkout.session.completed`, `customer.subscription.updated` and `customer.subscription.deleted`. Test duplicate/out-of-order events using a Stripe test account. Checkout is disabled until `LAUNCH_ENABLED=true`.
8. Configure a concrete trial verifier only after the network, token and treasury are confirmed and test-network proofs pass. See TRIAL_INTEGRATION.md. Unknown/partial configuration must not request payment.

## Required host work before public launch

- Enforce 20 GiB persistent-home quotas using the chosen host/storage backend. Docker named volumes alone do not enforce them. Monitor disk pressure; ensure tenant writes cannot exhaust the control plane.
- Use the chosen hardened isolation boundary (gVisor/Kata or per-tenant VMs) and test Chromium, VNC and execd there. Default Docker containers are a local development baseline.
- Deny sandbox traffic to host/control-plane/private networks and cloud metadata endpoints; preserve required public web access. Validate both IPv4 and IPv6 paths and DNS rebinding behavior.
- Automate encrypted home-volume and database backups, retention and a complete restore drill. Decide and implement cancellation retention before promising a deletion deadline. No backup or automatic 30-day deletion job currently runs.
- Add rate limits, signup/abuse controls, provider-spend budgets, centralized redacted logs, uptime/disk/capacity alerts and operator runbooks. Set explicit hosting spend alerts.
- Test simultaneous users on Postgres, stale worker recovery, tenant isolation, takeover revocation, metering under failure, payment webhooks and prompt-injection/approval bypasses.
- Run `scripts/smoke_desktop.py` and a real BYOK task, including closing/reopening the browser during execution.

The $200–500 monthly infrastructure target has not been validated with a provider quote or a load test. Pricing is implemented as an initial product assumption, not demonstrated unit economics.

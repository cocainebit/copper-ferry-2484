# Deployment checklist

This guide describes deployment work; it is not a record of a completed public deployment. Keep paid access disabled until the checks below pass. The local system now uses PostgreSQL, a separate Supabase Auth stack and Prometheus; production hosting and provider accounts remain separate work.

## Services and configuration

1. Provision production Postgres and a Supabase Auth project. Local email-code delivery, refresh, logout and backend verification have been exercised with local Supabase; Google/GitHub and hosted mail still require provider applications and SMTP configuration. Follow [account setup](ACCOUNT_SETUP.md). Share the identity project with the main website, but implement session exchange if cross-subdomain SSO is required: a shared identity provider alone does not share browser sessions.
2. Supply backend environment values from `.env.example` and the [production runtime guide](PRODUCTION_RUNTIME.md); set `DEV_MODE=false`. Generate a stable Fernet encryption key, separate signing key, private operations token and OpenSandbox API key. Store secrets in the hosting secret manager. Preserve the encryption key in recovery storage; replacing it makes saved customer API keys unreadable.
3. Back up before schema changes. On an empty database, run `uv run python -m desktop_service.migrate` from `services/api`. For an existing MVP database, inspect and run the additive `desktop_service.upgrade` migration before starting services. These include desktop profile/template/job tables and revoke direct browser-role table access. They are not a complete versioned production migration framework; introduce one before further schema evolution. The backend must connect with a private role that can perform its required operations.
4. Review [compose.production.yaml](../compose.production.yaml) and [dedicated Linux preparation](PRODUCTION_RUNTIME.md). The scaffold builds API/web images, runs a singleton worker, keeps OpenSandbox private and requires gVisor `runsc`. Its host firewall and preflight are mandatory. It is not suitable for Docker Desktop or a shared personal server and has not been deployed or isolation-tested on a production host. Do not publish its Docker socket, VNC, execd, CDP or dynamically allocated desktop ports.
5. Build the desktop image for the chosen Linux host and set `DESKTOP_IMAGE` to the reviewed image. Run the maintenance/migration service, then API and one worker under the supplied supervisor pattern. Multiple API replicas may share Postgres; the worker takes an advisory lock. The worker also processes one durable clone/template job at a time, counting its helper against capacity.
6. Build the frontend with production Supabase values and development auth disabled. Leave `NEXT_PUBLIC_WS_URL` unset behind the same-origin Caddy proxy. Configure `APP_DOMAIN`, HTTPS and the production proxy rules. Validate readiness and private metrics before opening user traffic; see [operations](OPERATIONS.md).
7. Configure Stripe test prices ($29/month and $10 top-up), portal and signed webhooks using [billing setup](ACCOUNT_SETUP.md#stripe). Include delayed-payment completion events. Exercise initial purchase, renewal, failed payment, cancellation, duplicate/out-of-order delivery and top-up. Browser redirects never grant credits. Production Compose intentionally fixes `LAUNCH_ENABLED=false`; enabling it is a later reviewed launch change.
8. Select the actual platform network, token and treasury before enabling trials. The [EVM adapter](EVM_TRIAL_ADAPTER.md) and [generic trial contract](TRIAL_INTEGRATION.md) are implemented, but their existence does not establish compatibility with an unknown platform token. Verify wallet ownership, finalized transfers, historical balance and replay protection on the chosen network. Unknown/partial configuration must never request payment.

For configuration-only validation without printing expanded secrets:

```sh
docker compose -f compose.production.yaml config --quiet
```

## Runtime acceptance

- Run `scripts/smoke_desktop.py` against the reviewed image/runtime to check actual browser/display readiness, live viewing and restart persistence.
- Run `scripts/smoke_features.py` in an isolated development/staging configuration. It verifies real CPU/RAM enforcement, full clone isolation, template home exclusion and independent consumer snapshots. It intentionally refuses production mode and creates only its own fixtures. Adapt an equivalent staging acceptance flow before public rollout.
- Run `scripts/check_postgres.py` against a development/staging Postgres with schema-creation permission. It has passed real concurrent duplicate charging, final-credit contention, simultaneous trial redemption and advisory-lock handover. It creates and removes only its own randomized schema; it does not replace production load or failover testing.
- Run a real Anthropic BYOK task, including pause, human takeover, resume, an approval and reconnecting the browser. A configured or validated key alone does not prove task execution.
- Test concurrent users, stale workers, tenant isolation, token expiry and takeover revocation. From actual tenant desktops and an external host, perform every isolation check in [production runtime preparation](PRODUCTION_RUNTIME.md#required-isolation-acceptance-tests).

## Storage and recovery

CPU choices (1/2 cores), RAM choices (2/4 GiB), saved-computer limits and five private templates are implemented. They do not enforce disk quotas. The clone's 20 GiB size check is a copy safeguard, not a storage allocation.

- Enforce per-tenant home quotas and snapshot/clone storage limits using the chosen host/storage backend. Docker named volumes alone do not enforce them. Ensure disk exhaustion cannot take down the control plane.
- Follow [backup and recovery](BACKUPS.md). Local encrypted backup extraction and a disposable Postgres restore drill have passed. A complete desktop boot on replacement infrastructure remains untested.
- Configure scheduled encrypted **off-host** backups, retention, failure alerts and protected recovery keys. Include Postgres, OpenSandbox manager metadata, home volumes, system/template images and required configuration.
- Decide and implement cancellation retention before promising automatic deletion deadlines. A manual backup tool is not an automatic retention policy.

## Monitoring and operating controls

The local [Prometheus stack](OPERATIONS.md) has a healthy scrape, component readiness checks and alert rules. Deploy its equivalent on the private production control network, with a managed bearer secret and configured alert routing. Do not expose the local unauthenticated Prometheus UI publicly.

Add deployment-specific disk/capacity metrics, provider-spend budgets, rate limits, signup/abuse controls, redacted centralized logs and an on-call response process. Test alert delivery, host reboot ordering, restore procedures and service failure recovery. Set hosting spend alerts.

The $200–500 monthly infrastructure target has not been validated with a provider quote or load test. Pricing is an initial product assumption, not demonstrated unit economics. Remaining blockers are tracked in [ROADBLOCKS.md](../ROADBLOCKS.md).

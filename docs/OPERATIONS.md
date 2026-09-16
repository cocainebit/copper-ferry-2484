# Operations and monitoring

## Verified local state

On 2026-09-16, the local monitoring check returned:

- Prometheus target `host.docker.internal:8000`: **up**, with no scrape error.
- `up{job="agent-desktop"}`: **1**.
- `/health/ready`: database, worker and desktop runtime **true**.
- Prometheus active alerts: none.

These are point-in-time checks, not a promise of continuing availability. The initial `up` query may be empty until the first scrape completes (configured interval: 15 seconds). This monitoring stack is local; it does not mean production hosting or third-party integrations are live.

## Endpoints

| Endpoint | Purpose | Access |
|---|---|---|
| API `/health` | API process liveness | Public, minimal response |
| API `/health/ready` | Database query, recent worker heartbeat, OpenSandbox health response | Public, component booleans; HTTP 503 when unready |
| API `/internal/metrics` | Prometheus metrics | Server-held `OPS_TOKEN` bearer credential |
| `http://127.0.0.1:9098` | Local Prometheus UI and query API | Loopback only |

Readiness checks database connectivity, a worker heartbeat less than 30 seconds old, and the OpenSandbox manager's `/health` response. It does **not** boot a desktop or prove video streaming, gVisor enforcement, agent/provider access, OAuth, payments, backups, token validation or sufficient host capacity. Add a scheduled test-desktop workflow in the deployment environment for those end-to-end checks.

Production Caddy blocks `/api/internal/*` and `/internal/*` from external access. Keep metrics private even though its bearer authentication is independently enforced. Do not expose Prometheus directly to the public internet; its query API has no authentication in this local Compose setup.

## Local monitoring configuration

[compose.monitoring.yaml](../compose.monitoring.yaml) runs Prometheus with a read-only filesystem, a dedicated metrics volume and 14-day retention. [prometheus.yml](../infra/monitoring/prometheus.yml) scrapes the API every 15 seconds and reads a bearer credential from `/run/secrets/ops-token`. The host source file is `.local/ops-token`; its contents must match the API's `OPS_TOKEN` configuration. This credential is separate from application authentication, wallet keys and provider keys. Never print it in commands, screenshots, logs or Git.

The container runs as UID/GID `65534:65534` so its storage and mounted-secret permissions must permit that identity. On production Linux, provision the credential through a secret manager or a restricted group-readable mount; do not solve permission errors by making every secret world-readable. The local `.local` directory is ignored by Git.

```sh
# Starts only the separately named local monitoring stack.
docker compose -f compose.monitoring.yaml up -d
# Read-only status checks; no credentials appear in these URLs.
curl -fsS http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:9098/api/v1/targets
curl -fsS 'http://127.0.0.1:9098/api/v1/query?query=up%7Bjob%3D%22agent-desktop%22%7D'
```

The configured scrape target reaches the host API via `host.docker.internal`. For the production Compose topology, supply a separate deployment monitoring configuration on the private control network, with target `api:8000` and a managed secret. Do not expose a production API port just to reuse the local host target.

## Metrics and alert rules

Current metrics report worker heartbeat age, API uptime, computer counts by status, run counts by status and process-local HTTP response counts by status. HTTP counters and uptime reset when the API process restarts; aggregate them carefully if running multiple API replicas. Computer/run gauges omit status categories with no records, so absence of a category means zero, not a scrape failure. The `up` metric measures scrape success separately.

[alerts.yml](../infra/monitoring/alerts.yml) defines:

| Alert | Trigger |
|---|---|
| DesktopAPIUnavailable | Scrape is down for one minute |
| DesktopWorkerMissing | Worker heartbeat is missing or older than 30 seconds for one minute |
| DesktopProvisioningFailure | At least one failed desktop persists for five minutes |

Prometheus evaluates these rules, but **Alertmanager and notification delivery are not configured**. An alert in the UI does not notify an operator. Add an authenticated notification destination and a tested delivery path before public launch. Current rules also do not cover host disk exhaustion, quota breaches, certificate expiry, backup age, latency, payment failures or external provider outages; add these for the deployment's actual infrastructure.

## Troubleshooting

- **No `up` sample:** allow the first 15-second scrape, then inspect `/api/v1/targets`. Confirm the configuration loaded and the target exists.
- **Connection refused:** confirm API process and host port, Docker host routing, and the correct target for local versus containerized deployment.
- **401 scraping metrics:** the mounted credential and API `OPS_TOKEN` differ, or the credential file is unreadable. Check existence/permissions without printing the token; restart or reload the appropriate service after correcting configuration.
- **503 scraping metrics:** the API has no operations token configured, or its database is unavailable. Inspect server logs with credentials redacted.
- **Worker alert / readiness 503:** verify the worker is running against the same database as the API, review its logs and heartbeat writes, and check OpenSandbox health. Do not mark desktops running simply to silence an alert.
- **Prometheus exits with permission errors:** inspect ownership of the metrics volume and mounted configuration for UID 65534. Avoid deleting metrics data as a first response.
- **Desktop failure alert remains:** inspect the desktop's recorded error and manager/runtime logs. A failed desktop record may keep this alert active after infrastructure recovery until the computer is retried or removed.

## Production status boundaries

The production image builds and Compose/firewall scaffolding are documented in [PRODUCTION_RUNTIME.md](PRODUCTION_RUNTIME.md). A working local metrics scrape does not establish production isolation, autoscaling, on-call coverage, tested disaster recovery or enforcement of per-desktop storage quotas. Review [ROADBLOCKS.md](../ROADBLOCKS.md) and the backup documentation before enabling public customer access.

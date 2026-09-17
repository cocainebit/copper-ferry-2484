# Cubicle

Cubicle is the cloud-computer service for AI agents in the broader platform, with a live desktop viewer and a reusable token-holder trial service. The product name was confirmed by the owner on September 16, 2026; the broader platform name is still undecided.

**Status:** the local platform runs real Linux desktops with persistent home/system customization and PostgreSQL. A local Supabase stack supports tested email-code authentication. Resource controls, independent clones and private system templates are implemented; use the real integration checks below to verify the deployed runtime. Prepaid USDC/x402 invoices and a shared workspace balance are implemented, but real payments remain disabled until the rail is configured and validated. Anthropic, hosted OAuth/mail, the production payment rail and the actual platform token still need configuration and end-to-end validation; read [ROADBLOCKS.md](ROADBLOCKS.md) before deployment.

## What is here

- Dark, responsive landing page, workspace dashboard, live noVNC viewer with clipboard sync, task chat, approval cards, takeover controls, file browser/uploads/downloads, rename and an interactive administrator terminal.
- Scoped workspace API keys (read/control/manage), a public computer API (screenshot, click, drag, scroll, type, key, bash, files), a TypeScript SDK + CLI (`packages/cubicle`), a Python SDK (`sdks/python`) and an MCP server (`packages/cubicle-mcp`).
- Supabase Google/GitHub/email authentication, owner/member workspaces, invitation links, encrypted Anthropic BYOK.
- Durable agent runs and tool results, separate worker, pause/resume at tool boundaries, step/time limits and recent screenshot retention.
- OpenSandbox adapter with persistent home volumes, crash recovery by computer metadata, stop/restart, expiration renewal and deletion cleanup.
- Owner-controlled CPU/RAM profiles, durable full-desktop cloning, private system templates and independent computers created from templates.
- PostgreSQL storage, advisory-lock scheduling, concurrent credit metering checks, readiness endpoints and private Prometheus metrics.
- USDC/x402 v2 invoice checkout, EOA wallet authorization, independent settlement checks, durable reconciliation and a shared workspace ledger with idempotent per-service usage debits. The existing Stripe backend is retained for compatibility, but the product payment flow is crypto.
- Seven-day, service-scoped trials with wallet ownership challenges, exact-token verification, finalized historical holdings checks and replay protection. An EVM adapter is included; token/network/treasury configuration remains disabled until the actual platform token is known and chain tests pass.

## Repository layout

```text
apps/web/                   Next.js frontend
services/api/               FastAPI, database, billing, agent worker and tests
packages/platform-trials/   Shared token-trial TypeScript client
packages/platform-billing/  Shared x402 invoice and wallet-signing client
packages/cubicle/           TypeScript SDK and `cubicle` CLI for the computer API
packages/cubicle-mcp/       MCP server exposing computers as tools
sdks/python/                Python SDK (`pip install -e sdks/python`)
infra/desktop/              Linux desktop image, visible Chromium and VNC
infra/Caddyfile             Local same-origin HTTPS and WebSocket proxy
infra/production/          Dedicated-Linux/gVisor deployment scaffold
infra/monitoring/          Prometheus scrape and alert configuration
supabase/                  Local email authentication and templates
scripts/                   Startup, runtime checks, backups and restore drill
```

Customer guides: [getting started](docs/GETTING_STARTED.md), [customizing desktops](docs/CUSTOMIZING_DESKTOPS.md), [clones/templates/resources](docs/FEATURES.md), [accounts, AI provider and billing](docs/ACCOUNT_SETUP.md), and the [developer guide](docs/API.md) for API keys, the computer API, SDKs, CLI and MCP server.

Upstream fork: https://github.com/cocainebit/OpenSandbox. Keep it alongside this repository as `../OpenSandbox`. The Python SDK is pinned to commit `f7e32e5f4b1d77502db54ffdbb21eb7d7f57ce96`. The application is separate from the Apache-2.0 upstream fork.

## Local setup

Requires Node 22, Python 3.12, uv, and a working Docker engine for actual desktops.

```sh
npm ci
cd services/api
uv sync --frozen
```

Create `services/api/.env` for local use only:

```dotenv
DEV_MODE=true
DATABASE_URL=postgresql+psycopg://desktop:local-desktop-password@127.0.0.1:54329/desktop
PUBLIC_URL=http://localhost:3000
OPENSANDBOX_DOMAIN=localhost:8080
OPENSANDBOX_API_KEY=local-sandbox-key-not-for-production
LAUNCH_ENABLED=false
```

Create `apps/web/.env.local`:

```dotenv
NEXT_PUBLIC_DEV_MODE=true
API_INTERNAL_URL=http://127.0.0.1:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

From the repository root:

```sh
docker compose --profile build build desktop-image
docker compose up -d postgres opensandbox
sh scripts/dev.sh
```

Open **http://localhost:3000**. Local mode creates one development account with test credits and bypasses login when frontend Supabase values are absent. Never expose this mode publicly. Follow [local Supabase setup](docs/ACCOUNT_SETUP.md#local-authentication-without-a-cloud-account) to exercise real email-code sessions and the local mail inbox. The application Postgres database and Supabase Auth database are separate. API docs: http://localhost:8000/docs.

SQLite remains supported for isolated tests and lightweight frontend work; it is no longer the recommended full-stack development database. Existing SQLite installations should use the reviewed [migration utility](scripts/migrate_sqlite.py), retaining the original database and encryption key. Do not point a migration at a populated database without reviewing its safeguards.

## Verification

```sh
npm run build
npm run typecheck
npm run format:check
cd services/api
.venv/bin/ruff check --config pyproject.toml desktop_service tests
.venv/bin/python -m pytest -q
cd ../..
npx playwright install chromium --with-deps
npm run test:e2e
```

Browser tests start isolated servers on ports 3107 and 8107 with a temporary database. They do not touch the development workspace. After Docker is operational, verify the real integration:

```sh
cd services/api
.venv/bin/python ../../scripts/smoke_desktop.py
```

The desktop smoke test creates a dedicated disposable computer, checks screenshot capture, the live VNC handshake, visible Chromium and persistent files across restarts, then erases only that computer's files.

Additional integration checks, run from `services/api`:

```sh
.venv/bin/python ../../scripts/check_postgres.py
.venv/bin/python ../../scripts/smoke_features.py
```

The Postgres check creates and removes a unique temporary schema. It has passed real concurrent metering, replay protection, sequence and advisory-lock checks. The feature smoke test requires a running API/worker/OpenSandbox stack and development mode; it creates its own workspace, checks actual cgroup resource limits, clone isolation and template behavior, then deletes only its own desktops/templates. It retains database audit records. See the script output for runtime-specific results; unit tests alone do not establish copy or restore correctness.

## Deploying and integrating the main website

Use `.env.example`, [architecture](docs/ARCHITECTURE.md), [deployment checklist](docs/DEPLOYMENT.md), [production runtime scaffold](docs/PRODUCTION_RUNTIME.md), and [trial integration contract](docs/TRIAL_INTEGRATION.md). Run one scheduler, separate API/web services, a private OpenSandbox host and Postgres. Keep `LAUNCH_ENABLED=false` until the outstanding integration and infrastructure checks pass.

The broader website can share the same Supabase identity and workspace, and use `@platform/billing` for prepaid USDC invoices and `@platform/trials` for separate trial entitlements. Additional services register central prices and private service credentials to charge the shared balance. See [crypto payment integration](docs/CRYPTO_PAYMENTS.md) and [crypto operations](docs/CRYPTO_OPERATIONS.md). The default payment network is Base Sepolia testnet, disabled until configured; the production network and treasury are not yet selected. Our invoice flow requires the `extra.invoiceNonce` extension supported by the shared client and currently accepts EOA EIP-3009 wallets only. A single transfer buys one service trial; adding another service does not automatically grant access to it. Native wallet connection requires the selected chain's wallet adapter. No real token transfers have been requested or performed.

## Operations

- [Production Compose](compose.production.yaml) and [runtime preparation](docs/PRODUCTION_RUNTIME.md) describe the dedicated Linux host, gVisor, required firewall, private services and startup checks. This scaffold has not been deployed or security-certified on a production host.
- [Operations and monitoring guide](docs/OPERATIONS.md), [Prometheus configuration](infra/monitoring/prometheus.yml) and [alert rules](infra/monitoring/alerts.yml) cover private metrics/readiness. The local scrape is verified healthy. Production still needs a private collector, alert routing and on-call ownership.
- [Backup and recovery guide](docs/BACKUPS.md) and [backup tool](scripts/backup.py) stages encrypted restic backups of the database, manager metadata, home volumes and system images. Its maintenance workflow requires stopped desktops and a stopped API/worker. [Restore drill](scripts/restore_drill.py) has verified an extracted local backup against a fresh disposable database; it does not overwrite live data. A full desktop boot on replacement infrastructure remains untested. Protect the backup password and stable application encryption/signing keys separately.

Local backup tooling is not an off-host production backup policy. Enforced storage quotas, recurring encrypted off-host backups, a full desktop recovery exercise, production isolation testing and external-provider validation remain launch requirements.

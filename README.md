# Agent Desktop

A cloud-computer service for AI agents, with a live desktop viewer and a reusable token-holder trial service for a broader platform.

**Status:** the local platform runs real Linux desktops with live viewing, browser control and persistent home/system customization. Public checkout is disabled. Anthropic BYOK and external providers still need credentials; read [ROADBLOCKS.md](ROADBLOCKS.md) before deployment.

## What is here

- Dark, responsive landing page, workspace dashboard, live noVNC viewer, task chat, approval cards, takeover controls, file browser/downloads and terminal.
- Supabase Google/GitHub/email authentication, owner/member workspaces, invitation links, encrypted Anthropic BYOK.
- Durable agent runs and tool results, separate worker, pause/resume at tool boundaries, step/time limits and recent screenshot retention.
- OpenSandbox adapter with persistent home volumes, crash recovery by computer metadata, stop/restart, expiration renewal and deletion cleanup.
- Stripe subscription/top-up checkout, portal, signature-checked webhooks and idempotent minute metering.
- Seven-day, service-scoped trials with wallet ownership challenges, exact-token verification, finalized historical holdings checks and replay protection. The concrete blockchain adapter is deliberately unconfigured until the platform token is known.

## Repository layout

```text
apps/web/                   Next.js frontend
services/api/               FastAPI, database, billing, agent worker and tests
packages/platform-trials/   Shared TypeScript client for the main website
infra/desktop/              Linux desktop image, visible Chromium and VNC
infra/Caddyfile              Same-origin HTTPS and WebSocket reverse proxy
scripts/                    Local startup, isolated browser API, desktop smoke test
```

Customer guides: [getting started](docs/GETTING_STARTED.md) and [customizing desktops](docs/CUSTOMIZING_DESKTOPS.md).

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
DATABASE_URL=sqlite:///./.local/desktop.db
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
docker compose up -d opensandbox
sh scripts/dev.sh
```

Open **http://localhost:3000**. Local mode creates one development account with test credits and bypasses login. Never expose it publicly. For frontend/API work without Docker, start uvicorn and `npm run dev` separately; desktop creation will remain queued without a worker. API docs: http://localhost:8000/docs.

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

The smoke test creates a dedicated disposable computer, checks screenshot capture, the live VNC handshake, visible Chromium and persistent files across restarts, then erases that computer's files. It now passes on this machine, including readiness checks after restoring the system snapshot.

## Deploying and integrating the main website

Use `.env.example`, [architecture](docs/ARCHITECTURE.md), [deployment checklist](docs/DEPLOYMENT.md), and [trial integration contract](docs/TRIAL_INTEGRATION.md). Run one scheduler, separate API/web services, a private OpenSandbox host and Postgres. Keep `LAUNCH_ENABLED=false` until the outstanding integration and infrastructure checks pass.

The broader website can share the same Supabase identity and use `@platform/trials`. A single transfer buys one service trial; adding another service does not automatically grant access to it. Native wallet connection requires the selected chain's wallet adapter. No real token transfers have been requested or performed.

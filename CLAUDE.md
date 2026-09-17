# Cubicle (agent-desktop)

Orgo-style cloud Linux desktops for AI agents, running on OpenSandbox (`../OpenSandbox`).
Read `ROADBLOCKS.md`, `docs/COMPLETION_SPEC.md` (M1-M12) and `docs/ORGO_PARITY.md` (P1-P8)
before changing scope. Built by Codex 2026-09-15..17; Claude Code took over 2026-09-17.

## Who is working on what

Add your row before you write a file. Update it when you start, not when you finish.

| Who | Started | Working on | Files / area |
| --- | --- | --- | --- |
| Claude Code session d7672813 | 2026-09-17 11:45 | Took over from Codex. Finish storage tiers honestly, then P1 (terminal, clipboard, rename) and P3 (API keys, public computer API, SDK/CLI/MCP) | services/api, apps/web, packages, infra/desktop |
| Codex thread 01a0a734 | 2026-09-15 | HALTED (usage limit, resets 2026-09-22 19:34). Its goal auto-continues if resumed; do not resume without syncing with this table | whole repo |

## Ports (this repo owns these)

    3000   web (next dev)                 8000   API (uvicorn)
    8080   OpenSandbox server             54329  app Postgres
    8547   Anvil test chain               9098   Prometheus
    55321-55326  local Supabase (agent-desktop-auth)
    3107 / 8107  Playwright e2e servers (temporary)

`infra-postgres-1` on 54339 and `site-studio-*` containers are NOT this repo's.

## Rules

- Stop things by PID or by compose project (`docker compose -p agent-desktop ...`), never by pattern.
- Desktops are OpenSandbox sandboxes on the host Docker engine; `desktop-<id>` volumes are customer homes. Do not prune volumes by pattern.
- `OPENSANDBOX_API_KEY` in `infra/opensandbox.local.toml` is a local dev key only.
- Verify: `cd services/api && .venv/bin/python -m pytest -q`, `.venv/bin/ruff check --config pyproject.toml desktop_service tests`, `npm run typecheck`, `npm run format:check`.
- No em dashes in code, copy or commits.

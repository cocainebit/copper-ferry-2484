# Cubicle (agent-desktop)

Orgo-style cloud Linux desktops for AI agents, running on OpenSandbox (`../OpenSandbox`).
Read `ROADBLOCKS.md`, `docs/COMPLETION_SPEC.md` (M1-M12) and `docs/ORGO_PARITY.md` (P1-P8)
before changing scope. Built by Codex 2026-09-15..17; Claude Code took over 2026-09-17.

## Who is working on what

Add your row before you write a file. Update it when you start, not when you finish.

| Who | Started | Working on | Files / area |
| --- | --- | --- | --- |
| Claude Code session d7672813 | 2026-09-17 11:45 | Took over from Codex. DONE and live-verified: P1 controls, P3 developer platform, P4 templates/apps/secrets, P5 automations, P6 screens and audio, P8 fleet, plus runtime billing on the platform (hour blocks + passes) and the identity cutover (platform JWKS in security.identity, identity_link, browser PKCE sign-in). P7 Windows/GPU providers built but config-gated and unit-tested only (no KVM/GPU here). Token verification and account linking proven against the real platform with minted tokens (email and wallet-only). NEXT: browser sign-in once Cubicle is re-registered as a public client, real agent run (needs Anthropic key), prices for the hour and pass SKUs | services/api, apps/web, packages, sdks, infra/desktop |
| Codex thread 01a0a734 | 2026-09-15 | HALTED (usage limit, resets 2026-09-22 19:34). Its goal auto-continues if resumed; do not resume without syncing with this table | whole repo |

## Remotes

    origin   github.com/cocainebit/agent-desktop        private, the working backup
    public   github.com/cocainebit/copper-ferry-2484    PUBLIC mirror, random name on purpose

Anything pushed to `public` is world readable, including history. Scan before pushing there
(`git grep` for keys, and check `.env` files stay untracked); the only secret-shaped string in the
tree is Anvil's well-known test key in the local crypto smoke scripts.

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

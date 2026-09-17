# Developer guide: API keys, computer API, SDKs, CLI and MCP

Cubicle computers can be driven without the dashboard. This is the contract external agents, scripts, the CLI and the MCP server use. Everything here runs on the same authenticated API the dashboard uses; nothing bypasses workspace membership, credits or metering.

## API keys

Workspace owners create keys in **Settings > API keys** (or `POST /v1/workspaces/{id}/api-keys` from a signed-in session). A key:

- is shown once; only its SHA-256 hash is stored, and the list shows the `cbk_xxxxxxxx` prefix;
- acts as the member who created it, inside that one workspace only (`GET /v1/workspaces` returns just that workspace);
- carries scopes: `read` (always), `control` (drive a computer), `manage` (lifecycle and configuration);
- can expire (1 to 365 days) and can be revoked at any time; revoking the creator's membership closes every key they made;
- can never manage keys, the workspace's Anthropic credential, members, invitations, trials or payments. Those routes answer 403 to a key.

Send it as `Authorization: Bearer cbk_...`. A workspace holds at most 20 active keys.

| Scope | Allows |
| --- | --- |
| `read` | every `GET`: workspaces, computers, profile, files, download, events, runs, templates, jobs, entitlements |
| `control` | `screenshot`, `click`, `drag`, `scroll`, `type`, `key`, `bash`, `wait`, `terminal`, `upload`, `delete-file` |
| `manage` | create, `actions/{start,stop,take-control,resume}`, rename, delete, profile, clone, templates, built-in tasks and approvals |

## Who may drive a computer

A control call succeeds when the computer is running and either nobody has taken manual control and no built-in Claude task holds it, or the caller is the person currently in control. Otherwise it answers 409 with the reason. Control calls count as activity, so the idle timer and billing treat an API-driven session like a dashboard session. Each actor is limited to 10 control calls per second (burst 30) per computer; excess answers 429. That limiter is per API process; a multi-process deployment needs a shared one.

## Computer API

All routes are under `/v1/computers/{id}`. Bodies are JSON. Coordinates are pixels of the computer's configured resolution (see `GET /v1/computers/{id}`).

| Route | Body | Result |
| --- | --- | --- |
| `GET` | | status, controller, cpu, memory_gib, storage_gib, resolution, idle_timeout_minutes |
| `POST /screenshot` | | `{format:"png", width, height, image}` with base64 PNG |
| `POST /click` | `{x, y, button?: left/right/middle, count?: 1/2/3}` | `{ok}` (multi-clicks are left button only) |
| `POST /drag` | `{from:[x,y], to:[x,y]}` | `{ok}` |
| `POST /scroll` | `{x, y, direction?: up/down/left/right, amount?: 1..100}` | `{ok}` |
| `POST /type` | `{text}` (max 10,000 chars, Unicode safe) | `{ok}` |
| `POST /key` | `{key}` in xdotool syntax: `Return`, `ctrl+l`, `alt+F4` | `{ok}` |
| `POST /bash` | `{command}` (max 8,000 chars) | `{output, error, exit_code}`; output is kept when the command fails; runs as administrator, 45 s limit |
| `POST /wait` | `{seconds?: 0..10}` | `{ok}` |
| `GET /files?path=` | | `[{name, size, directory}]` inside Home |
| `GET /download?path=` | | `{name, data}` base64, 20 MiB limit |
| `POST /upload` | `{path, data}` base64, 20 MiB limit | `{name, size}` |
| `POST /delete-file` | `{path}` | `{name, deleted}` (files only, never Home) |
| `POST /runs` | `{prompt}` + `Idempotency-Key` | built-in Claude task (needs the workspace's Anthropic key) |
| `GET /events?after=` | | activity, agent and approval events |

Every input primitive accepts `screen` (0 is the primary display, 1-3 are extra screens); `POST /screenshot?screen=N` captures one display and reports its geometry.

Lifecycle: `POST /v1/workspaces/{id}/computers` (`name`, optional `cpu` 1/2, `memory_gib` 2/4, `storage_gib` 20/50/100, `resolution`, `idle_timeout_minutes`) with an `Idempotency-Key` header creates a stopped computer; `POST /v1/computers/{id}/actions/start|stop`, `PATCH /v1/computers/{id}` `{name}` renames, `DELETE /v1/computers/{id}?confirm=<name>` erases it. Creation and start answer 402 without credits or a trial and 409 at the saved or running computer limit.

Errors carry `{"detail": "..."}`. 401 means the key is invalid, expired or revoked; 403 means the scope or workspace does not allow the call.

### curl

```sh
export CUBICLE_API_URL=http://localhost:8000 CUBICLE_API_KEY=cbk_...
curl -s -H "Authorization: Bearer $CUBICLE_API_KEY" $CUBICLE_API_URL/v1/workspaces
curl -s -X POST -H "Authorization: Bearer $CUBICLE_API_KEY" -H 'Content-Type: application/json' \
  $CUBICLE_API_URL/v1/computers/$ID/click -d '{"x":640,"y":400}'
curl -s -X POST -H "Authorization: Bearer $CUBICLE_API_KEY" $CUBICLE_API_URL/v1/computers/$ID/screenshot \
  | python3 -c 'import sys,json,base64; open("shot.png","wb").write(base64.b64decode(json.load(sys.stdin)["image"]))'
```

## TypeScript SDK and CLI (`packages/cubicle`)

```ts
import { Cubicle } from "@cubicle/sdk";
const cube = new Cubicle({ baseUrl: process.env.CUBICLE_API_URL!, apiKey: process.env.CUBICLE_API_KEY! });
const [ws] = await cube.workspaces();
const c = await cube.create(ws.id, { name: "research", cpu: 2, memory_gib: 4 });
await cube.start(c.id);
await cube.waitFor(c.id);
await cube.key(c.id, "ctrl+l");
await cube.type(c.id, "https://example.com");
await cube.key(c.id, "Return");
const png = await cube.screenshotBytes(c.id);
console.log((await cube.bash(c.id, "ls ~")).output);
```

The CLI runs the same client (Node 22.18+ executes the TypeScript directly):

```sh
node packages/cubicle/cli.ts workspaces
node packages/cubicle/cli.ts create <workspace> "research" --cpu 2 --storage 50 --start
node packages/cubicle/cli.ts screenshot <computer> -o shot.png
node packages/cubicle/cli.ts click <computer> 640 400 --double
node packages/cubicle/cli.ts bash <computer> "apt list --installed | wc -l"
node packages/cubicle/cli.ts upload <computer> ./notes.md Documents/notes.md
```

`npm link --workspace packages/cubicle` installs it as `cubicle` on your PATH.

## Python SDK (`sdks/python`)

```sh
pip install -e sdks/python
```

```python
from cubicle import Cubicle
cube = Cubicle("http://localhost:8000", "cbk_...")
ws = cube.workspaces()[0]["id"]
c = cube.create(ws, "research", cpu=2, memory_gib=4)
cube.start(c["id"]); cube.wait_for(c["id"])
cube.key(c["id"], "ctrl+l"); cube.type(c["id"], "https://example.com"); cube.key(c["id"], "Return")
open("shot.png", "wb").write(cube.screenshot(c["id"]))
print(cube.bash(c["id"], "ls ~")["output"])
```

## MCP server (`packages/cubicle-mcp`)

A stdio MCP server exposing `list_computers`, `get_computer`, `start_computer`, `stop_computer`, `screenshot` (returned as an image), `click`, `type_text`, `press_key`, `scroll`, `drag`, `bash`, `wait`, `list_files`, `read_file` and `write_file`.

Claude Code:

```sh
claude mcp add cubicle -e CUBICLE_API_URL=http://localhost:8000 -e CUBICLE_API_KEY=cbk_... -- node /path/to/agent-desktop/packages/cubicle-mcp/server.ts
```

Claude Desktop or Cursor (`mcpServers` entry):

```json
{ "cubicle": { "command": "node", "args": ["/path/to/agent-desktop/packages/cubicle-mcp/server.ts"],
  "env": { "CUBICLE_API_URL": "http://localhost:8000", "CUBICLE_API_KEY": "cbk_..." } } }
```

Give the key `read` + `control` for driving an existing computer, add `manage` if the agent should start and stop computers itself.

## Bringing your own agent loop

The primitives map one to one onto Anthropic's computer-use tool actions (`screenshot`, `left_click`, `type`, `key`, `scroll`, `left_click_drag`) and a `bash` tool, so any computer-use harness can target a Cubicle computer by translating tool calls into these routes. The built-in Claude worker does exactly that inside the platform.

## Screens

`GET /v1/computers/{id}/screens` lists displays. `POST` with `{resolution}` adds one (up to four in total, `manage` scope); `DELETE /screens/{n}` removes it. Extra screens are persisted and recreated at every boot, each with its own window manager and viewer stream. Target them with `screen` on input calls, `?screen=N` on screenshots and app launches, and `?screen=N` on the dashboard viewer ticket.

## App catalog

`GET /v1/apps` is the catalog. `GET /v1/computers/{id}/apps` adds each app's install state and log tail. `POST /computers/{id}/apps/{app}/install` and `/remove` (`manage`) run the recipe detached; the worker mirrors progress, so poll the listing. `POST /apps/{app}/launch?screen=N` (`control`) opens an installed app on a display; `POST /apps/check` reconciles recorded state with the live system. Installed apps live in the system layer and survive stop/start, clones and templates.

## Template definitions

`GET /v1/template-starters` lists built-in specs. `POST /v1/workspaces/{id}/template-definitions` with `{name, spec}` and an `Idempotency-Key` publishes a spec: an identical spec returns the existing version (`built: false`), a changed spec builds the next version in a disposable helper. `GET /v1/templates/{id}` returns the spec, digest, build log and missing secrets; `POST /templates/{id}/rebuild` retries a failed build. Create computers from a ready version with `POST /v1/templates/{id}/computers`.

Spec fields: `apps` (catalog ids, prerequisites added automatically), `packages` (Debian), `files` (`{path, content, mode}`, absolute, outside Home), `run` (root build steps), `startup` (commands run at desktop login), `env` (non-secret variables), `requires_secrets` (names only), and default `cpu`, `memory_gib`, `storage_gib`, `resolution`, `idle_timeout_minutes`.

## Secrets

Owners manage workspace secrets in Settings or with a signed-in session (`PUT/DELETE /v1/workspaces/{id}/secrets/{NAME}`); API keys can list names but never write values. Values are encrypted at rest, written to tmpfs at every boot and sourced by login shells: the dashboard terminal, `POST /bash`, automation commands and the built-in agent's bash tool. `PUT /v1/computers/{id}/secrets` with `{names}` restricts which secrets a computer receives; `POST /secrets/refresh` re-injects into a running computer.

## Automations

`POST /v1/computers/{id}/automations` (`manage`):

```json
{ "name": "Morning report",
  "trigger": { "kind": "schedule", "cron": "0 9 * * mon-fri", "timezone": "America/Sao_Paulo" },
  "action": { "kind": "agent_task", "prompt": "Summarize yesterday's sales into ~/reports" },
  "start_if_stopped": true, "timeout_minutes": 30 }
```

Triggers: `schedule` (five-field cron, IANA zone, at most every 5 minutes), `interval` (`every_minutes` >= 5), `webhook`, `file` (`path` under Home created or changed), `process` (`process` stops). Actions: `command` (administrator shell, detached, output and exit status recorded), `agent_task`, `start`, `stop`. `POST /v1/automations/{id}/run` runs now; `GET /runs` is the execution history; `PATCH` with `{enabled}` pauses or resumes without replaying missed slots.

Webhook automations return `webhook_token` once. Call them without any other credentials:

```sh
curl -X POST -H "X-Cubicle-Token: cbh_..." -H "Idempotency-Key: delivery-42" $CUBICLE_API_URL/v1/hooks/<automation id>
```

A retry with the same `Idempotency-Key` returns the original execution. Hooks accept one call every 10 seconds and each automation at most 300 executions a day.

## Fleet

`GET /v1/workspaces/{id}/fleet?q=&status=&label=` returns plan limits, host capacity, metered minutes and credit spend over 24 hours (from the usage ledger) and every computer with OS, resources, labels, screens, automations and usage. `PUT /v1/computers/{id}/labels`, `POST /v1/workspaces/{id}/computers/bulk` with `{ids, action: start|stop|add_label|remove_label, label}` (per-item results) and `POST /v1/computers/{id}/move` with `{workspace_id}` (stopped computers, owner of both workspaces) manage many computers at once.

## Sound

The dashboard viewer's speaker button streams the desktop's audio. Programmatic clients use `POST /v1/computers/{id}/audio-ticket` and the `/v1/computers/{id}/audio?ticket=` websocket from an allowed origin: the first text frame describes the format (24 kHz mono signed 16-bit little-endian), then binary PCM frames follow. Nothing is captured unless someone listens.

## Operating systems and hardware

`GET /v1/platform/capabilities` lists operating systems and GPUs with availability, the reason when unavailable, and what each OS supports. Linux is always available. Windows (OpenSandbox's Windows profile, KVM hosts only) and GPUs (NVIDIA hosts only) appear once operators enable them; macOS is not offered because no Apple-hardware provider exists. Create with `os` and `gpu` on `POST /v1/workspaces/{id}/computers`; unavailable choices fail with 409 before anything is stored. Windows computers support the viewer and lifecycle automations only.

## Runtime billing

Cubicle bills runtime two ways, both as single payable actions on the Instance platform (SPEC v0.2: pay per action, no balance anywhere):

- **Hours.** A running computer is covered by a paid hour for its resource tier (`cubicle.hour.cpu2-mem4` and so on). A few minutes before the hour ends Cubicle asks the platform for the next charge and shows its payment link in the dashboard and in the computer's events. If that charge is unpaid when the hour ends, the computer stops and its files are kept.
- **Passes.** A day or monthly pass is one charge that covers every computer inside its limits for the period. It never renews itself; buying again extends from the current expiry.

`GET /v1/computers/{id}/runtime` reports `billing` (`platform` or `credits`), `covered_until`, `covered_by` (`pass` or `hour`), the next charge with its `pay_url`, and recent hours. `POST /v1/computers/{id}/runtime/hours` (owner, `manage` scope) opens the next hour's charge early so a payer can settle it before the desktop stops.

A person pays on the platform's payment sheet; an agent pays the same charge over x402 with no browser, using the charge's public payment URL. Charges are keyed by subject (`desktop:<computer id>:<hour start>`, `workspace:<id>:pass:<plan>:<key>`), so a retry never charges twice.

**When a SKU has no price, the action is free**: a deployment with no prices set runs normally and asks nobody to pay. When the platform is not configured at all, Cubicle falls back to its own per-minute credit ledger. If the platform is configured but unreachable or misconfigured, running computers keep running and say so; they are never failed or stopped because billing is down.

## Passes and pay as you go

On a deployment without the Instance platform, Cubicle bills from its own prepaid USDC credits:

- **Pay as you go.** Every minute a computer runs debits credits at the per-minute price. This is what an agent buying a few minutes uses.
- **Passes.** A day pass (24 h) or monthly pass (30 days) bought once with credits. While it is active, runtime on computers inside the pass costs nothing, and the plan's own limits apply (how many computers may run and be saved, the largest resource tier, whether GPUs are allowed). x402 cannot charge again on its own, so a pass never renews itself: buying again while one is active extends it from its current end date.

`GET /v1/plans` returns the catalog, each plan's limits, its price when the owner has set one (`for_sale`), and the per-minute rate. A plan without a configured price is listed but cannot be bought, and the dashboard says so rather than inventing a number. `POST /v1/workspaces/{id}/passes` with `{plan_id}` and an `Idempotency-Key` buys or extends (owner only, charged exactly once per key). `GET /v1/workspaces/{id}/pass` returns the active pass and recent history.

Minutes on a computer larger than the pass includes stay on per-minute billing. Every minute is recorded either way, so fleet usage stays truthful: covered minutes are stored at zero cost with the reason `included-in-pass`. When a pass expires, metering falls back to credits; with no credits left the computer stops.

Prices are set by the operator as SKUs (`cubicle-pass-day`, `cubicle-pass-month`) in `PLATFORM_SERVICE_PRICES`, in micro-USDC.

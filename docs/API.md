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
| `POST /bash` | `{command}` (max 8,000 chars) | `{output, error}`; runs as administrator, 45 s limit |
| `POST /wait` | `{seconds?: 0..10}` | `{ok}` |
| `GET /files?path=` | | `[{name, size, directory}]` inside Home |
| `GET /download?path=` | | `{name, data}` base64, 20 MiB limit |
| `POST /upload` | `{path, data}` base64, 20 MiB limit | `{name, size}` |
| `POST /delete-file` | `{path}` | `{name, deleted}` (files only, never Home) |
| `POST /runs` | `{prompt}` + `Idempotency-Key` | built-in Claude task (needs the workspace's Anthropic key) |
| `GET /events?after=` | | activity, agent and approval events |

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

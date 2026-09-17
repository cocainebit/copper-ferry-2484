# Cubicle: full Orgo parity and customization backlog

Audited September 17, 2026 against the current public Orgo site/documentation and Cubicle source. This is a **capability specification**, not a claim that Orgo was exercised with a paid account or that Cubicle is production-ready.

## Scope and evidence

The user's objective is a fully functioning Orgo-like platform with customization and addons. The Linux-first launch in [COMPLETION_SPEC.md](COMPLETION_SPEC.md) is an intermediate release. Its expansion exclusions do **not** remove capabilities from this broader objective. Required launch reliability, security, identity, payments and trial gates M1–M12 remain in force.

Official pages were retrieved successfully with Firecrawl. Source captures during this audit: `/tmp/cubicle-parity-orgo.md`, `/tmp/cubicle-parity-docs.md`, `/tmp/cubicle-parity-index.md`, `/tmp/cubicle-parity-full.md`. These are temporary research artifacts, not repository dependencies. The permanent citations below are the authoritative references; features and plan availability can change.

Cubicle evidence inspected: `services/api/desktop_service/{main,gateway,runtime,worker,features,feature_models}.py`, [FEATURES.md](FEATURES.md), [CUSTOMIZING_DESKTOPS.md](CUSTOMIZING_DESKTOPS.md), and [COMPLETION_SPEC.md](COMPLETION_SPEC.md). “Implemented” below means code exists; no new runtime acceptance test was performed for this audit. Concurrent implementation should update each row only after verification.

## Capability matrix

| Area | Official Orgo capability / evidence | Cubicle baseline and remaining requirement |
| --- | --- | --- |
| Live computer | Browser desktop, terminal, files and persistent environment. [Introduction](https://docs.orgo.ai/introduction) | Linux desktop and authenticated noVNC gateway exist; clipboard sync (both directions) and rename are in the viewer. Verify public reconnect, sustained operation and revocation under load. |
| OS selection | Linux and Windows are advertised; Mac is closed beta. Enterprise hardware fleets are offered. [Product](https://www.orgo.ai/) | Linux container only. Add VM/provider abstraction, Windows images/licensing/guest control, then Mac hardware-backed adapter and availability rules. Do not add selectable OS options without a working provider. |
| CPU/RAM capacity | Create supports plan-bounded sizes, with a documented effective ceiling of 4 vCPU/64 GB per computer. [Instance types](https://docs.orgo.ai/guides/instance-types) | Only 1/2 vCPU and 2/4 GiB presently. Need capacity catalog, admission, reservation, measured enforcement and resource-dependent prices before larger allocations. |
| Resize/storage/network | Live CPU, bandwidth and disk growth; memory changes restart and replace connection credentials. [Resize](https://docs.orgo.ai/api-reference/computers/resize) | CPU/RAM edits require stop. 20/50/100 GiB storage tiers exist and report `storage_quota_enforced` truthfully (Docker: copy bound only; Kubernetes: claim size). No live resize, disk growth or bandwidth setting yet. |
| Always-on/idle policy | Idle timeout is configurable; zero disables it. [Resize](https://docs.orgo.ai/api-reference/computers/resize) | Persisted 0–1440 minute policy implemented with default 15; zero disables idle stop. Creation/settings and clone/template inheritance preserve the choice. Reconcile tests verify continued metering and credit-exhaustion stop without dashboard activity. Production soak acceptance remains. |
| Resolution/multiple screens | Screen lifecycle supports up to four displays and screen-targeted input. [Screens](https://docs.orgo.ai/api-reference/screens/create) | Three resolution presets are implemented (see the display update below). Per-screen view/control and screen-specific agent coordinates remain. |
| Clones/persistence | Disk and installed software survive stop/start; normal stop/start does not preserve processes. [Instance types](https://docs.orgo.ai/guides/instance-types), [Clone](https://docs.orgo.ai/api-reference/computers/clone) | Homes, system snapshots and full clones exist. Prove interruption recovery, independent copies, deleted-source survival and billable lifecycle correctness. |
| Template registry | Immutable versioned definitions, build status/logs, curated catalog and custom templates. [Templates](https://docs.orgo.ai/guides/templates/introduction) | Private system snapshot templates only; no declarative registry, immutable versions or catalog. Build reproducible install recipes, digest/version records, durable build jobs and launch validation. |
| Apps/addons | Templates declare package installs, files, environment, supervised apps, health, hooks, terminal sessions, egress and streaming. [Schema](https://docs.orgo.ai/guides/templates/schema) | Manual shell installation is possible. Need installable app profiles, lifecycle status, compatible versions, health/restart policies, uninstall semantics and visible installation errors. |
| Secrets | Named vault secrets are injected per launch, outside the shared template snapshot. [Secrets](https://docs.orgo.ai/guides/templates/secrets) | Encrypted Anthropic credential exists; general named secret vault and template injection do not. Add permissions, rotation, redaction, explicit secret requirements and snapshot-leak tests. |
| Automation/triggers | Scheduled and file/HTTP/process/metric/log/custom/desktop event triggers. [Triggers](https://docs.orgo.ai/guides/templates/triggers) | No managed trigger service. Need persisted schedules, deduplication, bounded executions, logs, retries and pause/delete behavior across restart. |
| Public computer API | Lifecycle plus screenshot/click/drag/type/key/scroll/wait/bash/exec operations. [API index](https://docs.orgo.ai/llms.txt) | Implemented locally: `screenshot`, `click`, `drag`, `scroll`, `type`, `key`, `bash`, `wait`, files and lifecycle under `/v1/computers/{id}` with an operator rule (manual control and built-in tasks win), per-actor rate limit and unit tests ([developer guide](API.md)). Runtime acceptance against a live desktop and a shared limiter for multi-process deployments remain. |
| API credentials | User-generated account/workspace API keys, scope and rotation. [Authentication](https://docs.orgo.ai/api-reference/authentication) | Implemented locally: hashed workspace keys with one-time reveal, read/control/manage scopes enforced per route, expiry, revocation, last-used tracking, session-only management and a settings card. Per-key audit history beyond activity events remains. |
| Developer clients | REST, Python/TypeScript SDKs, CLI and MCP. [Introduction](https://docs.orgo.ai/introduction), [CLI](https://docs.orgo.ai/guides/cli), [MCP](https://docs.orgo.ai/guides/mcp) | Implemented locally: TypeScript SDK + `cubicle` CLI (`packages/cubicle`), Python SDK (`sdks/python`) and a stdio MCP server (`packages/cubicle-mcp`) on the same contract. They typecheck and import; a third-party agent run against a live desktop without the dashboard is the remaining acceptance step. |
| Interactive terminal | Persistent interactive PTY connection, including CLI shell access. [Terminal](https://docs.orgo.ai/api-reference/computers/terminal) | Implemented locally: token-guarded PTY server injected at boot, `/pty` websocket relay bound to the control grant (revocation closes it), xterm.js tab with resize. Browser verification against a live desktop is pending (Docker outage during the run). |
| Audio/events | Speaker stream and desktop focus/clipboard/files/process/idle events. [Audio](https://docs.orgo.ai/api-reference/computers/audio), [Events](https://docs.orgo.ai/api-reference/computers/events) | No audio pipeline; Cubicle activity records are not guest OS events. Add authenticated opt-in audio and bounded event subscriptions with reconnect/backpressure. |
| Files | Upload, export, list, download and delete APIs. [File API index](https://docs.orgo.ai/llms.txt) | Authenticated 20 MiB upload, listing, home download and controller-only file deletion now exist with safe path checks. Add binary streaming/export, quotas, progress and partial-transfer recovery. |
| Embedded desktop | Integration guide for live screen embedding. [Embed](https://docs.orgo.ai/guides/embed-vms) | Dashboard uses an internal viewer ticket and a single permitted origin. Add a documented embed component with short-lived scoped tickets, approved origins and control/read-only modes. |
| Agent/model choice | Multiple model providers and external agent frameworks; chat endpoint and stored transcripts. [Models](https://docs.orgo.ai/guides/models), [Chat](https://docs.orgo.ai/api-reference/chat/completions), [Threads](https://docs.orgo.ai/api-reference/chat/threads) | Built-in Anthropic loop only, not yet verified with a real provider. Add provider-neutral adapter contracts, model capabilities, cost budgets, replay-safe tool handling and durable sessions. |
| Hosted agent apps | Guides and curated configurations for external agents. [OpenClaw](https://docs.orgo.ai/guides/openclaw), [Hermes](https://docs.orgo.ai/guides/hermes) | Users can install software manually. Provide tested app profiles with separate secret scopes, health, lifecycle and upgrade/rollback procedures. |
| Fleet/workspaces | Team/project scopes, computer movement and account capacity management. [Move](https://docs.orgo.ai/api-reference/computers/move), [Instance types](https://docs.orgo.ai/guides/instance-types) | Workspace membership exists, but saved/running limits are tiny and worker is singleton. Need quotas by entitlement, safe moves, search/filter/bulk management and capacity-aware multi-host scheduling. |
| Collaborative canvas | Advertised on paid plans. [Product](https://www.orgo.ai/) | No canvas. Define and implement shared fleet layout/presence with access control and conflict handling; exact Orgo interactions require authenticated observation. |
| Customer telemetry/backups | Dashboard guide mentions system metrics, hardware controls and backups. [Quickstart](https://docs.orgo.ai/quickstart) | Operator metrics and backup tooling exist. Add per-computer usage/history, customer-visible backup state and supported restore workflow; verify retention and billing effects. Exact Orgo retention is not established here. |
| Enterprise placement/GPU | Dedicated/on-prem and GPU/hardware fleets are advertised. [Product](https://www.orgo.ai/) | No provider for these. Keep within the full roadmap; require real hardware inventory, drivers, isolation and operational acceptance. Availability in a schema alone is insufficient proof of deliverability. |
| Payments/trials | Cubicle intentionally uses crypto/x402 and its platform-token trial. | Complete M5/M6 with live integration evidence. Matching Orgo's card billing or exact prices is not required by the user's chosen payment design. |

## Evidence qualifications: do not copy documentation contradictions into promises

- The instance guide lists `macos` and `android` as accepted OS values, but the product page only establishes Windows availability and a Mac beta. Android availability needs runtime/account verification. Schema acceptance is not a working operating system.
- The template schema includes GPU and region fields, while public offerings condition hardware on availability/enterprise arrangements. GPU choices must remain unavailable until a real eligible host can fulfill them.
- Orgo's general introduction describes desktop-session persistence, while the instance guide explicitly says ordinary stop/start loses running processes. Its template guide separately describes full-state golden snapshots. Cubicle should specify disk persistence, process resumption and template build semantics separately; generic snapshot support does not prove memory resume.
- Orgo advertises very fast boots. A Cubicle SLA requires fresh-host and warm-host measurements at supported concurrency; do not claim parity from an unmeasured UI transition.
- Copy functional behavior and supported contracts, not Orgo's branding or proprietary assets. Cubicle remains its own product and infrastructure.

## Delivery milestones beyond the Linux-first launch

These milestones extend M1–M12, rather than replacing their security and production gates. Order reflects dependencies, not a claim that one turn can deliver the whole platform.

### P1 — Complete everyday desktop controls

Resolution, file upload/download/delete, clipboard, configurable idle policy, interactive terminal, name/lifecycle UX and effective resource display. Acceptance: a new user completes all controls, reconnects, stops/starts and verifies retained files/preferences; another workspace cannot access any route or stream.

### P2 — Enforced resource and addon capacity

CPU/RAM/disk/bandwidth catalog, workspace reservations, customer limits, prices, capacity addons, usage graphs and grow/resize jobs. Acceptance: host measurements match sold resources; concurrent requests cannot oversubscribe reservations; full disks and exhausted balance fail predictably; charges reflect actual effective hardware.

### P3 — Developer platform

Scoped customer API keys; full control primitives; Python/TS desktop SDKs; CLI/MCP; embed package; documented errors/versioning. Acceptance: an independently configured external client provisions, controls, transfers files and deletes a computer without browser-session credentials; key revocation closes access promptly.

### P4 — Templates, apps and secrets

Versioned definitions, schema validation, isolated builds/logs, curated app catalog, per-launch secrets, health and lifecycle hooks. Acceptance: identical definitions produce reproducible environments, failed builds are recoverable, templates never carry customer secrets, and one-click app installation is verified on a fresh computer.

### P5 — Agents and reactive automation

Real provider acceptance, multiple provider adapters, durable threads, scheduled/event tasks, budgets, approvals/takeover and background agent services. Acceptance: real tasks finish after the browser disconnects; restart does not repeat uncertain side effects; cancellation stops work and metering; missing credentials produce actionable errors.

### P6 — Rich display and collaboration

Multiple independent screens, authenticated audio/guest events, shared canvas/presence and scoped embedding. Acceptance: two authorized agents can use separate displays without pointer interference; subscribers cannot see another tenant; resize/reconnect and backpressure work under load.

### P7 — Multi-OS and hardware providers

Windows, Mac-compatible hosting, GPU inventory and placement abstraction; investigate Android availability separately. Acceptance: each advertised option provisions the actual OS/hardware, preserves data, supports control/files/lifecycle, enforces isolation and has measured cost/capacity. Do not use Linux containers as a cosmetic stand-in.

### P8 — Fleet operations and complete release acceptance

Multi-host admission, team/fleet management, dedicated deployment options, customer restore, delivered alerts, documentation, support and launch drills. Acceptance combines P1–P7 with M1–M12 and records deployed-version evidence for every supported capability. A successful local unit suite alone cannot close this milestone.

## Immediate actionable work and external dependencies

Independent local work can proceed on P1, P3 API contracts, P4 definitions/vault design, and orchestration tests. Larger hardware allocations require confirmed host capacity; Windows/Mac/GPU need eligible infrastructure. Agent execution requires an authorized provider key. Public identity/domain, live crypto treasury/RPC/gas funding, trial-token parameters and main-site integration still require the inputs listed in [ROADBLOCKS](../ROADBLOCKS.md).

Track every row as `missing`, `implemented locally`, `runtime verified`, or `production accepted`, with a test artifact and version. Unverified beta/marketing capabilities remain discovery items, never silently discarded or represented as delivered.

## Implementation update: display presets

Creation and stopped-desktop settings now persist 1280×720, 1440×900 or 1920×1080; clones/templates preserve resolution and template consumers can override it. Runtime passes the setting to Xvfb, verifies geometry and supplies corresponding agent dimensions. Seven browser tests and actual X display probes for all three presets pass. Arbitrary live resize and multiple displays remain open.

## Implementation update: P1 controls and P3 developer platform (September 17, 2026)

- P1: interactive PTY terminal, clipboard sync, rename, storage tiers and file upload/delete are implemented locally. Remaining for P1 acceptance: browser verification of the terminal on a live desktop and a reconnect/revocation pass under load.
- P3: scoped API keys, the public computer API, TypeScript SDK + CLI, Python SDK and MCP server are implemented locally with 208 backend tests. Remaining: run a third-party agent (for example Claude Code through the MCP server) against a live desktop end to end, add a shared rate limiter for multi-process deployments and per-key audit history.

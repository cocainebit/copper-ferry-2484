# Cubicle — completion and launch specification

Updated: September 17, 2026. Status is based on repository implementation and recorded local verification, not an audit of a deployed production service.

The broader full-replica objective is tracked in [ORGO_PARITY.md](ORGO_PARITY.md). This specification defines an intermediate production v1; its expansion section does not remove requirements from the broader goal.

## 1. Definition of complete

Cubicle is a hosted Linux computer service for people and AI agents, integrated with a broader platform's identity, crypto credit balance and token-gated trials. A customer can sign in, pay or qualify for a trial, configure a computer, use its live desktop, delegate a task, take control, save their work, return later, and recover from documented failures. Operators can account for every charge, enforce tenant boundaries, restore data and support customers.

**Production v1 is complete when all launch milestones M1–M12 meet their acceptance criteria in the intended hosting environment.** A working local demonstration, passing unit tests, or a configured third-party account alone does not meet that standard. Optional expansion work is listed separately; “fully customizable” needs explicit supported boundaries.

### Supported v1 scope

- Linux desktops; live screen viewing and keyboard/mouse control; browser, terminal and file transfer.
- Configurable name, approved CPU/RAM/storage tiers, display resolution, appearance and installed applications; private system templates and full clones.
- Persistent home data and saved system changes, with documented stop/start and backup semantics. No promise to restore live RAM or running processes.
- One initial agent provider, real task execution, streaming status, cancellation and manual takeover.
- Workspace accounts, roles, shared platform identity and per-service entitlements.
- Prepaid crypto credits through x402; initial proposed payment rail is native USDC on Base, pending activation review. Payment asset and platform trial token are separate concepts.
- A reusable seven-day token trial for each service, with a bounded usage allowance.
- Explicit capacity, security, recovery and support guarantees supported by evidence.

### Current baseline

| Area | Existing evidence | Remaining distinction |
| --- | --- | --- |
| Desktop runtime | Local live desktops, persistence, clones, templates and actual CPU/RAM limits verified | Hardened production host, storage limits and complete customization UX remain |
| Identity/database | Local Supabase email auth and Postgres isolation/concurrency checks | Production identity, email/OAuth and main-site SSO remain |
| Agent | Implementation and simulated lifecycle tests | No configured Anthropic key; real task acceptance remains |
| Payments | Shared ledger, x402 checkout, settlement/recovery and real signatures against local test chain | Live network, treasury, gas funding and production reconciliation remain |
| Token trial | Framework and optional EVM verification adapter | Actual token/chain and end-to-end live-chain validation remain |
| Operations | Local metrics, encrypted backup checks and container builds | Off-host recovery, deployed alerts, load/security acceptance remain |
| Creation dialog | CPU/RAM/template creation controls implemented; backend and browser checks pass | Production resource and storage acceptance still belongs to M2 |

Historical verification is recorded in [ROADBLOCKS](../ROADBLOCKS.md). Do not translate test counts into a completion percentage.

## 2. Milestones and acceptance criteria

### M1 — Product, platform and deployment contract

**Decided September 17, 2026:** the platform is **Instance** (instanceOS); Cubicle is its cloud-computer service, alongside Floatlane and Plotform. Billing sells a day pass and a monthly pass (unlimited runtime inside plan limits, no auto-renewal) next to per-minute pay as you go. Domain, hosting, the actual prices, trial token and treasury remain open.

**Deliver:** a checked-in launch configuration matrix defining main-platform name/domain, Cubicle subdomain, shared identity ownership, service identifier, supported regions, initial payment network, trial token, capacity limits, pricing, data retention and support contact. Keep existing `agent-desktop` identifiers compatible where already persisted.

- Define saved/running desktop limits separately; decide owner/member permissions for creation, settings, billing, agent credentials and deletion.
- Review the provisional ~0.20 USDC/hour price against compute, storage, snapshots, bandwidth, agent and payment costs. Define resource-tier prices and rounding; reject unsupported configurations.
- State whether users supply agent keys or buy model usage through platform credits. Current trial proposal uses customer keys.
- Record payment/trial failure and refund policies before accepting customer funds.

**Done when:** a single environment/configuration matrix is approved and validation rejects missing production-critical settings. No invented token address, price, domain or treasury is deployed.

**Dependencies:** business/product choices and access to the main website repository.

### M2 — Complete desktop customization and lifecycle

**Deliver:** one consistent creation/settings experience backed by enforced runtime configuration.

| Control | Required v1 behavior |
| --- | --- |
| Name and environment | Name validation; clean Linux or ready private template; permissions enforced server-side |
| CPU/RAM | Initially 1/2 cores and 2/4 GiB; defaults visible; selected values persist atomically and reach runtime; changes require stop |
| Storage | Select from operator-defined tiers; hard home/snapshot limits, usage display, low-space handling; no cosmetic quota |
| Display | Supported resolution choices, resize/reconnect handling, fullscreen and usable scaling; three resolution presets implemented; production reconnect acceptance remains |
| Appearance/apps | Document and expose access to desktop appearance settings and app installation; preferences survive stop/start |
| Templates/clones | Explain system-only templates versus full clones; progress/error/retry states, ownership and quota checks |
| Lifecycle | Create/start/stop/restart/rename/delete; clear status, guarded destructive actions, truthful errors and safe reconnect |

- Make resource prices/capacity visible before creation if they affect charges. Never silently substitute hardware.
- Preserve files, permissions and browser preferences; explain system snapshot timing and unsaved-change risks.
- Add upload/download limits and clear file-transfer errors; verify manual control, clipboard and supported keyboard shortcuts.
- Keep instance access bound to an authenticated workspace session; remove access on membership revocation.

**Done when:** browser tests create each supported resource combination, verify actual runtime limits and disk exhaustion behavior, change preferences/install an app, stop/start, clone/template, reconnect and delete without crossing tenant boundaries. Interrupted creation/copy operations terminate in recoverable states without orphaned billable resources.

**Dependencies:** M1 capacity/pricing; M7 isolation; M8 lifecycle recovery. Creation-time CPU/RAM/template work is the immediate increment, not the whole milestone.

### M3 — Production identity and shared platform accounts

**Deliver:** production Supabase configuration, verified email sign-in/recovery, chosen OAuth providers, reliable SMTP, workspace invitations/roles and main-site/Cubicle shared account mapping.

- Define cross-subdomain sign-in and logout using verified issuer/audience/session rules; never trust a user/workspace ID supplied by the browser.
- Cover expired sessions, revoked invites, removed members, account recovery and workspace ownership transfer.
- Provide account export/deletion and retention behavior; preserve required financial audit records under the approved policy.
- Disable local preview/dev authentication in public deployments.

**Done when:** a new customer signs up on the main website and reaches the same Cubicle account; invitation, role restrictions, logout/revocation and recovery work on actual domains. Another account cannot access desktops, files, credentials, credits or trial records.

**Dependencies:** M1 domains/main-site repository; external identity and email credentials.

### M4 — Real autonomous agent operation

**Deliver:** real provider integration with encrypted key storage, task progress/tool history, pause/cancel/resume and reliable manual takeover.

- Execute browser, terminal and file tasks; recover cleanly from provider timeouts, exhausted budget, desktop disconnect and worker restart.
- Set task time/tool/token budgets and expose model cost responsibility. Never log credentials or replay uncertain irreversible actions automatically.
- Describe approval limits honestly: current model-mediated approvals are not a hard security boundary. For v1, either enforce protected actions outside the model or explicitly ship an unrestricted agent with clear user consent; do not advertise guaranteed action approval without enforcement.

**Done when:** production-like tests complete (1) browser research saved to a file, (2) a small webpage built and opened, (3) file organization, plus cancellation, takeover and failure recovery with a real provider. Task history and charges remain accurate after interruption.

**Dependencies:** M2, M3, M7; authorized provider key and chosen usage policy.

### M5 — Production x402 payments and shared credits

**Deliver:** deployed private facilitator, treasury address, funded gas signer, reliable RPC, reviewed confirmation/reorganization policy and working public checkout.

- Keep signer secrets separate from the public API; restrict facilitator access. Validate settlement independently before crediting.
- Complete Base Sepolia testing, then an explicitly authorized small mainnet acceptance transaction before public activation.
- Handle duplicate submissions, lost settlement responses, stale invoices, invalid signatures, wrong chain/asset/amount/recipient, reorganization and RPC outage. Credit each accepted payment exactly once; make uncertain states visible and reconcile them.
- Document current EOA/EIP-3009 and invoice-nonce client requirements. Unsupported wallets must get an actionable error.
- Finish balance/receipt/history/support UX; define refunds and audited operator adjustments. Gas costs and non-refundable network fees must be clear.
- Integrate the main website and each actual service with scoped server credentials, server-owned prices and idempotent usage records. Stop paid work when available balance is exhausted; reconcile reserved/in-flight work.

**Done when:** the same authenticated account purchases credit, spends it in Cubicle and one other integrated service, and receives an exact auditable balance. Concurrent charges cannot overspend; failure/recovery tests cannot lose or duplicate credit. Alerts detect gas exhaustion and settlement backlogs.

**Dependencies:** M1, M3, M8; treasury, RPC, funded signer and other service repository access. Existing local-chain evidence does not satisfy live-chain acceptance.

### M6 — One-token, seven-day service trials

**Deliver:** selected chain adapter and main-site wallet flow: prove wallet ownership, create a service-specific intent, send exactly one native platform token, verify confirmed transfer and holdings, activate bounded entitlement.

- Confirm the holdings policy: current implementation proposal checks **at least 10,000 tokens remaining after transfer**, generally requiring 10,001 beforehand plus chain gas. This needs explicit product approval; it is not continuous locking.
- One trial per wallet **and** platform user per service; prevent replay and concurrent double activation. A payment for one service cannot activate another.
- Define trial start time, seven-day expiry, included hours, paused/running behavior at expiry and conversion to paid credits. Current proposal: ten desktop-hours, one saved/running computer, customer agent key.
- Handle wrong amount/token/network/treasury, insufficient holdings, ambiguous chain ordering, delayed finality and abandoned intents; publish a reconciliation/refund path.

**Done when:** actual selected-network tests cover eligible/ineligible holders, duplicates, concurrent redemption, expiry and two different services. The UI never invites payment when verification is unconfigured or unavailable.

**Dependencies:** M1, M3, M5 shared accounts, actual token/network/treasury. EVM code does not cover an unspecified non-EVM network.

### M7 — Production tenant isolation and abuse controls

**Deliver:** dedicated Linux runtime with tested gVisor/hardened execution, restricted management network, authenticated desktop gateway, scoped service secrets and enforced quotas.

- Test browser sandbox compatibility without development bypasses; block cloud metadata and unauthorized private/control-plane access.
- Prevent privileged containers, host socket/mount access and direct public desktop/management ports.
- Enforce CPU, RAM, process, disk, snapshot and network abuse limits. Rate-limit auth, creation, agent tasks, trial verification and payment endpoints.
- Exercise origin/session handling for live connections, secret redaction and credential rotation; scan dependencies/images and resolve launch-critical findings.

**Done when:** documented adversarial tests cannot access another tenant or host/control-plane resources; exhaustion affects only the offender. Public configuration fails closed if dev auth or required isolation is missing.

**Dependencies:** M1 quotas; production Linux host. This is a public-launch blocker even for a small beta.

### M8 — Durable orchestration, accounting and capacity

**Deliver:** lifecycle/job recovery, versioned database migrations, deliberate capacity admission, idempotent financial operations and safe deployment/restart behavior.

- Define initial single-host capacity and reject/queue excess requests transparently; multiple hosts are only required if the chosen launch capacity demands them.
- Recover stale leases and reconcile database/runtime state; clean orphan desktops, snapshots and volumes without deleting valid customer data.
- Define billing start/stop boundaries, rounding, failed-start treatment, resource changes and agent charges. Meter billable time independently of the browser connection.
- Add migration upgrade/rollback or documented forward-repair procedures; remove production reliance on ad hoc startup schema changes.

**Done when:** kill/restart tests during start, stop, copy, agent action and payment settlement yield correct states and charges; last-credit races cannot overspend. A deployment and migration complete without unexplained data loss or duplicate work.

**Dependencies:** M1 pricing/capacity; M2/M4/M5 integration.

### M9 — Backups, retention and disaster recovery

**Deliver:** automated encrypted off-host database/home/system-snapshot backups, retention, integrity checks, protected keys, deletion handling and a fresh-host restore runbook.

- Agree RPO (maximum acceptable lost work) and RTO (maximum restoration time) before launch. Proposed starting targets: RPO ≤24 hours for backed-up persistent data and RTO ≤4 hours; benchmark feasibility before promising them.
- Document the separate risk of unsaved system changes and live memory. If shorter recovery targets are needed, build the required snapshot/replication strategy.
- Separate customer deletion, backup expiry and financial-record retention; verify backup failure alerts.

**Done when:** restore a representative workspace onto a clean host, including identity mapping, credits, homes and system snapshots, then start its desktop and verify contents within the approved targets. A database-only restore is insufficient.

**Dependencies:** M7, M8; off-host storage and key custody.

### M10 — Public deployment and operational ownership

**Deliver:** domain/DNS/TLS, production frontend/API/runtime/payment workers/Postgres/identity, secret storage, CI/CD, health checks, dashboards, delivered alerts and rollback instructions.

- Keep development/test funds and databases separate from production.
- Monitor desktop startup failures, job lag, runtime capacity, storage, provider errors, payment reconciliation, signer gas, backup freshness and suspicious usage.
- Define operator access, incident severity, on-call contact, support channel and maintenance procedure.
- Publish the application repository to the approved destination with secret scanning and a reviewed license/dependency inventory.

**Done when:** a tagged release deploys reproducibly from a clean environment, public TLS/redirects work, failed dependency health is visible, a test alert reaches its operator, and rollback is demonstrated.

**Dependencies:** M1, M3, M7–M9; hosting/domain/provider access.

### M11 — Complete customer and developer documentation

**Deliver:** public getting-started guide, customization/persistence guide, agent-key/task guide, payment/wallet troubleshooting, trial rules, API/SDK examples, service-integration guide and operator runbooks.

- Publish exact supported hardware, OS, wallet/network and feature limits. Explain template/clone secrets and snapshot semantics.
- Document authentication, authorization, errors, idempotency, asynchronous job states and x402 client compatibility with runnable examples.
- Supply reviewed pricing, terms, privacy, retention and refund/support information before accepting public customers. x402 is a technical payment rail, not a substitute for operating policies.

**Done when:** a new tester can sign up, pay/redeem a trial, configure a desktop, run a task and recover from common errors using the docs; an external developer can integrate a second service without undocumented steps.

**Dependencies:** final M1–M6 behavior. Draft throughout implementation, not only at the end.

### M12 — Integrated acceptance, private beta and public launch

**Deliver:** reproducible staging acceptance suite, load report, security review, failure drills and a release checklist tied to evidence.

- Test complete fresh-user paid and trial journeys on deployed domains with real runtime/provider/testnet integrations.
- Test supported browsers, keyboard accessibility, clear loading/error states and narrow-screen dashboard use. Define touch desktop-control support explicitly.
- Set a measured concurrent-desktop target N for the launch host. At N, run an 8-hour mixed-use soak; exceed N to verify admission control. Proposed acceptance targets: ≥99% successful starts and p95 ready-to-interact ≤120 seconds, excluding declared provider outages. Adjust targets through recorded review, not silent exceptions.
- Require zero unresolved critical/high security defects, zero unexplained financial discrepancies, passing restore and tenant-isolation drills, and no silent data loss in normal stop/start flows.
- Run an invited beta with support and incident tracking; resolve launch-blocking findings before opening public signup. Longer-term availability claims require ongoing measurement.

**Done when:** the release checklist links to test output, deployed version, configuration and named sign-off; all M1–M11 criteria pass or the product scope is explicitly narrowed and documentation updated. No mandatory blocker is disguised as a future enhancement.

**Dependencies:** all preceding milestones.

## 3. Delivery sequence

| Phase | Work that can proceed together | Exit gate |
| --- | --- | --- |
| A: Finish local product | M2 creation/customization; M8 migrations/recovery; M11 draft docs; M1 decisions | Coherent local customer flow and agreed scope |
| B: Integrate real services | M3 identity; M4 real agent; M5 payments; M6 token trial | End-to-end staging paid and trial flows |
| C: Make hosting dependable | M7 isolation; M9 recovery; M10 deployment/alerts; complete M8 | Hardened staging, restored data and operational alerts |
| D: Prove and launch | M12 acceptance/beta; finalize M11 | Evidence-backed production v1 |

Infrastructure work can start during Phase A. Identity and policy decisions should not delay independent resource, recovery, documentation or test work. Do not enable public payments merely because checkout renders.

## 4. Inputs that code alone cannot supply

Record missing inputs in [ROADBLOCKS](../ROADBLOCKS.md) while continuing independent implementation:

1. Main platform repository, name and domain; deployment provider/account/region and access.
2. Production identity project, SMTP and chosen OAuth credentials.
3. Authorized agent-provider key and who pays for model usage.
4. Payment treasury, network approval, RPC and gas-funded facilitator signer; mainnet test authorization.
5. Platform-token network/address/decimals/treasury and approved holdings/trial policy.
6. Approved prices, limits, retention/recovery promises, operating policies and support ownership.

Secrets belong in secret storage, not this document, chat logs or the repository. Use placeholders and fail-closed disabled integrations until configured.

## 5. Later expansion — not required for the defined v1

Windows/macOS, GPUs, arbitrary resource sizes, custom uploaded OS images, live-memory hibernation, public template marketplace, scheduled agents, multiple model providers, smart-contract wallets/extra chains, automatic renewals/refunds, multi-region scheduling and enterprise SSO are separate projects. Self-service historical restore and elastic multi-host scaling may be promoted into v1 if the promised product requires them; each needs its own design and acceptance criteria.

## 6. Tracking rules

Use `not started`, `implemented locally`, `verified in staging`, and `accepted for launch` rather than a single subjective percentage. Each milestone records an owner, open issues, PRs, test evidence, remaining external inputs and acceptance date. Estimates come after M1 decisions and a task breakdown; this specification does not promise an unsupported launch date.

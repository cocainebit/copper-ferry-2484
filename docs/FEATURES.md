# Desktop resources, clones and templates

Workspace owners can customize stopped computers in the dashboard. Team members can read settings and job progress. Computers must have been started and cleanly stopped once before cloning or templating so their installed system is saved.

## Resources

Choose 1 or 2 CPU cores, 2 or 4 GiB RAM and a 20, 50 or 100 GiB home storage tier. Defaults remain 2 CPU / 4 GiB / 20 GiB. These are passed to OpenSandbox on the next start; changing a running computer is rejected. These choices remain within the existing plan ceiling.

The storage tier is honest about what it enforces. `GET /computers/{id}/profile` reports `storage_quota_enforced`. On the Docker runtime (the local stack) named volumes ignore the requested size, so the tier only bounds clone copies (a clone refuses a source home larger than the target's tier) and is shown against measured usage. On the OpenSandbox Kubernetes runtime the same value sizes the home claim itself; operators set `STORAGE_QUOTA_ENFORCED=true` there so the dashboard stops describing the tier as advisory.

## Full clones

Cloning creates an independent system snapshot and copies the stopped source's home to a new persistent volume. Files, ownership, permissions, symlinks, personal preferences, and browser sessions are copied. No source volume is shared with the clone. The new computer counts toward the existing saved-computer limit and starts stopped. A paid workspace can have two saved computers; a trial can have one, so a trial cannot clone its only computer without a plan change.

The source is temporarily unavailable while copying. Installed applications and the home are copied together only after a clean stop; running processes and RAM are never cloned. Clones contain browser credentials and other files: workspace owners must consider who has access to that workspace.

## System templates

A template saves installed applications and system settings into its own snapshot. It **excludes the mounted home directory**, including documents, browser profiles, wallpapers and other per-user preferences. System-wide secrets outside the home can still be included. Templates are workspace-private; do not bake credentials into system files.

Each workspace can store five templates. Creating a computer from one produces another independent snapshot and a fresh home. Deleting a template or its source does not delete existing computers made from it.

## API

All routes start with `/v1` and require an authenticated session or a workspace API key with the right scope (see the [developer guide](API.md)). Mutations other than profile PUT require `Idempotency-Key` (8–100 characters).

- `GET/PUT /computers/{id}/profile`: CPU, memory, `storage_gib` (20/50/100), resolution and `idle_timeout_minutes` settings. Omitted PUT fields preserve saved values. Idle timeout is 0–1440 minutes, default 15; zero disables idle stopping.
- `POST /computers/{id}/upload`: upload one base64-encoded file into Home (maximum 20 MiB). Allowed for whoever may operate the computer: the person in control, or anyone in the workspace while no human has taken control and no built-in task runs.
- `POST /computers/{id}/delete-file`: delete one file inside Home under the same rule (directories and Home itself are refused).
- `PATCH /computers/{id}`: `{ "name": "New name" }` renames (any member).
- `POST /computers/{id}/terminal-ticket` then the `/computers/{id}/pty` websocket: interactive administrator shell for the person in control. Computers whose saved system predates the shell fall back to the one-shot `POST /computers/{id}/terminal`.
- `POST /computers/{id}/clone`: `{ "name": "Copy" }`.
- `POST /computers/{id}/templates`: `{ "name": "Python tools" }`.
- `GET /workspaces/{id}/templates`: templates with lifecycle state.
- `POST /workspaces/{id}/computers`: `{ "name": "New desktop", "cpu": 1, "memory_gib": 2, "storage_gib": 50 }`; omitted resources default to 2 CPU / 4 GiB / 20 GiB.
- `GET /workspaces/{id}/computers`: each row carries its effective `cpu`, `memory_gib`, `storage_gib` and `resolution`.
- `POST /templates/{id}/computers`: `{ "name": "New desktop", "cpu": 1, "memory_gib": 2, "storage_gib": 50 }`; omitted resources inherit the template.
- `DELETE /templates/{id}`: queue deletion.
- `GET /workspaces/{id}/feature-jobs`: operation status and any user-safe error.

Copy mutations return HTTP 202 and a durable job. Poll the jobs route; completion means the target can start. Do not start or delete a source with `customizing` status or a target with `copying` status. A failed target has `copy_failed` status and must be deleted before retrying.

## Operations and limits

The singleton lifecycle worker runs one feature job at a time and reserves an infrastructure slot for its helper. Helper sandboxes have a 15-minute lifetime; interrupted operations are not replayed automatically. After 20 minutes the worker releases a frozen source and marks the failed target for deletion. Successful copies are independent of source deletion.

Database changes are additive tables: `desktop_profiles`, `desktop_templates`, `desktop_feature_jobs`. Include these in backup/RLS/migration policies. System snapshot artifacts require infrastructure backups separate from database and home-volume backups.

Tests exercise authorization, isolation, quotas, durable job transitions and adapter parameters. A real stopped-desktop clone and template launch must also be validated against the deployed OpenSandbox version before enabling these features publicly.

Creation bodies also accept `idle_timeout_minutes`; template consumers inherit it when omitted. Background guest processes do not count as dashboard activity. Always-on disables only idle stopping; metering and balance exhaustion still apply.

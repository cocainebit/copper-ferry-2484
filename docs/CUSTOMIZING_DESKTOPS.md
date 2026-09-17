# Customizing your desktop

## Configure a new computer

The Create computer dialog lets you choose a name, 1 or 2 CPU cores, and 2 or 4 GiB RAM. Choose a clean Linux environment or, as a workspace owner, a ready private system template. Templates prefill their saved resource allocation; you can change it before creating. Resource choices are saved with the computer. Template-based computers become available after copying completes; start them when ready.

## What persists

| Customization                               | How to change it                                                      | Persistence                                       |
| ------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------- |
| Wallpaper and appearance                    | Take control; open Linux Applications → Settings                      | Home configuration survives normal stop/start     |
| Browser preferences, extensions and profile | Use visible Chromium                                                  | Home profile survives normal stop/start           |
| Files, scripts and project environments     | Files, terminal or desktop apps                                       | Home volume survives normal stop/start            |
| System packages and configuration           | Dashboard Terminal while you have control                             | Saved in a system snapshot when stopping normally |
| CPU and memory                              | Owner: stop the computer, then open desktop customization in Settings | Applied on the next start                         |

For example, install a utility from the dashboard Terminal:

```sh
apt-get update && apt-get install -y jq
jq --version
```

Stop the computer from the dashboard, wait until it is stopped, then start it again. The installed utility remains available.

The dashboard terminal has administrator privileges inside your computer. The graphical desktop runs as the `desktop` user. That user does not have passwordless sudo; use the dashboard terminal for administrator changes.

## Resources

Workspace owners can select **1 or 2 CPU cores** and **2 or 4 GiB RAM**. Defaults are 2 CPU / 4 GiB. Stop the desktop first; the worker passes the saved allocation to OpenSandbox on the next start. Pick a **20, 50 or 100 GiB** home storage tier the same way. On the local Docker runtime the tier bounds clone copies and is displayed against measured usage but is not a hard disk limit; on the Kubernetes runtime it sizes the home volume. Larger CPU/RAM allocations are not available yet. Choose **1280×720, 1440×900 (default), or 1920×1080** during creation or in stopped-computer settings. Changes apply next start. Clones/templates inherit resolution; template consumers can override it. Agent coordinates match the selected dimensions. Legacy platform startup scripts are upgraded narrowly; custom scripts must honor `DESKTOP_RESOLUTION` or startup fails the geometry check.

## Idle stop and background work

Choose an idle-stop timeout during creation or in stopped-computer settings. The default is 15 minutes; the dashboard offers 5, 15, 30, 60 minutes or **Always on**. The API accepts integer minutes from 0 through 1440; zero disables idle stopping. Clones and templates preserve this policy, and template consumers can override it.

Inactivity means no qualifying dashboard/control activity and no queued or running built-in agent task. Guest background processes do not reset that timer. Use Always on for unattended scripts or services. You can close the dashboard; compute charges continue while the computer runs. Credit exhaustion, manual stop, runtime failures and maintenance can still stop it. This setting is not an uptime guarantee.

## Clone a complete desktop

Start and stop the source at least once so its system snapshot is saved. In Settings → desktop customization, select a stopped computer, enter a new name and choose **Clone computer**. The source stays unavailable during the operation. Follow progress under recent operations; the clone is ready when it becomes stopped.

Clones copy installed software, system settings and the entire home folder into independent storage. This includes documents, browser sessions and credentials saved in that home. Changes to a clone do not change its source. The clone counts toward the saved-computer limit: two for an active paid plan, one for a trial. A failed clone must be deleted before retrying.

## Save a reusable system template

Choose **Save system template** for a stopped computer. A template includes installed applications and system settings but **excludes the home folder**: documents, browser sessions, wallpaper and per-user preferences do not carry over. Credentials written outside the home can still be included, so avoid storing secrets in system files.

Templates are private to the workspace; owners can create, use and delete them. Up to five can be saved. Enter a name and choose **Create computer** beside a ready template to create a computer with a fresh home. Each consumer has its own system snapshot; deleting a template does not invalidate existing computers made from it.

See [feature details and API routes](FEATURES.md) for quotas, asynchronous operations and recovery behavior.

## Persistence and recovery limits

- Snapshots preserve system files, not live process memory. Unexpected destruction before a snapshot can lose recent system changes. Home data persists independently.
- Deleting a computer erases its home and removes its saved system snapshot. It is not a restore operation. Self-service point-in-time restore, public template sharing and Windows/macOS desktops are not implemented.
- Operator [backup and recovery](BACKUPS.md) tools exist; local backup extraction and a disposable database restore have passed. Their availability does not mean your desktop has a scheduled backup or that a complete recovery drill has passed. Production needs a defined off-host backup schedule and tested recovery.
- The local Docker preview uses a development-only Chromium `--no-sandbox` flag because Docker Desktop blocks Chromium's namespace sandbox. Production does not receive that flag and requires a tested hardened runtime. Do not expose this development environment publicly.
- CPU/RAM limits do not enforce disk quotas. The storage tier bounds clone copies and, on Kubernetes, sizes the home claim; on Docker it is advisory. Snapshots still need independently enforced production storage quotas.

See [production runtime preparation](PRODUCTION_RUNTIME.md), [deployment](DEPLOYMENT.md), and [remaining launch blockers](../ROADBLOCKS.md).

# Customizing your desktop

## What persists now

| Customization | How to change it | Persistence |
|---|---|---|
| Wallpaper and appearance | Take control; open the Linux Applications → Settings menu | Home configuration survives normal stop/start |
| Browser preferences, extensions and profile | Use the visible Chromium browser | Home profile survives normal stop/start |
| Files, scripts and project environments | Files, terminal or desktop apps | Home volume survives normal stop/start |
| System packages and configuration | Dashboard Terminal while you have control | Saved in a system snapshot when stopping normally |

For example, install a utility from the dashboard Terminal:

```sh
apt-get update && apt-get install -y jq
jq --version
```

Stop the computer from the dashboard, wait until it is stopped, then start it again. The installed utility remains available.

The dashboard terminal has administrator privileges inside your computer. The graphical desktop runs as the `desktop` user. That user does not have passwordless sudo; use the dashboard terminal for administrator changes.

## Limits of the current implementation

- One Linux base image, with a fixed 1440×900 display and 2 CPU/4 GiB RAM allocation.
- No user-facing template library, template sharing, clone/restore UI, resource sliders or Windows/macOS desktops yet.
- Snapshots preserve system files, not live process memory. Unexpected destruction before a snapshot can lose recent system changes. Home data persists independently, but is not backed up automatically.
- Deleting a computer erases its home and removes its saved system snapshot. It is not a restore operation.
- The local Docker preview uses a development-only Chromium `--no-sandbox` flag because the default Docker Desktop environment blocks Chromium's namespace sandbox. Production must use a compatible hardened runtime and does not receive that flag. Do not expose this development environment publicly.

A hosted version needs storage quotas, tested backups and stronger isolation before offering unrestricted administrator access to customers. See ROADBLOCKS.md for the remaining platform work.

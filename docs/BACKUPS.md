# Backup and recovery

The local tool creates encrypted restic backups of Postgres, OpenSandbox metadata, desktop home volumes, system snapshots and template images. A completed local backup was extracted and restored into a fresh disposable Postgres database; every recorded table count, SQLite integrity and desktop archive structure passed. A full desktop boot on a replacement host remains untested.

## Create a backup

Stop desktops through the dashboard and wait for their snapshots to finish. Stop the API and worker, then wait at least 30 seconds. The script refuses a running worker or active desktop and holds database locks during capture.

```sh
cd services/api
.venv/bin/python ../../scripts/backup.py backup
.venv/bin/python ../../scripts/backup.py check
```

These commands target the local Compose container names and database. Adapt them explicitly before production use. Staging needs room for database exports and complete images in both the host and Docker storage. Failed captures receive pending tags; only successful captures receive the platform tag used by restore.

The encrypted repository is `.local/backups`; its password is `.local/backup-password`. Preserve the password separately in a protected recovery store. Also preserve the application's original encryption key, signing/configuration secrets and deployment image digests separately; the repository does not include `.env` files. Without the original encryption key, restored customer API credentials cannot be decrypted.

## Verify recovery safely

Use a new destination; restore refuses an existing directory and checks required files before reporting success.

```sh
cd services/api
.venv/bin/python ../../scripts/backup.py restore --destination /absolute/new/recovery-directory
.venv/bin/python ../../scripts/restore_drill.py /absolute/new/recovery-directory
```

The drill creates and deletes its own database, leaving the live database and home volumes untouched. It verifies counts and archive structure, without executing archived software.

For real disaster recovery, keep ingress/API/worker stopped on fresh infrastructure. Restore `source/database.dump` with `pg_restore --exit-on-error` into an empty database; restore `opensandbox.db` into the manager's data volume before starting it. Load each manifest-listed system/template image with `docker image load`; restore each home tar into its corresponding `desktop-<computer-id>` Docker volume. Preserve the desktop image's numeric ownership. Restore the original application keys and reviewed runtime configuration. Start the manager, API and worker, then verify readiness, tenant access controls, desktop boot, saved applications and home contents before reopening ingress.

## Remaining production work

Local encrypted backups do not protect against loss of this machine. Configure off-host storage, scheduled quiescent captures, retention and alerts; test complete recovery on a replacement Linux host. Stop-time snapshots are not continuous autosave. The first two development backup attempts produced incomplete snapshots; restore now rejects incomplete content, and new incomplete captures are excluded from the successful-backup tag.

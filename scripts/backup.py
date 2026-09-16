"""Encrypted local backup/restore staging via restic. Stop API/worker/desktops first.
Run from services/api: .venv/bin/python ../../scripts/backup.py backup
Restore extracts into a NEW directory; it never overwrites the running service.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from uuid import uuid4
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service.db import Base, Computer, ServiceHeartbeat, engine, now
from desktop_service.feature_models import DesktopTemplate

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
REPOSITORY = LOCAL / "backups"
PASSWORD = LOCAL / "backup-password"
RESTIC = "restic/restic:0.18.0"


def docker(*args, stdout=None):
    try:
        return subprocess.run(
            ["docker", *args], check=True, stdout=stdout, stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode(errors="replace")) from None


def restic(*args, mounts=()):
    command = [
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        "RESTIC_REPOSITORY=/repository",
        "-e",
        "RESTIC_PASSWORD_FILE=/password",
        "-v",
        str(REPOSITORY) + ":/repository",
        "-v",
        str(PASSWORD) + ":/password:ro",
    ]
    for source, target in mounts:
        command.extend(["-v", str(source) + ":" + target])
    return docker(*command, RESTIC, *args)


def initialize():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    if REPOSITORY.exists() and not PASSWORD.exists():
        raise RuntimeError("Backup password is missing; do not replace it")
    if not PASSWORD.exists():
        descriptor = os.open(PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(secrets.token_urlsafe(48))
    REPOSITORY.mkdir(exist_ok=True)
    if not (REPOSITORY / "config").exists():
        restic("init")


def backup():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Backups require the Postgres deployment")
    initialize()
    with engine.begin() as connection:
        # Same lock as the scheduler. Never back up mutable desktop files.
        if not connection.execute(
            text("SELECT pg_try_advisory_xact_lock(8118026)")
        ).scalar():
            raise RuntimeError("Stop the worker before taking a backup")
        tables = ",".join(
            '"' + table.name + '"' for table in Base.metadata.sorted_tables
        )
        connection.execute(text("LOCK TABLE " + tables + " IN SHARE MODE"))
        heartbeat = connection.execute(
            select(ServiceHeartbeat.updated_at).where(
                ServiceHeartbeat.id == "desktop-worker"
            )
        ).scalar()
        if heartbeat and (now() - heartbeat).total_seconds() < 30:
            raise RuntimeError("Wait 30 seconds after stopping the worker")
        rows = (
            connection.execute(select(Computer).where(Computer.status != "deleted"))
            .mappings()
            .all()
        )
        if any(
            row["status"] not in ("stopped", "failed", "copy_failed") for row in rows
        ):
            raise RuntimeError(
                "Stop all desktops and finish feature jobs before backup"
            )
        with tempfile.TemporaryDirectory(
            prefix="backup-stage-", dir=LOCAL
        ) as directory:
            stage = Path(directory)
            with (stage / "database.dump").open("wb") as output:
                docker(
                    "exec",
                    "agent-desktop-postgres-1",
                    "pg_dump",
                    "-U",
                    "desktop",
                    "-d",
                    "desktop",
                    "-Fc",
                    stdout=output,
                )
            # SQLite online-backup API produces a consistent OpenSandbox metadata file.
            docker(
                "exec",
                "agent-desktop-opensandbox-1",
                "python",
                "-c",
                "import sqlite3; s=sqlite3.connect('/data/opensandbox.db'); d=sqlite3.connect('/tmp/platform-backup.db'); s.backup(d); d.close(); s.close()",
            )
            docker(
                "cp",
                "agent-desktop-opensandbox-1:/tmp/platform-backup.db",
                str(stage / "opensandbox.db"),
            )
            docker(
                "exec",
                "agent-desktop-opensandbox-1",
                "rm",
                "-f",
                "/tmp/platform-backup.db",
            )
            manifest = {
                "templates": [],
                "version": 1,
                "created_at": now().isoformat() + "Z",
                "computers": [],
                "table_counts": {
                    table.name: connection.execute(
                        text(f'SELECT count(*) FROM "{table.name}"')
                    ).scalar()
                    for table in Base.metadata.sorted_tables
                },
            }
            for row in rows:
                cid = row["id"]
                volume = "desktop-" + cid
                exists = (
                    subprocess.run(
                        ["docker", "volume", "inspect", volume],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode
                    == 0
                )
                item = {
                    "id": cid,
                    "home_archive": None,
                    "system_archive": None,
                    "snapshot_id": row["system_snapshot_id"],
                }
                if exists:
                    with (stage / (cid + "-home.tar")).open("wb") as output:
                        docker(
                            "run",
                            "--rm",
                            "--network",
                            "none",
                            "-v",
                            volume + ":/home-backup:ro",
                            "--entrypoint",
                            "tar",
                            "agent-desktop:local",
                            "-C",
                            "/home-backup",
                            "-cf",
                            "-",
                            ".",
                            stdout=output,
                        )
                    item["home_archive"] = cid + "-home.tar"
                if row["system_snapshot_id"]:
                    with (stage / (cid + "-system.tar")).open("wb") as output:
                        docker(
                            "image",
                            "save",
                            "opensandbox-snapshots:" + row["system_snapshot_id"],
                            stdout=output,
                        )
                    item["system_archive"] = cid + "-system.tar"
                manifest["computers"].append(item)
            for template in connection.execute(
                select(DesktopTemplate).where(DesktopTemplate.status != "deleted")
            ).mappings():
                if template["status"] != "ready":
                    raise RuntimeError("Finish template jobs before backing up")
                filename = template["id"] + "-template.tar"
                with (stage / filename).open("wb") as output:
                    docker(
                        "image",
                        "save",
                        "opensandbox-snapshots:" + template["snapshot_id"],
                        stdout=output,
                    )
                manifest["templates"].append(
                    {
                        "id": template["id"],
                        "snapshot_id": template["snapshot_id"],
                        "system_archive": filename,
                    }
                )
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
            # Native Docker staging avoids macOS VirtioFS read failures on fresh dump files.
            volume = "agent-desktop-backup-stage-" + uuid4().hex
            container = "agent-desktop-backup-copy-" + uuid4().hex
            docker("volume", "create", volume, stdout=subprocess.DEVNULL)
            try:
                docker(
                    "create",
                    "--name",
                    container,
                    "--network",
                    "none",
                    "-v",
                    volume + ":/source",
                    "--entrypoint",
                    "sleep",
                    RESTIC,
                    "600",
                    stdout=subprocess.DEVNULL,
                )
                docker("cp", str(stage) + "/.", container + ":/source")
                backup_tag = "pending-" + uuid4().hex
                restic(
                    "backup",
                    "--host",
                    "agent-desktop",
                    "--tag",
                    backup_tag,
                    "/source",
                    mounts=[(volume, "/source:ro")],
                )
                restic(
                    "tag",
                    "--tag",
                    backup_tag,
                    "--add",
                    "platform",
                    "--remove",
                    backup_tag,
                )
            finally:
                docker("rm", "-f", container, stdout=subprocess.DEVNULL)
                docker("volume", "rm", volume, stdout=subprocess.DEVNULL)
    restic("check")
    print(
        "Encrypted backup completed and repository integrity checked. Preserve .local/backup-password separately."
    )


def restore(destination):
    if not PASSWORD.exists() or not (REPOSITORY / "config").exists():
        raise RuntimeError("Repository and original password are required")
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Restore target must be a new directory")
    destination.mkdir(mode=0o700, parents=True)
    restic(
        "restore",
        "latest",
        "--tag",
        "platform",
        "--target",
        "/restore",
        mounts=[(destination, "/restore")],
    )
    source = destination / "source"
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("version") != 1:
        raise RuntimeError("Unsupported backup version")
    required = ["database.dump", "opensandbox.db"]
    for item in manifest["computers"] + manifest.get("templates", []):
        required.extend(
            item[key] for key in ("home_archive", "system_archive") if item.get(key)
        )
    for filename in required:
        archive = source / filename
        if (
            archive.parent != source
            or not archive.is_file()
            or not archive.stat().st_size
        ):
            raise RuntimeError(
                "Backup is incomplete or contains an invalid archive path"
            )
    print(
        "Backup extracted to a new directory. Follow docs/BACKUPS.md to restore into fresh infrastructure."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "check", "restore"])
    parser.add_argument("--destination")
    args = parser.parse_args()
    if args.action == "backup":
        backup()
    elif args.action == "check":
        restic("check")
    elif not args.destination:
        parser.error("--destination is required for restore")
    else:
        restore(args.destination)

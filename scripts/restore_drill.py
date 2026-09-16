"""Validate an extracted backup against a NEW disposable Postgres database.
Never restores over the live database or mounts customer homes on the host.
"""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service.config import settings


def run(directory):
    source = Path(directory).resolve() / "source"
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("version") != 1:
        raise ValueError("Unsupported backup format")
    with sqlite3.connect(
        f"file:{source / 'opensandbox.db'}?mode=ro", uri=True
    ) as metadata:
        assert metadata.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for item in manifest["computers"] + manifest.get("templates", []):
        for key in ("home_archive", "system_archive"):
            if item.get(key):
                archive = source / item[key]
                if archive.parent != source:
                    raise ValueError("Unexpected archive path")
                with tarfile.open(archive) as tar:
                    if key == "system_archive":
                        assert "manifest.json" in tar.getnames()
                    else:
                        assert tar.getmembers()
    name = "desktop_restore_check_" + uuid4().hex[:12]

    def docker(*args, stdin=None):
        subprocess.run(
            ["docker", "exec", "-i", "agent-desktop-postgres-1", *args],
            stdin=stdin,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    docker("createdb", "-U", "desktop", name)
    try:
        with (source / "database.dump").open("rb") as dump:
            docker(
                "pg_restore", "-U", "desktop", "-d", name, "--exit-on-error", stdin=dump
            )
        restored = create_engine(make_url(settings().database_url).set(database=name))
        try:
            with restored.connect() as connection:
                for table, expected in manifest["table_counts"].items():
                    if not table.replace("_", "").isalnum():
                        raise ValueError("Invalid table name")
                    actual = connection.execute(
                        text(f'SELECT count(*) FROM "{table}"')
                    ).scalar()
                    if actual != expected:
                        raise RuntimeError(f"Restored count differs: {table}")
        finally:
            restored.dispose()
        print(
            "PASS: encrypted archive extraction, fresh Postgres restore/counts, OpenSandbox metadata and desktop archives"
        )
    finally:
        docker("dropdb", "-U", "desktop", name)


if __name__ == "__main__":
    run(sys.argv[1])

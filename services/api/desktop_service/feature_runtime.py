"""Runtime operations run only by the singleton worker, never by a browser."""

import asyncio
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import PVC, Volume

from . import db as database_models
from . import runtime
from .config import settings
from .feature_models import DesktopProfile


def resource_for(cid):
    with database_models.Session() as db:
        profile = db.get(DesktopProfile, cid)
        return {"cpu": str(profile.cpu if profile else 2), "memory": f"{profile.memory_gib if profile else 4}Gi"}


async def materialize(source_snapshot, source_id=None, target_id=None):
    """Copy a stopped system and optionally its home to independent storage."""
    volumes = []
    if source_id:
        volumes.append(
            Volume(
                name="source",
                pvc=PVC(claim_name="desktop-" + source_id, create_if_not_exists=False),
                mount_path="/mnt/source",
                read_only=True,
            )
        )
    if target_id:
        volumes.append(
            Volume(
                name="target",
                pvc=PVC(claim_name="desktop-" + target_id, create_if_not_exists=True),
                mount_path="/mnt/target",
            )
        )
    sb = await Sandbox.create(
        **({"snapshot_id": source_snapshot} if source_snapshot else {"image": settings().desktop_image}),
        connection_config=runtime.connection(),
        timeout=timedelta(minutes=15),
        ready_timeout=timedelta(seconds=120),
        resource={"cpu": "1", "memory": "1Gi"},
        entrypoint=["sleep", "900"],
        volumes=volumes,
    )
    try:
        if target_id:
            command = "find /mnt/target -mindepth 1 -xdev -delete"
            if source_id:
                command = (
                    "test $(du -skx /mnt/source | cut -f1) -le 20971520 && "
                    + command
                    + " && cp -a -- /mnt/source/. /mnt/target/"
                )
            result = await sb.commands.run(command, opts=RunCommandOpts(timeout=timedelta(minutes=10)))
            if result.error:
                raise RuntimeError("Home copy failed or exceeded the 20 GiB copy limit")
        return await asyncio.wait_for(runtime.save_system(sb.id), timeout=150)
    finally:
        try:
            await sb.kill()
        finally:
            await sb.close()

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


def resolution_for(cid):
    with database_models.Session() as db:
        profile = db.get(DesktopProfile, cid)
        return profile.resolution if profile else "1440x900"


def storage_for(cid):
    with database_models.Session() as db:
        profile = db.get(DesktopProfile, cid)
        return profile.storage_gib if profile else 20


async def materialize(source_snapshot, source_id=None, target_id=None, storage_gib=20):
    """Copy a stopped system and optionally its home to independent storage.

    The copy is bounded by the target's storage tier. On the Docker runtime that bound is the only
    place the tier takes effect; Kubernetes additionally sizes the claim itself (see runtime.create).
    """
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
                    f"test $(du -skx /mnt/source | cut -f1) -le {int(storage_gib) * 1024 * 1024} && "
                    + command
                    + " && cp -a -- /mnt/source/. /mnt/target/"
                )
            result = await sb.commands.run(command, opts=RunCommandOpts(timeout=timedelta(minutes=10)))
            if result.error:
                raise RuntimeError(f"Home copy failed or exceeded the {storage_gib} GiB storage tier")
        return await asyncio.wait_for(runtime.save_system(sb.id), timeout=150)
    finally:
        try:
            await sb.kill()
        finally:
            await sb.close()

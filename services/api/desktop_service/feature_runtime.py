"""Runtime operations run only by the singleton worker, never by a browser."""

import asyncio
import shlex
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
        resource = {"cpu": str(profile.cpu if profile else 2), "memory": f"{profile.memory_gib if profile else 4}Gi"}
        if profile and profile.gpu:
            # OpenSandbox maps this to Docker DeviceRequests or nvidia.com/gpu on Kubernetes.
            resource["gpu"] = str(profile.gpu)
        return resource


def os_for(cid):
    with database_models.Session() as db:
        profile = db.get(DesktopProfile, cid)
        return profile.os if profile else "linux"


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


BUILD_MINUTES = 45
BUILD_LOG_LIMIT = 200_000


class BuildFailed(RuntimeError):
    def __init__(self, log):
        super().__init__("Template build failed")
        self.log = log


async def build(script):
    """Run a template build script as root in a disposable helper from the clean image, then snapshot it."""
    sb = await Sandbox.create(
        image=settings().desktop_image,
        connection_config=runtime.connection(),
        timeout=timedelta(minutes=BUILD_MINUTES + 5),
        ready_timeout=timedelta(seconds=120),
        resource={"cpu": "2", "memory": "4Gi"},
        entrypoint=["sleep", str((BUILD_MINUTES + 5) * 60)],
    )
    try:
        result = await sb.commands.run(
            "sh -c " + shlex.quote(script) + " 2>&1",
            opts=RunCommandOpts(timeout=timedelta(minutes=BUILD_MINUTES)),
        )
        output = "\n".join(x.text for x in result.logs.stdout) + "\n".join(x.text for x in result.logs.stderr)
        output = output[-BUILD_LOG_LIMIT:]
        if result.error:
            raise BuildFailed(output + f"\n[build failed: {result.error.value}]")
        return await asyncio.wait_for(runtime.save_system(sb.id), timeout=300), output
    finally:
        try:
            await sb.kill()
        finally:
            await sb.close()

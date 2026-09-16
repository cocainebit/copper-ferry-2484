import base64
import json
import shlex
from datetime import datetime, timedelta, timezone

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxApiException
from opensandbox.manager import SandboxManager
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import PVC, SandboxFilter, Volume

from .config import settings


def connection():
    s = settings()
    return ConnectionConfig(
        domain=s.opensandbox_domain,
        protocol=s.opensandbox_protocol,
        api_key=s.opensandbox_api_key,
        use_server_proxy=True,
        request_timeout=timedelta(seconds=60),
    )


async def create(cid, password):
    manager = await SandboxManager.create(connection_config=connection())
    try:
        existing = await manager.list_sandbox_infos(
            SandboxFilter(metadata={"agent-desktop-id": cid}, states=["RUNNING"])
        )
        if len(existing.sandbox_infos) > 1:
            raise RuntimeError("Multiple desktops found; operator reconciliation required")
        if existing.sandbox_infos:
            return existing.sandbox_infos[0].id
    finally:
        await manager.close()
    sb = await Sandbox.create(
        settings().desktop_image,
        connection_config=connection(),
        timeout=timedelta(hours=24),
        ready_timeout=timedelta(seconds=120),
        resource={"cpu": "2", "memory": "4Gi"},
        metadata={"agent-desktop-id": cid},
        env={"VNC_PASSWORD": password},
        entrypoint=["/opt/desktop/start.sh"],
        volumes=[
            Volume(
                name="home", pvc=PVC(claim_name="desktop-" + cid, create_if_not_exists=True), mount_path="/home/desktop"
            )
        ],
    )
    await sb.close()
    return sb.id


async def connect(sid):
    return await Sandbox.connect(sid, connection_config=connection())


async def stop(sid):
    manager = await SandboxManager.create(connection_config=connection())
    try:
        await manager.kill_sandbox(sid)
    except SandboxApiException as exc:
        if exc.status_code != 404:
            raise
    finally:
        await manager.close()


async def keep_alive(sid):
    manager = await SandboxManager.create(connection_config=connection())
    try:
        info = await manager.get_sandbox_info(sid)
        if info.expires_at and info.expires_at < datetime.now(timezone.utc) + timedelta(hours=1):
            await manager.renew_sandbox(sid, timedelta(hours=24))
    finally:
        await manager.close()


async def wipe(cid):
    # The desktop is stopped first. A separate short-lived sandbox wipes only its home volume.
    sb = await Sandbox.create(
        settings().desktop_image,
        connection_config=connection(),
        timeout=timedelta(minutes=5),
        entrypoint=["sleep", "300"],
        volumes=[
            Volume(
                name="home", pvc=PVC(claim_name="desktop-" + cid, create_if_not_exists=True), mount_path="/home/desktop"
            )
        ],
    )
    try:
        result = await sb.commands.run("find /home/desktop -mindepth 1 -xdev -delete")
        if result.error:
            raise RuntimeError("Home cleanup failed")
    finally:
        await sb.kill()
        await sb.close()


async def execute(sid, command):
    sb = await connect(sid)
    try:
        result = await sb.commands.run(
            command,
            opts=RunCommandOpts(
                working_directory="/home/desktop",
                timeout=timedelta(seconds=50),
                envs={"HOME": "/home/desktop", "DISPLAY": ":0"},
            ),
        )
        output = "\n".join(x.text for x in result.logs.stdout)
        errors = "\n".join(x.text for x in result.logs.stderr)
        if result.error:
            raise RuntimeError(result.error.value)
        return (output + "\n" + errors).strip()
    finally:
        await sb.close()


async def tool(sid, name, args):
    if name == "bash":
        return await execute(sid, "timeout 45s bash -lc " + shlex.quote(args["command"]))
    payload = base64.b64encode(json.dumps({"name": name, "input": args}).encode()).decode()
    return await execute(sid, "python3 /opt/desktop/tools.py " + shlex.quote(payload))


async def endpoint(sid, port):
    sb = await connect(sid)
    try:
        result = await sb.get_endpoint(port)
        return result.endpoint, result.headers or {}
    finally:
        await sb.close()

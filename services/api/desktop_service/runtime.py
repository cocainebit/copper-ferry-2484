import asyncio
import base64
import json
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxApiException
from opensandbox.manager import SandboxManager
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import PVC, SandboxFilter, Volume

from .config import settings
from .display import dimensions


def connection():
    s = settings()
    return ConnectionConfig(
        domain=s.opensandbox_domain,
        protocol=s.opensandbox_protocol,
        api_key=s.opensandbox_api_key,
        use_server_proxy=True,
        request_timeout=timedelta(seconds=60),
    )


async def create(cid, password, snapshot_id=None, pty_token=""):
    from .feature_runtime import resolution_for, resource_for, storage_for

    resolution = resolution_for(cid)
    dimensions(resolution)
    manager = await SandboxManager.create(connection_config=connection())
    try:
        existing = await manager.list_sandbox_infos(
            SandboxFilter(metadata={"agent-desktop-id": cid}, states=["RUNNING"])
        )
        if len(existing.sandbox_infos) > 1:
            raise RuntimeError("Multiple desktops found; operator reconciliation required")
        if existing.sandbox_infos:
            await wait_ready(existing.sandbox_infos[0].id)
            await verify_display(existing.sandbox_infos[0].id, resolution)
            return existing.sandbox_infos[0].id
    finally:
        await manager.close()
    sb = await Sandbox.create(
        **({"snapshot_id": snapshot_id} if snapshot_id else {"image": settings().desktop_image}),
        connection_config=connection(),
        timeout=timedelta(hours=24),
        ready_timeout=timedelta(seconds=120),
        resource=resource_for(cid),
        metadata={"agent-desktop-id": cid},
        env={
            "DESKTOP_RESOLUTION": resolution,
            "VNC_PASSWORD": password,
            "PTY_TOKEN": pty_token,
            "CHROMIUM_DEV_FLAGS": "--no-sandbox" if settings().dev_mode else "",
        },
        entrypoint=desktop_entrypoint(resolution, bool(snapshot_id)),
        volumes=[
            Volume(
                name="home",
                pvc=PVC(claim_name="desktop-" + cid, create_if_not_exists=True, storage=f"{storage_for(cid)}Gi"),
                mount_path="/home/desktop",
            )
        ],
    )
    await sb.close()
    await wait_ready(sb.id)
    await verify_display(sb.id, resolution)
    return sb.id


GUEST_PTY_SERVER = Path(__file__).with_name("guest") / "pty_server.py"


def snapshot_migration():
    # Upgrade only the exact platform-owned legacy Xvfb line in saved images.
    # Leave user-modified scripts untouched; verify actual geometry after boot.
    return (
        "from pathlib import Path; "
        "p=Path('/opt/desktop/start.sh'); s=p.read_text(); "
        "old='Xvfb :0 -screen 0 1440x900x24 -nolisten tcp &'; "
        "new='Xvfb :0 -screen 0 \"${DESKTOP_RESOLUTION:-1440x900}x24\" -nolisten tcp &'; "
        "p.write_text(s.replace(old,new)) if old in s else None"
    )


def desktop_entrypoint(resolution, from_snapshot=False):
    """Boot wrapper: refresh the platform-owned PTY server, launch it, then start the desktop.

    The server is written from the API's copy at every boot so saved system snapshots never pin an old
    version. Images that predate the websockets dependency simply fail to start it (logged in /tmp/pty.log)
    and the dashboard falls back to the one-shot command runner.
    """
    dimensions(resolution)
    payload = base64.b64encode(GUEST_PTY_SERVER.read_bytes()).decode()
    steps = [
        f"printf %s {payload} | base64 -d > /opt/desktop/pty_server.py",
        "(/opt/tools/bin/python /opt/desktop/pty_server.py > /tmp/pty.log 2>&1 &)",
    ]
    if from_snapshot:
        steps.append("python3 -c " + shlex.quote(snapshot_migration()))
    steps.append("exec /opt/desktop/start.sh")
    return ["/bin/sh", "-c", " && ".join(steps)]


async def verify_display(sid, resolution):
    width, height = dimensions(resolution)
    actual = await execute(sid, "DISPLAY=:0 xdotool getdisplaygeometry")
    if actual.strip() != f"{width} {height}":
        raise RuntimeError("Desktop startup script did not apply the selected display resolution")


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


async def save_system(sid):
    manager = await SandboxManager.create(connection_config=connection())
    try:
        snapshot = await manager.create_snapshot(sid)
        for _ in range(120):
            state = snapshot.status.state.upper()
            if state == "READY":
                return snapshot.id
            if state == "FAILED":
                raise RuntimeError("System snapshot failed; computer was not destroyed")
            await asyncio.sleep(1)
            snapshot = await manager.get_snapshot(snapshot.id)
        raise RuntimeError("System snapshot timed out; computer was not destroyed")
    finally:
        await manager.close()


async def delete_system(snapshot_id):
    manager = await SandboxManager.create(connection_config=connection())
    try:
        await manager.delete_snapshot(snapshot_id)
    finally:
        await manager.close()


async def wait_ready(sid):
    for _ in range(30):
        try:
            await execute(
                sid,
                "python3 -c \"import socket,urllib.request; socket.create_connection(('127.0.0.1',6080),2).close(); urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=2).read()\"",
            )
            return
        except Exception:
            await asyncio.sleep(1)
    raise RuntimeError("Desktop display or browser did not become ready")

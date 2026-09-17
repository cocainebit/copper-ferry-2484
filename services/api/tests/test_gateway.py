import asyncio
from unittest.mock import AsyncMock

import jwt
import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from desktop_service import gateway, runtime
from desktop_service.db import Computer, Event
from desktop_service.security import seal


@pytest.fixture
def running(db):
    c = Computer(
        workspace_id="w",
        name="Live",
        request_id="gateway-001",
        status="running",
        sandbox_id="sandbox-live",
        controller="local-user",
        pty_secret=seal("shell-token"),
    )
    db.add(c)
    db.commit()
    return c


class FakeRemote:
    """Stands in for the sandbox websocket: yields one prompt, records what the browser sent."""

    def __init__(self):
        self.sent = []
        self.connects = []
        self.gate = asyncio.Event()

    def connect(self, target, **kwargs):
        self.connects.append((target, kwargs))
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._stream()

    async def _stream(self):
        yield b"root@cubicle:~# "
        await self.gate.wait()

    async def send(self, data):
        self.sent.append(data)
        if len(self.sent) >= 2:
            self.gate.set()


def test_terminal_ticket_requires_control(client, db, running):
    running.controller = "agent"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/terminal-ticket").status_code == 409
    running.controller = "local-user"
    db.commit()
    response = client.post(f"/v1/computers/{running.id}/terminal-ticket")
    assert response.status_code == 200
    claims = jwt.decode(response.json()["ticket"], gateway.signing_key(), algorithms=["HS256"])
    assert claims["purpose"] == "desktop-terminal" and claims["cid"] == running.id and claims["control"]
    viewer = client.post(f"/v1/computers/{running.id}/viewer-ticket").json()
    assert jwt.decode(viewer["ticket"], gateway.signing_key(), algorithms=["HS256"])["purpose"] == "desktop-viewer"


def test_pty_rejects_viewer_ticket_and_wrong_origin(client, db, running, monkeypatch):
    endpoint = AsyncMock(return_value=("sandbox-host:7681", {}))
    monkeypatch.setattr(runtime, "endpoint", endpoint)
    viewer = client.post(f"/v1/computers/{running.id}/viewer-ticket").json()["ticket"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/computers/{running.id}/pty?ticket={viewer}", headers={"origin": "http://localhost:3000"}
        ):
            pass
    terminal = client.post(f"/v1/computers/{running.id}/terminal-ticket").json()["ticket"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/computers/{running.id}/pty?ticket={terminal}", headers={"origin": "http://evil.example"}
        ):
            pass
    endpoint.assert_not_awaited()


def test_pty_relays_bytes_and_resize_control_frames(client, db, running, monkeypatch):
    remote = FakeRemote()
    monkeypatch.setattr(runtime, "endpoint", AsyncMock(return_value=("sandbox-host:7681", {"X-Proxy": "1"})))
    monkeypatch.setattr(gateway.websockets, "connect", remote.connect)
    terminal = client.post(f"/v1/computers/{running.id}/terminal-ticket").json()["ticket"]
    with client.websocket_connect(
        f"/v1/computers/{running.id}/pty?ticket={terminal}", headers={"origin": "http://localhost:3000"}
    ) as ws:
        assert ws.receive_bytes() == b"root@cubicle:~# "
        ws.send_bytes(b"ls\n")
        ws.send_text('{"resize":[100,30]}')
        # The fake remote ends its stream after two inbound frames, closing the relay.
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
    assert remote.sent == [b"ls\n", '{"resize":[100,30]}']
    target, kwargs = remote.connects[0]
    # The OpenSandbox proxy drops Authorization, so the token rides in the query string.
    assert target == "ws://sandbox-host:7681/?token=shell-token"
    assert kwargs["additional_headers"] == {"X-Proxy": "1"}
    assert db.scalar(select(Event).where(Event.computer_id == running.id, Event.text.like("%terminal%")))


def test_pty_refused_for_computers_without_a_shell_token(client, db, running, monkeypatch):
    endpoint = AsyncMock(return_value=("sandbox-host:7681", {}))
    monkeypatch.setattr(runtime, "endpoint", endpoint)
    running.pty_secret = None
    db.commit()
    terminal = client.post(f"/v1/computers/{running.id}/terminal-ticket").json()["ticket"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/computers/{running.id}/pty?ticket={terminal}", headers={"origin": "http://localhost:3000"}
        ):
            pass
    endpoint.assert_not_awaited()


def test_pty_denied_after_control_is_lost(client, db, running, monkeypatch):
    endpoint = AsyncMock(return_value=("sandbox-host:7681", {}))
    monkeypatch.setattr(runtime, "endpoint", endpoint)
    terminal = client.post(f"/v1/computers/{running.id}/terminal-ticket").json()["ticket"]
    running.controller = "agent"
    db.commit()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/computers/{running.id}/pty?ticket={terminal}", headers={"origin": "http://localhost:3000"}
        ):
            pass
    endpoint.assert_not_awaited()


def test_rename_is_member_scoped_and_logged(client, db, running):
    assert client.patch(f"/v1/computers/{running.id}", json={"name": "  Renamed  "}).json()["name"] == "Renamed"
    assert client.patch(f"/v1/computers/{running.id}", json={"name": "   "}).status_code == 422
    assert client.patch(f"/v1/computers/{running.id}", json={"name": "x" * 81}).status_code == 422
    db.refresh(running)
    assert running.name == "Renamed"
    assert db.scalar(select(Event).where(Event.text == "Computer renamed to Renamed"))
    running.workspace_id = "other"
    db.commit()
    assert client.patch(f"/v1/computers/{running.id}", json={"name": "Nope"}).status_code == 403


def test_viewer_route_still_relays_binary_only(client, db, running, monkeypatch):
    remote = FakeRemote()
    monkeypatch.setattr(runtime, "endpoint", AsyncMock(return_value=("sandbox-host:6080", {})))
    monkeypatch.setattr(gateway.websockets, "connect", remote.connect)
    viewer = client.post(f"/v1/computers/{running.id}/viewer-ticket").json()["ticket"]
    with client.websocket_connect(
        f"/v1/computers/{running.id}/desktop?ticket={viewer}", headers={"origin": "http://localhost:3000"}
    ) as ws:
        assert ws.receive_bytes() == b"root@cubicle:~# "
        ws.send_text("ignored text frame")
        ws.send_bytes(b"\x01")
        ws.send_bytes(b"\x02")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_bytes()
    assert remote.sent == [b"\x01", b"\x02"]


class TickingRemote(FakeRemote):
    """Emits a numbered frame every 100 ms for about three seconds."""

    async def _stream(self):
        for index in range(30):
            yield bytes([index])
            await asyncio.sleep(0.1)


def test_audio_is_receive_only_and_survives_control_changes(client, db, running, monkeypatch):
    remote = TickingRemote()
    monkeypatch.setattr(runtime, "endpoint", AsyncMock(return_value=("sandbox-host:7682", {})))
    monkeypatch.setattr(gateway.websockets, "connect", remote.connect)
    running.controller = "agent"
    db.commit()
    ticket = client.post(f"/v1/computers/{running.id}/audio-ticket").json()["ticket"]
    claims = jwt.decode(ticket, gateway.signing_key(), algorithms=["HS256"])
    assert claims["purpose"] == "desktop-audio" and claims["control"] is False
    viewer = client.post(f"/v1/computers/{running.id}/viewer-ticket").json()["ticket"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/v1/computers/{running.id}/audio?ticket={viewer}", headers={"origin": "http://localhost:3000"}
        ):
            pass
    with client.websocket_connect(
        f"/v1/computers/{running.id}/audio?ticket={ticket}", headers={"origin": "http://localhost:3000"}
    ) as ws:
        assert ws.receive_bytes() == bytes([0])
        ws.send_bytes(b"ignored")
        running.controller = "local-user"  # control changes hands mid-stream
        db.commit()
        # The membership watch polls every second; frames must keep flowing well past that.
        received = [ws.receive_bytes() for _ in range(20)]
        assert received[-1] == bytes([20])
    assert remote.sent == []
    assert remote.connects[0][0] == "ws://sandbox-host:7682/?token=shell-token"


def test_entrypoint_audio_step_can_never_block_boot():
    import subprocess

    entry = runtime.desktop_entrypoint("1440x900", False)[2]
    probe = entry.replace("exec /opt/desktop/start.sh", "echo BOOT_CONTINUES")
    for target in runtime.GUEST_FILES:
        probe = probe.replace(target, "/dev/null")
    probe = probe.replace("> /etc/profile.d/cubicle-secrets.sh", "> /dev/null").replace("chmod 0644 /dev/null", "true")
    probe = probe.replace("chmod 0755 /dev/null", "true").replace(
        "(/opt/tools/bin/python /dev/null > /tmp/pty.log 2>&1 &)", "true"
    )
    for variant in (
        probe.replace("command -v pulseaudio", "false"),
        probe.replace("command -v pulseaudio", "true").replace("runuser -u desktop -- pulseaudio", "false"),
    ):
        result = subprocess.run(
            ["sh", "-c", variant.replace("/tmp/pulse.log", "/dev/null").replace("/tmp/audio.log", "/dev/null")],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip().endswith("BOOT_CONTINUES"), result.stderr
    assert "export PULSE_SERVER=unix:/tmp/cubicle-pulse/native" in entry

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import jwt
import pytest
from sqlalchemy import select

from desktop_service import computer_api, gateway, runtime, screens
from desktop_service.db import Computer, Event, Member
from desktop_service.feature_models import DesktopProfile
from desktop_service.screens import ComputerScreen


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Multi", request_id="screens-001", status="running", sandbox_id="sb-multi")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, resolution="1920x1080"))
    db.commit()
    computer_api._buckets.clear()
    return c


@pytest.fixture
def execute(monkeypatch):
    fake = AsyncMock(return_value="screen ready")
    monkeypatch.setattr(runtime, "execute", fake)
    return fake


def test_add_list_remove_and_limits(client, db, running, execute):
    assert client.get(f"/v1/computers/{running.id}/screens").json() == [
        {"number": 0, "resolution": "1920x1080", "primary": True}
    ]
    added = client.post(f"/v1/computers/{running.id}/screens", json={"resolution": "1280x720"})
    assert added.status_code == 201 and added.json() == {
        "number": 1,
        "resolution": "1280x720",
        "primary": False,
        "live": True,
    }
    assert execute.await_args.args == ("sb-multi", "/opt/desktop/screen.sh start 1 1280x720")
    assert client.post(f"/v1/computers/{running.id}/screens", json={}).json()["number"] == 2
    assert client.post(f"/v1/computers/{running.id}/screens", json={}).json()["number"] == 3
    assert client.post(f"/v1/computers/{running.id}/screens", json={}).status_code == 409
    assert client.post(f"/v1/computers/{running.id}/screens", json={"resolution": "9x9"}).status_code == 422
    assert client.delete(f"/v1/computers/{running.id}/screens/2").json() == {"ok": True}
    assert execute.await_args.args == ("sb-multi", "/opt/desktop/screen.sh stop 2")
    assert client.post(f"/v1/computers/{running.id}/screens", json={}).json()["number"] == 2  # lowest free
    assert client.delete(f"/v1/computers/{running.id}/screens/0").status_code == 409
    assert any(e.text == "Screen 2 added at 1280x720" for e in db.scalars(select(Event)))


def test_stopped_computer_persists_screens_without_starting(client, db, running, execute):
    running.status, running.sandbox_id = "stopped", None
    db.commit()
    body = client.post(f"/v1/computers/{running.id}/screens", json={}).json()
    assert body["live"] is False
    execute.assert_not_awaited()


def test_start_failure_rolls_back(client, db, running, execute):
    execute.side_effect = RuntimeError("old image")
    response = client.post(f"/v1/computers/{running.id}/screens", json={})
    assert response.status_code == 409 and "restart" in response.json()["detail"]
    assert db.scalar(select(ComputerScreen)) is None


def test_owner_only(client, db, running, execute):
    membership = db.scalar(select(Member).where(Member.workspace_id == "w"))
    membership.role = "member"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/screens", json={}).status_code == 403
    assert client.get(f"/v1/computers/{running.id}/screens").status_code == 200


def test_primitives_target_screens(client, db, running, monkeypatch):
    tool = AsyncMock(return_value="aGk=")
    monkeypatch.setattr(runtime, "tool", tool)
    db.add(ComputerScreen(computer_id=running.id, number=2, resolution="1280x720"))
    db.commit()
    shot = client.post(f"/v1/computers/{running.id}/screenshot?screen=2").json()
    assert (shot["width"], shot["height"]) == (1280, 720)
    assert tool.await_args.kwargs["display"] == ":2"
    assert client.post(f"/v1/computers/{running.id}/click", json={"x": 1, "y": 1, "screen": 2}).status_code == 200
    assert tool.await_args.kwargs["display"] == ":2"
    assert client.post(f"/v1/computers/{running.id}/type", json={"text": "hi"}).status_code == 200
    assert tool.await_args.kwargs["display"] == ":0"
    calls = tool.await_count
    assert client.post(f"/v1/computers/{running.id}/key", json={"key": "Return", "screen": 1}).status_code == 404
    assert client.post(f"/v1/computers/{running.id}/key", json={"key": "Return", "screen": 9}).status_code == 422
    assert tool.await_count == calls


def test_viewer_ticket_targets_screen_port(client, db, running, monkeypatch):
    db.add(ComputerScreen(computer_id=running.id, number=1, resolution="1440x900"))
    running.controller = "local-user"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/viewer-ticket?screen=3").status_code == 404
    body = client.post(f"/v1/computers/{running.id}/viewer-ticket?screen=1").json()
    claims = jwt.decode(body["ticket"], gateway.signing_key(), algorithms=["HS256"])
    assert claims["screen"] == 1 and body["screen"] == 1
    assert screens.ports(1, True) == 6090 and screens.ports(1, False) == 6091 and screens.ports(0, True) == 6080


def test_boot_recreates_persisted_screens_and_reports_failures(db, running, execute):
    import asyncio

    db.add(ComputerScreen(computer_id=running.id, number=1, resolution="1280x720"))
    db.add(ComputerScreen(computer_id=running.id, number=3, resolution="1920x1080"))
    db.commit()
    execute.side_effect = [None, RuntimeError("no x")]
    asyncio.run(screens.start_all(db, running))
    db.commit()
    commands = [c.args[1] for c in execute.await_args_list]
    assert commands == ["/opt/desktop/screen.sh start 1 1280x720", "/opt/desktop/screen.sh start 3 1920x1080"]
    assert any("Screen 3 could not start" in e.text for e in db.scalars(select(Event)))


def test_guest_screen_script_parses_and_validates_arguments():
    script = Path(screens.__file__).with_name("guest") / "screen.sh"
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0
    assert subprocess.run(["sh", str(script), "start", "7", "1280x720"], capture_output=True).returncode == 2
    assert subprocess.run(["sh", str(script), "start", "1", "999x1"], capture_output=True).returncode == 2


def test_guest_tools_reject_unknown_display(tmp_path):
    import base64
    import json
    import sys

    tools = Path(screens.__file__).with_name("guest") / "tools.py"
    payload = base64.b64encode(json.dumps({"name": "list_files", "input": {}, "display": ":9"}).encode()).decode()
    result = subprocess.run([sys.executable, str(tools), payload], capture_output=True, text=True)
    assert result.returncode != 0 and "Unsupported display" in result.stderr

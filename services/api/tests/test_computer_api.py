from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import computer_api, runtime
from desktop_service.db import Computer, Event, Run
from desktop_service.feature_models import DesktopProfile


@pytest.fixture
def running(db):
    c = Computer(workspace_id="w", name="Live", request_id="api-001", status="running", sandbox_id="sb-live")
    db.add(c)
    db.flush()
    db.add(DesktopProfile(computer_id=c.id, resolution="1280x720"))
    db.commit()
    computer_api._buckets.clear()
    return c


@pytest.fixture
def tool(monkeypatch):
    fake = AsyncMock(return_value="aGVsbG8=")
    monkeypatch.setattr(runtime, "tool", fake)
    return fake


def test_get_computer_reports_profile(client, running):
    body = client.get(f"/v1/computers/{running.id}").json()
    assert body["resolution"] == "1280x720" and body["cpu"] == 2 and body["status"] == "running"
    assert client.get("/v1/computers/missing").status_code == 404


def test_screenshot_click_type_key_scroll_drag_map_to_guest_tools(client, db, running, tool):
    cid = running.id
    shot = client.post(f"/v1/computers/{cid}/screenshot").json()
    assert shot == {"format": "png", "width": 1280, "height": 720, "image": "aGVsbG8="}
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 10, "y": 20}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 10, "y": 20, "count": 2}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 1, "y": 1, "button": "right"}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/type", json={"text": "hello"}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/key", json={"key": "ctrl+l"}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/scroll", json={"x": 5, "y": 5, "direction": "up"}).status_code == 200
    assert client.post(f"/v1/computers/{cid}/drag", json={"from": [1, 2], "to": [3, 4]}).status_code == 200
    calls = [c.args[1:] for c in tool.await_args_list]
    assert calls == [
        ("computer", {"action": "screenshot"}),
        ("computer", {"action": "left_click", "coordinate": [10, 20]}),
        ("computer", {"action": "double_click", "coordinate": [10, 20]}),
        ("computer", {"action": "right_click", "coordinate": [1, 1]}),
        ("computer", {"action": "type", "text": "hello"}),
        ("computer", {"action": "key", "text": "ctrl+l"}),
        ("computer", {"action": "mouse_move", "coordinate": [5, 5]}),
        ("computer", {"action": "scroll", "scroll_direction": "up", "scroll_amount": 3}),
        ("computer", {"action": "mouse_move", "coordinate": [1, 2]}),
        ("computer", {"action": "left_click_drag", "coordinate": [3, 4]}),
    ]
    assert all(c.args[0] == "sb-live" for c in tool.await_args_list)
    texts = [e.text for e in db.scalars(select(Event).where(Event.computer_id == cid))]
    assert "api: left_click at 10,20" in texts and "api: key ctrl+l" in texts


def test_validation_rejects_bad_input(client, running, tool):
    cid = running.id
    assert client.post(f"/v1/computers/{cid}/click", json={"x": -1, "y": 0}).status_code == 422
    assert (
        client.post(f"/v1/computers/{cid}/click", json={"x": 1, "y": 1, "button": "right", "count": 2}).status_code
        == 422
    )
    assert client.post(f"/v1/computers/{cid}/key", json={"key": "rm -rf /"}).status_code == 422
    assert client.post(f"/v1/computers/{cid}/wait", json={"seconds": 60}).status_code == 422
    assert client.post(f"/v1/computers/{cid}/scroll", json={"x": 1, "y": 1, "amount": 500}).status_code == 422
    tool.assert_not_awaited()


def test_bash_returns_output_or_error(client, running, tool):
    tool.return_value = "total 0"
    body = client.post(f"/v1/computers/{running.id}/bash", json={"command": "ls -la"}).json()
    assert body == {"output": "total 0", "error": None}
    tool.side_effect = RuntimeError("exit status 2")
    body = client.post(f"/v1/computers/{running.id}/bash", json={"command": "false"}).json()
    assert body["output"] == "" and "exit status 2" in body["error"]


def test_operator_rules_respect_manual_control_and_builtin_tasks(client, db, running, tool):
    cid = running.id
    running.controller = "someone-else"
    db.commit()
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 1, "y": 1}).status_code == 409
    running.controller = "local-user"
    db.commit()
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 1, "y": 1}).status_code == 200
    running.controller = "agent"
    db.add(Run(computer_id=cid, prompt="busy", request_id="run-1", status="running", lease="lease"))
    db.commit()
    assert client.post(f"/v1/computers/{cid}/click", json={"x": 1, "y": 1}).status_code == 409
    running.status = "stopped"
    db.commit()
    assert client.post(f"/v1/computers/{cid}/screenshot").status_code == 409
    running.workspace_id = "other"
    running.status = "running"
    db.commit()
    assert client.post(f"/v1/computers/{cid}/screenshot").status_code == 403


def test_rate_limit_per_actor(client, running, tool):
    statuses = [client.post(f"/v1/computers/{running.id}/wait", json={"seconds": 0}).status_code for _ in range(40)]
    assert statuses[:30] == [200] * 30 and 429 in statuses[30:]


def test_terminal_and_upload_follow_operator_rule(client, db, running, tool):
    tool.return_value = '{"name":"a.txt","size":1}'
    assert client.post(f"/v1/computers/{running.id}/upload", json={"path": "a.txt", "data": "YQ=="}).status_code == 200
    running.controller = "other-user"
    db.commit()
    assert client.post(f"/v1/computers/{running.id}/terminal", json={"command": "id"}).status_code == 409

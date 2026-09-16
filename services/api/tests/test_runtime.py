from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from desktop_service import runtime


@pytest.mark.asyncio
async def test_recover_created_sandbox_without_allocating_twice(monkeypatch):
    monkeypatch.setattr(runtime, "wait_ready", AsyncMock())
    manager = SimpleNamespace(
        list_sandbox_infos=AsyncMock(return_value=SimpleNamespace(sandbox_infos=[SimpleNamespace(id="recovered")])),
        close=AsyncMock(),
    )
    monkeypatch.setattr(runtime.SandboxManager, "create", AsyncMock(return_value=manager))
    create = AsyncMock()
    monkeypatch.setattr(runtime.Sandbox, "create", create)
    assert await runtime.create("computer", "password") == "recovered"
    create.assert_not_called()
    manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_persistent_volume_creation_and_password(monkeypatch,db):
    monkeypatch.setattr(runtime, "wait_ready", AsyncMock())
    manager = SimpleNamespace(
        list_sandbox_infos=AsyncMock(return_value=SimpleNamespace(sandbox_infos=[])), close=AsyncMock()
    )
    monkeypatch.setattr(runtime.SandboxManager, "create", AsyncMock(return_value=manager))
    create = AsyncMock(return_value=SimpleNamespace(id="new", close=AsyncMock()))
    monkeypatch.setattr(runtime.Sandbox, "create", create)
    assert await runtime.create("computer", "durable-password") == "new"
    args = create.call_args.kwargs
    assert args["volumes"][0].pvc.create_if_not_exists
    assert args["volumes"][0].pvc.claim_name == "desktop-computer"
    assert args["env"]["VNC_PASSWORD"] == "durable-password"


@pytest.mark.asyncio
async def test_large_screenshot_is_not_truncated(monkeypatch):
    payload = "a" * 100000
    commands = SimpleNamespace(
        run=AsyncMock(
            return_value=SimpleNamespace(
                error=None, logs=SimpleNamespace(stdout=[SimpleNamespace(text=payload)], stderr=[])
            )
        )
    )
    monkeypatch.setattr(
        runtime, "connect", AsyncMock(return_value=SimpleNamespace(commands=commands, close=AsyncMock()))
    )
    assert await runtime.execute("sandbox", "screenshot") == payload


@pytest.mark.asyncio
async def test_renew_only_near_expiry(monkeypatch):
    info = SimpleNamespace(expires_at=datetime.now(timezone.utc) + timedelta(hours=2))
    manager = SimpleNamespace(
        get_sandbox_info=AsyncMock(return_value=info), renew_sandbox=AsyncMock(), close=AsyncMock()
    )
    monkeypatch.setattr(runtime.SandboxManager, "create", AsyncMock(return_value=manager))
    await runtime.keep_alive("sandbox")
    manager.renew_sandbox.assert_not_called()
    info.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await runtime.keep_alive("sandbox")
    manager.renew_sandbox.assert_awaited_once()


def test_prune_images_preserves_tool_results():
    from desktop_service.worker import prune_images

    original = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": str(i),
                    "content": [{"type": "image", "source": {"data": "large"}}],
                }
            ],
        }
        for i in range(5)
    ]
    result = prune_images(original, keep=2)
    assert len(result) == 5
    assert result[0]["content"][0]["tool_use_id"] == "0"
    assert result[2]["content"][0]["content"][0]["type"] == "text"
    assert result[3]["content"][0]["content"][0]["type"] == "image"
    assert original[0]["content"][0]["content"][0]["type"] == "image"


@pytest.mark.parametrize("path", ["/etc/passwd", "../../etc/passwd"])
def test_file_download_cannot_escape_home(path):
    import base64
    import json
    import subprocess
    import sys
    from pathlib import Path

    tool = Path(__file__).resolve().parents[3] / "infra/desktop/tools.py"
    payload = base64.b64encode(json.dumps({"name": "read_file", "input": {"path": path}}).encode()).decode()
    result = subprocess.run([sys.executable, str(tool), payload], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Path must stay inside Home" in result.stderr
    assert not result.stdout


@pytest.mark.asyncio
async def test_snapshot_waits_for_ready(monkeypatch):
    manager = SimpleNamespace(
        create_snapshot=AsyncMock(return_value=SimpleNamespace(id="snap", status=SimpleNamespace(state="Pending"))),
        get_snapshot=AsyncMock(return_value=SimpleNamespace(id="snap", status=SimpleNamespace(state="Ready"))),
        close=AsyncMock(),
    )
    monkeypatch.setattr(runtime.SandboxManager, "create", AsyncMock(return_value=manager))
    monkeypatch.setattr(runtime.asyncio, "sleep", AsyncMock())
    assert await runtime.save_system("sandbox") == "snap"
    manager.get_snapshot.assert_awaited_once_with("snap")

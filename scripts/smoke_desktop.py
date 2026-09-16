"""Real sandbox smoke test. Run from services/api after building desktop image."""

import asyncio
import secrets
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service import runtime
from desktop_service.config import settings
import websockets


async def main():
    cid = str(uuid4())
    password = secrets.token_urlsafe(18)
    sid = None
    try:
        sid = await runtime.create(cid, password)
        await runtime.execute(sid, "printf persistence-test > /home/desktop/smoke.txt")
        for attempt in range(20):
            try:
                screenshot = await runtime.tool(sid, "computer", {"action": "screenshot"})
                assert screenshot.startswith("iVBOR")
                endpoint, headers = await runtime.endpoint(sid, 6081)
                scheme = "wss" if settings().opensandbox_protocol == "https" else "ws"
                async with websockets.connect(
                    f"{scheme}://{endpoint}/websockify", additional_headers=headers
                ) as socket:
                    assert (await asyncio.wait_for(socket.recv(), timeout=10)).startswith(b"RFB ")
                break
            except Exception:
                if attempt == 19:
                    raise
                await asyncio.sleep(2)
        browser = await runtime.tool(sid, "browser", {"action": "inspect"})
        assert "url" in browser
        await runtime.stop(sid)
        sid = None
        sid = await runtime.create(cid, password)
        assert await runtime.execute(sid, "cat /home/desktop/smoke.txt") == "persistence-test"
        print("PASS: screenshot, live VNC handshake, visible browser, stop/restart persistence")
    finally:
        if sid:
            await runtime.stop(sid)
        await runtime.wipe(cid)


if __name__ == "__main__":
    asyncio.run(main())

"""Desktop speaker stream: raw PCM from the PulseAudio null sink's monitor over a websocket.

Injected and started at boot like the PTY server and guarded by the same per-boot token. Each
connection runs its own `parec` so nothing is captured unless someone is listening. Frames are
signed 16-bit little-endian mono at RATE Hz, CHUNK_MS long. The first text frame describes the format.
"""

import asyncio
import hmac
import json
import os
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve

PORT = 7682
RATE = 24000
CHUNK_MS = 40
TOKEN = os.environ.get("PTY_TOKEN", "")
PULSE = os.environ.get("PULSE_SERVER", "unix:/tmp/cubicle-pulse/native")


def presented(request):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return (parse_qs(urlsplit(request.path).query).get("token") or [""])[0]


def gate(connection, request):
    if not TOKEN:
        return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "audio token not configured\n")
    if not hmac.compare_digest(presented(request), TOKEN):
        return connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
    return None


async def session(ws):
    process = await asyncio.create_subprocess_exec(
        "parec",
        "--server",
        PULSE,
        "--device",
        "cubicle.monitor",
        "--format=s16le",
        f"--rate={RATE}",
        "--channels=1",
        "--latency-msec=40",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await ws.send(json.dumps({"format": "s16le", "rate": RATE, "channels": 1}))
    size = RATE * 2 * CHUNK_MS // 1000

    async def pump():
        while True:
            chunk = await process.stdout.readexactly(size)
            await ws.send(chunk)

    async def drain():
        async for _ in ws:
            pass

    tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.IncompleteReadError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if process.returncode is None:
            process.kill()
        await process.wait()


async def main():
    async with serve(session, "0.0.0.0", PORT, process_request=gate, max_size=1 << 16):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

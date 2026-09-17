"""Interactive shell over a websocket inside the desktop sandbox.

The API injects this file at every boot (fresh image or saved snapshot) and launches it as root before
the desktop drops privileges, so saved systems always run the current version. It listens on all sandbox
interfaces because the OpenSandbox endpoint proxy connects over the container network, and every
handshake must present the per-computer token the API passed in PTY_TOKEN. Without a token it refuses
all connections.

One websocket connection is one shell session. Binary frames carry raw PTY bytes in both directions;
text frames are small JSON control messages:
  client -> {"resize": [cols, rows]}
  server -> {"exit": code}
"""

import asyncio
import fcntl
import hmac
import json
import os
import pty
import signal
import struct
import termios
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve

PORT = 7681
TOKEN = os.environ.get("PTY_TOKEN", "")
SHELL = ["/bin/bash", "-l"]
ENV = {
    "HOME": "/home/desktop",
    "DISPLAY": ":0",
    "TERM": "xterm-256color",
    "LANG": "C.UTF-8",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


def presented(request):
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return (parse_qs(urlsplit(request.path).query).get("token") or [""])[0]


def gate(connection, request):
    if not TOKEN:
        return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "terminal token not configured\n")
    if not hmac.compare_digest(presented(request), TOKEN):
        return connection.respond(HTTPStatus.UNAUTHORIZED, "unauthorized\n")
    return None


def resize(fd, cols, rows):
    cols = max(2, min(500, int(cols)))
    rows = max(1, min(300, int(rows)))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def session(ws):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir("/home/desktop")
        os.execvpe(SHELL[0], SHELL, ENV)
    resize(fd, 120, 32)
    loop = asyncio.get_running_loop()
    reader = asyncio.Queue()

    def readable():
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        reader.put_nowait(data)
        if not data:
            loop.remove_reader(fd)

    loop.add_reader(fd, readable)

    async def pump_out():
        while True:
            data = await reader.get()
            if not data:
                return
            await ws.send(data)

    async def pump_in():
        async for message in ws:
            if isinstance(message, bytes):
                os.write(fd, message)
            else:
                try:
                    control = json.loads(message)
                except ValueError:
                    continue
                if isinstance(control.get("resize"), list) and len(control["resize"]) == 2:
                    resize(fd, *control["resize"])

    out = asyncio.create_task(pump_out())
    inbound = asyncio.create_task(pump_in())
    try:
        await asyncio.wait({out, inbound}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (out, inbound):
            task.cancel()
        loop.remove_reader(fd)
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            _, status = os.waitpid(pid, 0)
            code = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            code = -1
        os.close(fd)
        try:
            await ws.send(json.dumps({"exit": code}))
        except Exception:
            pass


async def main():
    async with serve(session, "0.0.0.0", PORT, process_request=gate, max_size=1 << 20):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

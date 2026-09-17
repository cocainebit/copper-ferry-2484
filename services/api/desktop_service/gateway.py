import asyncio
import json
import secrets
from datetime import timedelta, timezone
from urllib.parse import quote

import jwt
import websockets
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import db as models
from . import runtime
from .computer_api import operator
from .config import settings
from .db import Computer, database, event, now
from .security import identity, member, unseal

router = APIRouter()


def signing_key():
    return settings().signing_key or (settings().dev_token if settings().dev_mode else "")


def authorize(db, cid, user):
    c = db.get(Computer, cid)
    if not c or c.status != "running":
        raise HTTPException(409, "Computer is not running")
    member(db, c.workspace_id, user)
    return c


def issue(user, cid, purpose, control):
    claims = {
        "sub": user["id"],
        "cid": cid,
        "exp": now().replace(tzinfo=timezone.utc) + timedelta(seconds=60),
        "jti": secrets.token_urlsafe(16),
        "purpose": purpose,
        "control": control,
    }
    return jwt.encode(claims, signing_key(), algorithm="HS256")


def redeem(ws, ticket, cid, purpose):
    if ws.headers.get("origin") != settings().public_url:
        raise ValueError("origin")
    claims = jwt.decode(
        ticket, signing_key(), algorithms=["HS256"], options={"require": ["exp", "sub", "cid", "purpose"]}
    )
    if claims["cid"] != cid or claims["purpose"] != purpose:
        raise ValueError("scope")
    return claims


@router.post("/v1/computers/{cid}/viewer-ticket")
def ticket(cid: str, user=Depends(identity), db=Depends(database)):
    c = authorize(db, cid, user)
    control = c.controller == user["id"]
    return {
        "ticket": issue(user, cid, "desktop-viewer", control),
        "control": control,
        "password": unseal(c.vnc_secret) if c.vnc_secret else "",
    }


@router.post("/v1/computers/{cid}/terminal-ticket")
def terminal_ticket(cid: str, user=Depends(identity), db=Depends(database)):
    c = authorize(db, cid, user)
    if c.controller != user["id"]:
        raise HTTPException(409, "Take control before opening the terminal")
    return {"ticket": issue(user, cid, "desktop-terminal", True)}


async def proxy(ws, cid, claims, sid, target, headers, control, text_frames=False):
    """Relay one browser websocket to one sandbox websocket until either side, or the grant, ends."""
    await ws.accept()
    async with websockets.connect(target, additional_headers=headers, max_size=16 * 1024 * 1024) as remote:

        async def incoming():
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                data = message.get("bytes")
                if data is None:
                    if not text_frames or message.get("text") is None:
                        continue
                    data = message["text"]
                with models.Session() as db:
                    current = authorize(db, cid, {"id": claims["sub"]})
                    if control and current.controller != claims["sub"]:
                        return
                    if control:
                        current.last_active = now()
                        db.commit()
                await remote.send(data)

        async def outgoing():
            async for data in remote:
                if isinstance(data, bytes):
                    await ws.send_bytes(data)
                elif text_frames:
                    await ws.send_text(data)

        async def membership_watch():
            for _ in range(3600):
                await asyncio.sleep(1)
                with models.Session() as db:
                    current = authorize(db, cid, {"id": claims["sub"]})
                    if current.sandbox_id != sid or bool(current.controller == claims["sub"]) != control:
                        return

        tasks = [asyncio.create_task(f()) for f in (incoming, outgoing, membership_watch)]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def sandbox_url(endpoint, path):
    protocol = "wss" if settings().opensandbox_protocol == "https" else "ws"
    return f"{protocol}://{endpoint}{path}"


@router.websocket("/v1/computers/{cid}/desktop")
async def desktop(ws: WebSocket, cid: str, ticket: str):
    try:
        claims = redeem(ws, ticket, cid, "desktop-viewer")
        with models.Session() as db:
            c = authorize(db, cid, {"id": claims["sub"]})
            control = claims["control"] and c.controller == claims["sub"]
            sid = c.sandbox_id
        endpoint, headers = await runtime.endpoint(sid, 6080 if control else 6081)
        await proxy(ws, cid, claims, sid, sandbox_url(endpoint, "/websockify"), headers, control)
    except (Exception, WebSocketDisconnect):
        pass
    finally:
        try:
            await ws.close(code=1000)
        except (RuntimeError, WebSocketDisconnect):
            pass


@router.websocket("/v1/computers/{cid}/pty")
async def pty(ws: WebSocket, cid: str, ticket: str):
    """Interactive administrator shell. Requires the same control grant as keyboard and mouse input."""
    try:
        claims = redeem(ws, ticket, cid, "desktop-terminal")
        with models.Session() as db:
            c = authorize(db, cid, {"id": claims["sub"]})
            if c.controller != claims["sub"] or not c.pty_secret:
                raise ValueError("control")
            sid = c.sandbox_id
            token = unseal(c.pty_secret)
            event(db, cid, "Interactive terminal opened", "activity")
            db.commit()
        endpoint, headers = await runtime.endpoint(sid, 7681)
        # The guest server refuses handshakes without this per-sandbox token. The OpenSandbox proxy
        # strips Authorization, so it travels as a query parameter; the worker rotates it every start.
        target = sandbox_url(endpoint, "/?token=" + quote(token, safe=""))
        await proxy(ws, cid, claims, sid, target, headers, True, text_frames=True)
    except (Exception, WebSocketDisconnect):
        pass
    finally:
        try:
            await ws.close(code=1000)
        except (RuntimeError, WebSocketDisconnect):
            pass


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=8000)


class Upload(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    data: str = Field(min_length=1, max_length=28_000_000)


@router.post("/v1/computers/{cid}/terminal")
async def terminal(cid: str, body: Command, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    output = await runtime.tool(c.sandbox_id, "bash", {"command": body.command})
    c.last_active = now()
    event(db, cid, "Terminal command executed", "activity")
    db.commit()
    return {"output": output}


@router.post("/v1/computers/{cid}/upload")
async def upload(cid: str, body: Upload, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    try:
        result = json.loads(await runtime.tool(c.sandbox_id, "write_file", {"path": body.path, "data": body.data}))
    except (ValueError, RuntimeError, json.JSONDecodeError):
        raise HTTPException(400, "Upload must be a file inside Home no larger than 20 MB") from None
    c.last_active = now()
    event(db, cid, "File uploaded", "activity")
    db.commit()
    return result


class DeleteFile(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


@router.post("/v1/computers/{cid}/delete-file")
async def delete_file(cid: str, body: DeleteFile, user=Depends(identity), db=Depends(database)):
    c = operator(db, cid, user)
    try:
        result = json.loads(await runtime.tool(c.sandbox_id, "delete_file", {"path": body.path}))
    except (ValueError, RuntimeError, json.JSONDecodeError):
        raise HTTPException(400, "Choose an existing file inside Home") from None
    c.last_active = now()
    event(db, cid, "File deleted", "activity")
    db.commit()
    return result


@router.get("/v1/computers/{cid}/files")
async def files(cid: str, path: str = "", user=Depends(identity), db=Depends(database)):
    c = authorize(db, cid, user)
    result = await runtime.tool(c.sandbox_id, "list_files", {"path": path})
    return json.loads(result)


@router.get("/v1/computers/{cid}/download")
async def download(cid: str, path: str, user=Depends(identity), db=Depends(database)):
    c = authorize(db, cid, user)
    try:
        return json.loads(await runtime.tool(c.sandbox_id, "read_file", {"path": path}))
    except RuntimeError:
        raise HTTPException(400, "Choose a file inside Home no larger than 20 MB") from None

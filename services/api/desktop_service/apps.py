"""App catalog and one-click installs into running computers.

Each catalog entry is a reproducible install recipe run as administrator inside the sandbox, detached,
with its log and exit status kept on the computer and mirrored into the database by the worker. What
gets installed lives in the system layer, so it survives stop/start through the system snapshot and
carries into clones and templates.
"""

import shlex
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from . import runtime
from .computer_api import operator
from .db import Base, Computer, database, event, now, uid
from .security import identity, member

router = APIRouter(prefix="/v1")

APT = "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends"
NODESOURCE = (
    "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends"
    " ca-certificates curl gnupg && mkdir -p /etc/apt/keyrings && "
    "curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/nodesource.gpg && "
    'echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && '
    "apt-get update -qq && apt-get install -y nodejs"
)
VSCODE = (
    "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y --no-install-recommends"
    " ca-certificates curl gpg apt-transport-https && mkdir -p /etc/apt/keyrings && "
    "curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --yes -o /etc/apt/keyrings/packages.microsoft.gpg && "
    'echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list && '
    "apt-get update -qq && apt-get install -y code"
)

# id, name, category, description, install script, check command (exit 0 when present), optional launch
# command (run as the desktop user on DISPLAY=:0), optional remove script, optional prerequisites.
CATALOG = [
    {
        "id": "firefox",
        "name": "Firefox ESR",
        "category": "Browsers",
        "description": "Mozilla Firefox, alongside the built-in Chromium.",
        "install": f"{APT} firefox-esr",
        "check": "command -v firefox-esr",
        "launch": "firefox-esr",
        "remove": "apt-get remove -y firefox-esr",
    },
    {
        "id": "vscode",
        "name": "Visual Studio Code",
        "category": "Development",
        "description": "Microsoft's editor from the official apt repository.",
        "install": VSCODE,
        "check": "command -v code",
        "launch": "code --no-sandbox",
        "remove": "apt-get remove -y code",
    },
    {
        "id": "nodejs",
        "name": "Node.js 22",
        "category": "Development",
        "description": "Node.js and npm from NodeSource.",
        "install": NODESOURCE,
        "check": "command -v node && node --version",
        "remove": "apt-get remove -y nodejs",
    },
    {
        "id": "python-data",
        "name": "Python data tools",
        "category": "Development",
        "description": "A virtualenv at /opt/venvs/data with numpy, pandas, matplotlib and JupyterLab.",
        "install": (
            f"{APT} python3-venv python3-pip && python3 -m venv /opt/venvs/data && "
            "/opt/venvs/data/bin/pip install --no-cache-dir numpy pandas matplotlib jupyterlab && "
            "ln -sf /opt/venvs/data/bin/jupyter /usr/local/bin/jupyter && chown -R desktop:desktop /opt/venvs/data"
        ),
        "check": "test -x /opt/venvs/data/bin/python",
        "remove": "rm -rf /opt/venvs/data /usr/local/bin/jupyter",
    },
    {
        "id": "git-tools",
        "name": "Git and GitHub CLI",
        "category": "Development",
        "description": "git, gh and build essentials.",
        "install": f"{APT} git gh build-essential",
        "check": "command -v git && command -v gh",
        "remove": "apt-get remove -y gh",
    },
    {
        "id": "libreoffice",
        "name": "LibreOffice",
        "category": "Office",
        "description": "Writer, Calc and Impress.",
        "install": f"{APT} libreoffice libreoffice-gtk3",
        "check": "command -v libreoffice",
        "launch": "libreoffice",
        "remove": "apt-get remove -y libreoffice-core",
    },
    {
        "id": "gimp",
        "name": "GIMP",
        "category": "Media",
        "description": "Image editing.",
        "install": f"{APT} gimp",
        "check": "command -v gimp",
        "launch": "gimp",
        "remove": "apt-get remove -y gimp",
    },
    {
        "id": "vlc",
        "name": "VLC",
        "category": "Media",
        "description": "Media player.",
        "install": f"{APT} vlc",
        "check": "command -v vlc",
        "launch": "vlc",
        "remove": "apt-get remove -y vlc",
    },
    {
        "id": "media-tools",
        "name": "ffmpeg, ImageMagick, Tesseract",
        "category": "Media",
        "description": "Command-line media conversion and OCR for agents.",
        "install": f"{APT} ffmpeg imagemagick tesseract-ocr",
        "check": "command -v ffmpeg && command -v convert && command -v tesseract",
        "remove": "apt-get remove -y ffmpeg imagemagick tesseract-ocr",
    },
    {
        "id": "openclaw",
        "name": "OpenClaw",
        "category": "Agents",
        "description": "The OpenClaw agent CLI (npm). Bring its keys as workspace secrets.",
        "install": "npm install -g openclaw",
        "check": "command -v openclaw",
        "remove": "npm uninstall -g openclaw",
        "requires": ["nodejs"],
    },
]
BY_ID = {app["id"]: app for app in CATALOG}
ROOT = "/opt/cubicle/apps"
LOG_LIMIT = 64_000
POLL_EVERY = timedelta(seconds=5)


class AppInstall(Base):
    __tablename__ = "app_installs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    computer_id: Mapped[str] = mapped_column(ForeignKey("computers.id"), index=True)
    app_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String, default="queued")
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def catalog_public(app):
    return {k: app[k] for k in ("id", "name", "category", "description") if k in app} | {
        "launchable": "launch" in app,
        "removable": "remove" in app,
        "requires": app.get("requires", []),
    }


def install_public(i):
    return {
        "id": i.id,
        "app_id": i.app_id,
        "status": i.status,
        "error": i.error,
        "log": i.log[-8000:],
        "created_at": i.created_at,
        "updated_at": i.updated_at,
    }


def current(db, cid):
    """Latest install row per app for one computer."""
    rows = db.scalars(select(AppInstall).where(AppInstall.computer_id == cid).order_by(AppInstall.created_at))
    latest = {}
    for row in rows:
        latest[row.app_id] = row
    return latest


def detached(script, install_id):
    """Run a recipe in the background; its log and exit code stay on the computer for polling."""
    log, code = f"{ROOT}/{install_id}.log", f"{ROOT}/{install_id}.exit"
    body = f"{script}\necho __CUBICLE_EXIT__=$?"
    return (
        f"mkdir -p {ROOT} && printf %s {shlex.quote(body)} > {ROOT}/{install_id}.sh && rm -f {code} && "
        f"(nohup sh -c 'sh {ROOT}/{install_id}.sh > {log} 2>&1; tail -n 1 {log} | sed s/.*=// > {code}' >/dev/null 2>&1 &)"
    )


def poll_command(install_id):
    # Always exit 0: a missing exit file just means the recipe is still running.
    return (
        f"tail -c {LOG_LIMIT} {ROOT}/{install_id}.log 2>/dev/null; echo; echo __POLL__; "
        f"cat {ROOT}/{install_id}.exit 2>/dev/null; true"
    )


async def poll(db, c):
    """Mirror running installs into the database. Called by the lifecycle worker for running computers."""
    active = [
        i
        for i in db.scalars(
            select(AppInstall).where(AppInstall.computer_id == c.id, AppInstall.status.in_(["installing", "removing"]))
        )
        if now() - i.updated_at >= POLL_EVERY
    ]
    for i in active:
        output = await runtime.execute(c.sandbox_id, poll_command(i.id))
        log, _, exit_code = output.rpartition("__POLL__")
        i.log = log.strip()[-LOG_LIMIT:]
        i.updated_at = now()
        code = exit_code.strip()
        if code:
            app = BY_ID.get(i.app_id, {"name": i.app_id})
            if code == "0":
                i.status = "installed" if i.status == "installing" else "removed"
                event(db, c.id, f"{app['name']} {i.status}", "info")
            else:
                i.status = "failed"
                i.error = f"Recipe exited with status {code}; see the log"
                event(db, c.id, f"{app['name']} install failed (exit {code})", "error")
    if active:
        db.commit()


def running_owner(db, cid, user):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user, owner=True)
    if c.status != "running" or not c.sandbox_id:
        raise HTTPException(409, "Start the computer first")
    return c


@router.get("/apps")
def catalog():
    return [catalog_public(app) for app in CATALOG]


@router.get("/computers/{cid}/apps")
def computer_apps(cid: str, user=Depends(identity), db=Depends(database)):
    c = db.get(Computer, cid)
    if not c or c.status == "deleted":
        raise HTTPException(404, "Computer not found")
    member(db, c.workspace_id, user)
    latest = current(db, cid)
    return [
        {**catalog_public(app), "install": install_public(latest[app["id"]]) if app["id"] in latest else None}
        for app in CATALOG
    ]


@router.post("/computers/{cid}/apps/{app_id}/install", status_code=202)
async def install(cid: str, app_id: str, user=Depends(identity), db=Depends(database)):
    app = BY_ID.get(app_id)
    if not app:
        raise HTTPException(404, "Unknown app")
    from .providers import require_for

    c = running_owner(db, cid, user)
    require_for(db, cid, "apps")
    latest = current(db, cid)
    if app_id in latest and latest[app_id].status in ("installing", "removing"):
        raise HTTPException(409, "This app is already being changed")
    if any(latest.get(r) is None or latest[r].status != "installed" for r in app.get("requires", [])):
        raise HTTPException(409, "Install " + ", ".join(BY_ID[r]["name"] for r in app["requires"]) + " first")
    row = AppInstall(computer_id=cid, app_id=app_id, status="installing")
    db.add(row)
    db.flush()
    await runtime.execute(c.sandbox_id, detached(app["install"], row.id))
    row.updated_at = now() - POLL_EVERY
    event(db, cid, f"Installing {app['name']}", "activity")
    db.commit()
    return install_public(row)


@router.post("/computers/{cid}/apps/{app_id}/remove", status_code=202)
async def remove(cid: str, app_id: str, user=Depends(identity), db=Depends(database)):
    app = BY_ID.get(app_id)
    if not app or "remove" not in app:
        raise HTTPException(404, "This app cannot be removed")
    c = running_owner(db, cid, user)
    latest = current(db, cid)
    if app_id not in latest or latest[app_id].status != "installed":
        raise HTTPException(409, "This app is not installed")
    row = AppInstall(computer_id=cid, app_id=app_id, status="removing")
    db.add(row)
    db.flush()
    await runtime.execute(c.sandbox_id, detached(app["remove"], row.id))
    row.updated_at = now() - POLL_EVERY
    event(db, cid, f"Removing {app['name']}", "activity")
    db.commit()
    return install_public(row)


@router.post("/computers/{cid}/apps/{app_id}/launch")
async def launch(cid: str, app_id: str, screen: int = 0, user=Depends(identity), db=Depends(database)):
    app = BY_ID.get(app_id)
    if not app or "launch" not in app:
        raise HTTPException(404, "This app has no desktop launcher")
    c = operator(db, cid, user)
    latest = current(db, cid)
    if app_id not in latest or latest[app_id].status != "installed":
        raise HTTPException(409, "Install the app first")
    from .screens import display, require_screen

    require_screen(db, cid, screen)
    command = f"DISPLAY={display(screen)} HOME=/home/desktop nohup {app['launch']} >/dev/null 2>&1 &"
    await runtime.execute(c.sandbox_id, "runuser -u desktop -- sh -c " + shlex.quote(command))
    c.last_active = now()
    event(db, cid, f"Launched {app['name']}", "activity")
    db.commit()
    return {"ok": True}


@router.post("/computers/{cid}/apps/check")
async def check(cid: str, user=Depends(identity), db=Depends(database)):
    """Re-verify installed apps against the live system (for example after manual changes)."""
    c = operator(db, cid, user)
    latest = {k: v for k, v in current(db, cid).items() if v.status in ("installed", "failed")}
    if not latest:
        return {"checked": 0, "missing": []}
    probes = "; ".join(
        f"({BY_ID[a]['check']}) >/dev/null 2>&1 && echo {a}=ok || echo {a}=missing" for a in latest if a in BY_ID
    )
    output = await runtime.execute(c.sandbox_id, probes)
    missing = []
    for line in output.splitlines():
        app_id, _, state = line.strip().partition("=")
        if app_id in latest:
            if state == "ok" and latest[app_id].status != "installed":
                latest[app_id].status = "installed"
                latest[app_id].error = None
            elif state == "missing" and latest[app_id].status == "installed":
                latest[app_id].status = "failed"
                latest[app_id].error = "Not found on the system anymore"
                missing.append(app_id)
    db.commit()
    return {"checked": len(latest), "missing": missing}

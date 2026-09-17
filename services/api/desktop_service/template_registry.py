"""Versioned template definitions: declarative, immutable recipes built into launchable system templates.

A definition is a named series of versions. Each version stores its exact spec and a SHA-256 digest of
the canonical spec; submitting an identical spec returns the existing version instead of rebuilding.
The worker builds a version in a disposable helper sandbox from the clean desktop image, keeps the
build log, and snapshots the result. A ready version is an ordinary DesktopTemplate, so computers are
created from it through the existing /templates/{id}/computers route, which also enforces the
version's required secrets.

Specs never carry secret values: declare names in requires_secrets and store the values as workspace
secrets, which reach computers at boot instead of being baked into the snapshot.
"""

import base64
import hashlib
import json
import re
import shlex
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from . import apps
from .db import database
from .display import Resolution
from .feature_models import DesktopTemplate, FeatureJob
from .secrets_vault import RESERVED, Secret
from .security import identity, member

router = APIRouter(prefix="/v1")

MAX_DEFINITIONS = 10
MAX_VERSIONS = 20
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9.+\-]{0,99}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class TemplateFile(BaseModel):
    path: str = Field(min_length=2, max_length=512)
    content: str = Field(max_length=200_000)
    mode: str = Field(default="0644", pattern=r"^0[0-7]{3}$")

    @field_validator("path")
    @classmethod
    def system_path(cls, value):
        if not value.startswith("/") or ".." in value.split("/") or "\x00" in value:
            raise ValueError("Files need an absolute path without '..'")
        if value == "/home/desktop" or value.startswith("/home/desktop/"):
            raise ValueError("Home is a separate persistent volume and is not part of templates")
        if value.startswith(("/proc/", "/sys/", "/dev/")):
            raise ValueError("Virtual filesystems cannot be written")
        return value


class TemplateSpec(BaseModel):
    description: str = Field(default="", max_length=500)
    apps: list[str] = Field(default=[], max_length=len(apps.CATALOG))
    packages: list[str] = Field(default=[], max_length=100)
    files: list[TemplateFile] = Field(default=[], max_length=50)
    run: list[str] = Field(default=[], max_length=50)
    startup: list[str] = Field(default=[], max_length=20)
    env: dict[str, str] = Field(default={}, max_length=50)
    requires_secrets: list[str] = Field(default=[], max_length=50)
    cpu: Literal[1, 2] = 2
    memory_gib: Literal[2, 4] = 4
    storage_gib: Literal[20, 50, 100] = 20
    resolution: Resolution = "1440x900"
    idle_timeout_minutes: int = Field(default=15, ge=0, le=1440)

    @field_validator("apps")
    @classmethod
    def known_apps(cls, value):
        unknown = [a for a in value if a not in apps.BY_ID]
        if unknown:
            raise ValueError("Unknown catalog apps: " + ", ".join(unknown))
        return value

    @field_validator("packages")
    @classmethod
    def package_names(cls, value):
        bad = [p for p in value if not PACKAGE.match(p)]
        if bad:
            raise ValueError("Invalid Debian package names: " + ", ".join(bad))
        return value

    @field_validator("run", "startup")
    @classmethod
    def bounded_steps(cls, value):
        if any(not step.strip() or len(step) > 8000 for step in value):
            raise ValueError("Steps must be non-empty and at most 8000 characters")
        return value

    @field_validator("env")
    @classmethod
    def env_names(cls, value):
        bad = [k for k in value if not ENV_NAME.match(k) or k in RESERVED or len(value[k]) > 4000]
        if bad:
            raise ValueError("Invalid or reserved environment names: " + ", ".join(bad))
        return value

    @field_validator("requires_secrets")
    @classmethod
    def secret_names(cls, value):
        bad = [k for k in value if not ENV_NAME.match(k) or k in RESERVED]
        if bad:
            raise ValueError("Invalid secret names: " + ", ".join(bad))
        return sorted(set(value))


class DefinitionBody(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    spec: TemplateSpec


STARTERS = [
    {
        "id": "web-research",
        "name": "Web research",
        "spec": {
            "description": "Firefox next to Chromium, plus OCR and media conversion for saving findings.",
            "apps": ["firefox", "media-tools"],
            "packages": ["jq", "pandoc"],
        },
    },
    {
        "id": "python-data",
        "name": "Python data workstation",
        "spec": {
            "description": "Jupyter-ready data virtualenv, VS Code and git.",
            "apps": ["python-data", "vscode", "git-tools"],
            "resolution": "1920x1080",
        },
    },
    {
        "id": "agent-dev",
        "name": "Agent developer box",
        "spec": {
            "description": "Node.js 22, OpenClaw, git and VS Code. Supply provider keys as workspace secrets.",
            "apps": ["nodejs", "openclaw", "git-tools", "vscode"],
            "requires_secrets": ["ANTHROPIC_API_KEY"],
        },
    },
    {
        "id": "office",
        "name": "Office and media",
        "spec": {
            "description": "LibreOffice, GIMP and VLC.",
            "apps": ["libreoffice", "gimp", "vlc"],
        },
    },
]


def canonical(spec: TemplateSpec):
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def digest(spec: TemplateSpec):
    return "sha256:" + hashlib.sha256(canonical(spec).encode()).hexdigest()


def ordered_apps(names):
    """Catalog apps in install order, pulling in prerequisites that were not listed."""
    order, seen = [], set()

    def visit(app_id):
        if app_id in seen:
            return
        seen.add(app_id)
        for requirement in apps.BY_ID[app_id].get("requires", []):
            visit(requirement)
        order.append(app_id)

    for name in names:
        visit(name)
    return order


def write_file(path, content, mode):
    payload = base64.b64encode(content.encode()).decode()
    directory = path.rsplit("/", 1)[0] or "/"
    return (
        f"mkdir -p {shlex.quote(directory)} && printf %s {payload} | base64 -d > {shlex.quote(path)} && "
        f"chmod {mode} {shlex.quote(path)}"
    )


def build_script(name, version, spec: TemplateSpec):
    """Root shell script run once in the helper sandbox. Every step must succeed."""
    steps = ["set -eu", "export DEBIAN_FRONTEND=noninteractive", "mkdir -p /opt/cubicle"]
    if spec.packages:
        steps.append("echo '== packages'")
        steps.append("apt-get update -qq && apt-get install -y --no-install-recommends " + " ".join(spec.packages))
    for app_id in ordered_apps(spec.apps):
        steps.append(f"echo '== app {app_id}'")
        steps.append(f"( {apps.BY_ID[app_id]['install']} )")
    for f in spec.files:
        steps.append("echo " + shlex.quote(f"== file {f.path}"))
        steps.append(write_file(f.path, f.content, f.mode))
    if spec.env:
        exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in sorted(spec.env.items()))
        steps.append(write_file("/etc/profile.d/cubicle-template-env.sh", exports, "0644"))
    for index, step in enumerate(spec.run, 1):
        steps.append(f"echo '== run step {index}'")
        steps.append("sh -euc " + shlex.quote(step))
    if spec.startup:
        script = "#!/bin/sh\n" + "".join(f"( {s} ) >> /tmp/cubicle-startup.log 2>&1 &\n" for s in spec.startup)
        steps.append(write_file("/opt/cubicle/startup.sh", script, "0755"))
        autostart = (
            "[Desktop Entry]\nType=Application\nName=Cubicle template startup\n"
            "Exec=/bin/sh -lc /opt/cubicle/startup.sh\nX-GNOME-Autostart-enabled=true\n"
        )
        steps.append(write_file("/etc/xdg/autostart/cubicle-startup.desktop", autostart, "0644"))
    metadata = json.dumps({"name": name, "version": version, "digest": digest(spec)})
    steps.append(write_file("/opt/cubicle/template.json", metadata, "0644"))
    steps.append("apt-get clean && rm -rf /var/lib/apt/lists/*")
    steps.append("echo '== build complete'")
    return "\n".join(steps) + "\n"


def version_public(t, detail=False):
    body = {
        "id": t.id,
        "name": t.name,
        "definition_id": t.definition_id,
        "version": t.version,
        "digest": t.digest,
        "status": t.status,
        "requires_secrets": t.requires_secrets or [],
        "created_at": t.created_at,
    }
    if detail:
        body |= {"spec": t.spec, "build_log": (t.build_log or "")[-20000:]}
    return body


def missing_secrets(db, t):
    if not t.requires_secrets:
        return []
    present = set(db.scalars(select(Secret.name).where(Secret.workspace_id == t.workspace_id)))
    return [name for name in t.requires_secrets if name not in present]


@router.get("/template-starters")
def starters():
    return [
        {**s, "spec": TemplateSpec(**s["spec"]).model_dump(mode="json"), "digest": digest(TemplateSpec(**s["spec"]))}
        for s in STARTERS
    ]


@router.get("/workspaces/{wid}/template-definitions")
def definitions(wid: str, user=Depends(identity), db=Depends(database)):
    member(db, wid, user)
    rows = db.scalars(
        select(DesktopTemplate)
        .where(DesktopTemplate.workspace_id == wid, DesktopTemplate.definition_id.is_not(None))
        .order_by(DesktopTemplate.name, DesktopTemplate.version.desc())
    )
    grouped = {}
    for t in rows:
        entry = grouped.setdefault(t.definition_id, {"id": t.definition_id, "name": t.name, "versions": []})
        if t.status != "deleted":
            entry["versions"].append(version_public(t))
    return [g for g in grouped.values() if g["versions"]]


@router.post("/workspaces/{wid}/template-definitions", status_code=202)
def publish(
    wid: str,
    body: DefinitionBody,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    member(db, wid, user, owner=True, lock=True)
    previous_job = db.scalar(
        select(FeatureJob).where(FeatureJob.workspace_id == wid, FeatureJob.request_id == idempotency_key)
    )
    if previous_job:
        return {"template": version_public(db.get(DesktopTemplate, previous_job.template_id)), "built": False}
    name = body.name.strip()
    series = db.scalars(
        select(DesktopTemplate)
        .where(
            DesktopTemplate.workspace_id == wid,
            DesktopTemplate.name == name,
            DesktopTemplate.definition_id.is_not(None),
        )
        .order_by(DesktopTemplate.version.desc())
    ).all()
    spec_digest = digest(body.spec)
    live = [t for t in series if t.status != "deleted"]
    same = next((t for t in live if t.digest == spec_digest and t.status in ("building", "ready")), None)
    if same:
        return {"template": version_public(same), "built": False}
    if not series:
        definitions_count = db.scalar(
            select(func.count(func.distinct(DesktopTemplate.definition_id))).where(
                DesktopTemplate.workspace_id == wid,
                DesktopTemplate.definition_id.is_not(None),
                DesktopTemplate.status != "deleted",
            )
        )
        if definitions_count >= MAX_DEFINITIONS:
            raise HTTPException(409, f"A workspace holds at most {MAX_DEFINITIONS} template definitions")
    elif len(live) >= MAX_VERSIONS:
        raise HTTPException(409, f"Delete old versions first; a definition keeps at most {MAX_VERSIONS}")
    spec = body.spec
    t = DesktopTemplate(
        workspace_id=wid,
        name=name,
        status="building",
        definition_id=series[0].definition_id if series else None,
        version=(series[0].version or 0) + 1 if series else 1,
        digest=spec_digest,
        spec=spec.model_dump(mode="json"),
        requires_secrets=spec.requires_secrets,
        build_log="",
        cpu=spec.cpu,
        memory_gib=spec.memory_gib,
        storage_gib=spec.storage_gib,
        resolution=spec.resolution,
        idle_timeout_minutes=spec.idle_timeout_minutes,
    )
    db.add(t)
    db.flush()
    if not t.definition_id:
        t.definition_id = t.id
    db.add(FeatureJob(workspace_id=wid, request_id=idempotency_key, kind="build", template_id=t.id))
    db.commit()
    return {"template": version_public(t), "built": True}


@router.get("/templates/{tid}")
def template_detail(tid: str, user=Depends(identity), db=Depends(database)):
    t = db.get(DesktopTemplate, tid)
    if not t or t.status == "deleted":
        raise HTTPException(404, "Template not found")
    member(db, t.workspace_id, user)
    if not t.definition_id:
        return {**version_public(t), "spec": None, "build_log": None}
    return {**version_public(t, detail=True), "missing_secrets": missing_secrets(db, t)}


@router.post("/templates/{tid}/rebuild", status_code=202)
def rebuild(
    tid: str,
    user=Depends(identity),
    db=Depends(database),
    idempotency_key: str = Header(min_length=8, max_length=100),
):
    t = db.get(DesktopTemplate, tid)
    if not t or not t.definition_id or t.status == "deleted":
        raise HTTPException(404, "Template version not found")
    member(db, t.workspace_id, user, owner=True, lock=True)
    db.refresh(t)
    if t.status != "failed":
        raise HTTPException(409, "Only failed builds can be retried; publish a changed spec for a new version")
    t.status, t.build_log = "building", ""
    db.add(FeatureJob(workspace_id=t.workspace_id, request_id=idempotency_key, kind="build", template_id=t.id))
    db.commit()
    return version_public(t)

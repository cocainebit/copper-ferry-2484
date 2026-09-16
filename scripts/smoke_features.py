"""Real, destructive-to-its-own-fixtures feature smoke test (development only).

Run from services/api:
  .venv/bin/python ../../scripts/smoke_features.py

Requires the API, singleton worker, OpenSandbox, and built desktop image. Creates
one uniquely named temporary workspace, tests real system/home copies and cgroup
limits, then deletes only its own computers/templates through the API. Database
audit records and the empty workspace remain. Never modifies existing desktops.
"""

import json
import os
import shlex
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
from desktop_service.config import settings
from desktop_service.db import Member, Session, Workspace


def wait_for(fetch, ready, description, timeout=1200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fetch()
        if ready(value):
            return value
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for {description}; last state: {value!r}")


def main():
    s = settings()
    if not s.dev_mode:
        raise RuntimeError("This test creates development credits and requires DEV_MODE=true")
    run_id = str(uuid4())
    wid = "feature-smoke-" + run_id
    computer_ids = set()
    template_ids = set()
    api_url = os.environ.get("SMOKE_API_URL", "http://127.0.0.1:8000").rstrip("/")
    client = httpx.Client(base_url=api_url, timeout=75, headers={"Authorization": "Bearer " + s.dev_token})

    def call(method, path, body=None):
        r = client.request(method, "/v1" + path, json=body, headers={"Idempotency-Key": str(uuid4())})
        r.raise_for_status()
        return r.json()

    def computers():
        return call("GET", f"/workspaces/{wid}/computers")

    def computer(cid):
        return next((c for c in computers() if c["id"] == cid), None)

    def state(cid, wanted):
        def ready(c):
            if c and c["status"] in ("failed", "copy_failed"):
                raise RuntimeError(f"Computer {cid} failed: {c.get('error')}")
            return c is not None and c["status"] == wanted

        return wait_for(lambda: computer(cid), ready, f"computer {cid} {wanted}")

    def action(cid, name):
        return call("POST", f"/computers/{cid}/actions/{name}")

    def start(cid):
        action(cid, "start")
        state(cid, "running")
        action(cid, "take-control")

    def stop(cid):
        action(cid, "stop")
        state(cid, "stopped")

    def terminal(cid, command):
        return call("POST", f"/computers/{cid}/terminal", {"command": command})["output"]

    def job(j):
        if j.get("target_id"):
            computer_ids.add(j["target_id"])
        if j.get("template_id"):
            template_ids.add(j["template_id"])

        def ready(rows):
            current = next(row for row in rows if row["id"] == j["id"])
            if current["status"] == "failed":
                raise RuntimeError(f"Feature job failed: {current}")
            return current["status"] == "completed"

        wait_for(lambda: call("GET", f"/workspaces/{wid}/feature-jobs"), ready, f"job {j['id']}")
        return j

    def delete_computer(cid):
        c = computer(cid)
        if not c:
            return
        # Never race a copy helper. The worker resolves interrupted helpers after
        # their lifetime; cleanup can wait for that rather than overriding locks.
        c = wait_for(
            lambda: computer(cid),
            lambda c: c is None or c["status"] not in ("copying", "customizing", "starting", "stopping"),
            f"computer {cid} ready for cleanup",
        )
        if not c:
            return
        r = client.delete(f"/v1/computers/{cid}", params={"confirm": c["name"]})
        r.raise_for_status()
        wait_for(lambda: computer(cid), lambda c: c is None, f"computer {cid} deleted")

    # Verify the API before creating any database fixtures.
    config = call("GET", "/config")
    if not config["dev_mode"]:
        raise RuntimeError("Refusing to test a production API")
    with Session() as db:
        db.add(Workspace(id=wid, name="Feature smoke " + run_id[:8], subscription="active", included=6000))
        db.flush()
        db.add(Member(workspace_id=wid, user_id="local-user", email="you@localhost", role="owner"))
        db.commit()
    print(f"Temporary workspace: {wid}", flush=True)
    try:
        call("GET", f"/workspaces/{wid}/templates")
        source = call("POST", f"/workspaces/{wid}/computers", {"name": "Smoke source"})["id"]
        computer_ids.add(source)
        call("PUT", f"/computers/{source}/profile", {"cpu": 1, "memory_gib": 2})
        start(source)
        marker = shlex.quote(run_id)
        terminal(
            source,
            f"printf %s {marker} > /home/desktop/.feature-smoke-home; printf %s {marker} > /opt/feature-smoke-system",
        )
        limits = terminal(
            source,
            "python3 - <<'PY'\nimport json\nfrom pathlib import Path\nprint(json.dumps({'cpu':Path('/sys/fs/cgroup/cpu.max').read_text().strip(),'memory':Path('/sys/fs/cgroup/memory.max').read_text().strip()}))\nPY",
        )
        parsed = json.loads(limits)
        quota, period = parsed["cpu"].split()
        assert quota != "max" and int(quota) == int(period), f"Expected 1 CPU: {parsed}"
        assert int(parsed["memory"]) == 2 * 1024**3, f"Expected 2 GiB RAM: {parsed}"
        stop(source)
        print("PASS: configured CPU/RAM enforced inside real sandbox", flush=True)

        clone_job = job(call("POST", f"/computers/{source}/clone", {"name": "Smoke clone"}))
        clone = clone_job["target_id"]
        start(clone)
        assert terminal(clone, "cat /home/desktop/.feature-smoke-home") == run_id
        assert terminal(clone, "cat /opt/feature-smoke-system") == run_id
        terminal(
            clone, "printf changed > /home/desktop/.feature-smoke-home; printf changed > /opt/feature-smoke-system"
        )
        stop(clone)
        start(source)
        assert terminal(source, "cat /home/desktop/.feature-smoke-home") == run_id
        assert terminal(source, "cat /opt/feature-smoke-system") == run_id
        stop(source)
        delete_computer(clone)
        print("PASS: real clone includes home/system, changes isolated from source", flush=True)

        template_job = job(call("POST", f"/computers/{source}/templates", {"name": "Smoke system template"}))
        tid = template_job["template_id"]
        instance_job = job(call("POST", f"/templates/{tid}/computers", {"name": "Smoke template instance"}))
        instance = instance_job["target_id"]
        start(instance)
        assert terminal(instance, "cat /opt/feature-smoke-system") == run_id
        assert (
            terminal(
                instance, "if test -e /home/desktop/.feature-smoke-home; then printf leaked; else printf clean; fi"
            )
            == "clean"
        )
        stop(instance)
        job(call("DELETE", f"/templates/{tid}"))
        # A consumer must continue booting after its template's snapshot is deleted.
        start(instance)
        assert terminal(instance, "cat /opt/feature-smoke-system") == run_id
        stop(instance)
        print("PASS: template excludes home; consumer survives template deletion", flush=True)
        print("Feature integration checks passed.", flush=True)
    finally:
        failures = []
        for cid in sorted(computer_ids):
            try:
                delete_computer(cid)
            except Exception as exc:
                failures.append(f"computer {cid}: {exc}")
        for tid in sorted(template_ids):
            try:
                rows = call("GET", f"/workspaces/{wid}/templates")
                if any(t["id"] == tid for t in rows):
                    job(call("DELETE", f"/templates/{tid}"))
            except Exception as exc:
                failures.append(f"template {tid}: {exc}")
        client.close()
        if failures:
            print("Cleanup needs review (only this test's resources):\n" + "\n".join(failures), file=sys.stderr)
            raise RuntimeError("Feature smoke cleanup incomplete; see resource IDs above")
        else:
            print(f"Cleanup complete; audit records retained in {wid}", flush=True)


if __name__ == "__main__":
    main()

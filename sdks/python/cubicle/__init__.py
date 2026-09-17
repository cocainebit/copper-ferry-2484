"""Cubicle Python SDK: drive cloud computers with a workspace API key.

from cubicle import Cubicle
cube = Cubicle("http://localhost:8000", "cbk_...")
c = cube.computers(workspace_id)[0]
cube.start(c["id"]); cube.wait_for(c["id"])
open("shot.png", "wb").write(cube.screenshot(c["id"]))
cube.click(c["id"], 640, 400); cube.type(c["id"], "hello"); cube.key(c["id"], "Return")
print(cube.bash(c["id"], "ls -la")["output"])
"""

import base64
import time
import uuid

import httpx

__all__ = ["Cubicle", "CubicleError"]


class CubicleError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class Cubicle:
    def __init__(self, base_url, api_key, timeout=90.0):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(
            base_url=self.base_url + "/v1",
            headers={"Authorization": "Bearer " + api_key},
            timeout=timeout,
        )

    def request(self, method, path, json=None, idempotency_key=None, **kwargs):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        response = self.http.request(method, path, json=json, headers=headers, **kwargs)
        data = response.json() if response.content else None
        if response.is_error:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise CubicleError(
                response.status_code,
                detail if isinstance(detail, str) else f"HTTP {response.status_code}",
            )
        return data

    # Lifecycle
    def workspaces(self):
        return self.request("GET", "/workspaces")

    def computers(self, workspace_id):
        return self.request("GET", f"/workspaces/{workspace_id}/computers")

    def computer(self, cid):
        return self.request("GET", f"/computers/{cid}")

    def create(self, workspace_id, name, idempotency_key=None, **options):
        """Create a stopped computer. options: cpu, memory_gib, storage_gib, resolution, idle_timeout_minutes."""
        body = {"name": name, **options}
        return self.request(
            "POST",
            f"/workspaces/{workspace_id}/computers",
            body,
            idempotency_key or str(uuid.uuid4()),
        )

    def start(self, cid):
        return self.request("POST", f"/computers/{cid}/actions/start", idempotency_key=str(uuid.uuid4()))

    def stop(self, cid):
        return self.request("POST", f"/computers/{cid}/actions/stop", idempotency_key=str(uuid.uuid4()))

    def rename(self, cid, name):
        return self.request("PATCH", f"/computers/{cid}", {"name": name})

    def delete(self, cid, confirm_name):
        """Erases the home directory and saved system; the current name confirms the deletion."""
        return self.request(
            "DELETE",
            f"/computers/{cid}",
            params={"confirm": confirm_name},
            idempotency_key=str(uuid.uuid4()),
        )

    def wait_for(self, cid, statuses=("running",), timeout=180.0, interval=2.0):
        deadline = time.monotonic() + timeout
        while True:
            c = self.computer(cid)
            if c["status"] in statuses:
                return c
            if c["status"] in ("failed", "copy_failed"):
                raise CubicleError(409, c.get("error") or c["status"])
            if time.monotonic() > deadline:
                raise CubicleError(408, "Timed out waiting for " + "/".join(statuses))
            time.sleep(interval)

    # Control
    # Every input method takes screen: 0 is the primary display, extra screens are 1-3.
    def screenshot(self, cid, screen=0):
        """PNG bytes of a live display."""
        return base64.b64decode(self.screenshot_info(cid, screen)["image"])

    def screenshot_info(self, cid, screen=0):
        return self.request("POST", f"/computers/{cid}/screenshot", params={"screen": screen})

    def click(self, cid, x, y, button="left", count=1, screen=0):
        body = {"x": x, "y": y, "button": button, "count": count, "screen": screen}
        return self.request("POST", f"/computers/{cid}/click", body)

    def double_click(self, cid, x, y, screen=0):
        return self.click(cid, x, y, count=2, screen=screen)

    def right_click(self, cid, x, y, screen=0):
        return self.click(cid, x, y, button="right", screen=screen)

    def drag(self, cid, start, end, screen=0):
        body = {"from": list(start), "to": list(end), "screen": screen}
        return self.request("POST", f"/computers/{cid}/drag", body)

    def scroll(self, cid, x, y, direction="down", amount=3, screen=0):
        body = {"x": x, "y": y, "direction": direction, "amount": amount, "screen": screen}
        return self.request("POST", f"/computers/{cid}/scroll", body)

    def type(self, cid, text, screen=0):
        return self.request("POST", f"/computers/{cid}/type", {"text": text, "screen": screen})

    def key(self, cid, key, screen=0):
        """xdotool key syntax: Return, ctrl+l, alt+F4."""
        return self.request("POST", f"/computers/{cid}/key", {"key": key, "screen": screen})

    def bash(self, cid, command):
        """Returns output, error and exit_code; output is kept when the command fails. 45 second limit."""
        return self.request("POST", f"/computers/{cid}/bash", {"command": command})

    def wait(self, cid, seconds=1, screen=0):
        return self.request("POST", f"/computers/{cid}/wait", {"seconds": seconds, "screen": screen})

    # Screens
    def screens(self, cid):
        return self.request("GET", f"/computers/{cid}/screens")

    def add_screen(self, cid, resolution="1440x900"):
        return self.request("POST", f"/computers/{cid}/screens", {"resolution": resolution})

    def remove_screen(self, cid, screen):
        return self.request("DELETE", f"/computers/{cid}/screens/{screen}")

    # Apps
    def app_catalog(self):
        return self.request("GET", "/apps")

    def apps(self, cid):
        return self.request("GET", f"/computers/{cid}/apps")

    def install_app(self, cid, app_id):
        return self.request("POST", f"/computers/{cid}/apps/{app_id}/install")

    def remove_app(self, cid, app_id):
        return self.request("POST", f"/computers/{cid}/apps/{app_id}/remove")

    def launch_app(self, cid, app_id, screen=0):
        return self.request("POST", f"/computers/{cid}/apps/{app_id}/launch", params={"screen": screen})

    # Automations
    def automations(self, cid):
        return self.request("GET", f"/computers/{cid}/automations")

    def create_automation(self, cid, name, trigger, action, **options):
        """trigger and action are dicts, e.g. {"kind": "schedule", "cron": "0 9 * * *"}, {"kind": "command", ...}."""
        body = {"name": name, "trigger": trigger, "action": action, **options}
        return self.request("POST", f"/computers/{cid}/automations", body)

    def run_automation(self, automation_id):
        return self.request("POST", f"/automations/{automation_id}/run")

    def automation_runs(self, automation_id):
        return self.request("GET", f"/automations/{automation_id}/runs")

    def set_automation_enabled(self, automation_id, enabled):
        return self.request("PATCH", f"/automations/{automation_id}", {"enabled": enabled})

    def delete_automation(self, automation_id):
        return self.request("DELETE", f"/automations/{automation_id}")

    # Templates
    def template_starters(self):
        return self.request("GET", "/template-starters")

    def template_definitions(self, workspace_id):
        return self.request("GET", f"/workspaces/{workspace_id}/template-definitions")

    def publish_template(self, workspace_id, name, spec, idempotency_key=None):
        """Identical specs return the existing version; a changed spec builds the next version."""
        key = idempotency_key or str(uuid.uuid4())
        body = {"name": name, "spec": spec}
        return self.request("POST", f"/workspaces/{workspace_id}/template-definitions", body, key)

    def template(self, template_id):
        return self.request("GET", f"/templates/{template_id}")

    def create_from_template(self, template_id, name, idempotency_key=None, **options):
        key = idempotency_key or str(uuid.uuid4())
        return self.request("POST", f"/templates/{template_id}/computers", {"name": name, **options}, key)

    # Fleet
    def fleet(self, workspace_id, q="", status="", label=""):
        params = {"q": q, "status": status, "label": label}
        return self.request("GET", f"/workspaces/{workspace_id}/fleet", params=params)

    def set_labels(self, cid, labels):
        return self.request("PUT", f"/computers/{cid}/labels", {"labels": list(labels)})

    def bulk(self, workspace_id, ids, action, label=None):
        body = {"ids": list(ids), "action": action, **({"label": label} if label else {})}
        return self.request("POST", f"/workspaces/{workspace_id}/computers/bulk", body)

    def move(self, cid, workspace_id):
        return self.request("POST", f"/computers/{cid}/move", {"workspace_id": workspace_id})

    # Files
    def files(self, cid, path=""):
        return self.request("GET", f"/computers/{cid}/files", params={"path": path})

    def upload(self, cid, path, data: bytes):
        return self.request(
            "POST",
            f"/computers/{cid}/upload",
            {"path": path, "data": base64.b64encode(data).decode()},
        )

    def download(self, cid, path):
        r = self.request("GET", f"/computers/{cid}/download", params={"path": path})
        return r["name"], base64.b64decode(r["data"])

    def delete_file(self, cid, path):
        return self.request("POST", f"/computers/{cid}/delete-file", {"path": path})

    # Built-in agent
    def submit_task(self, cid, prompt):
        return self.request("POST", f"/computers/{cid}/runs", {"prompt": prompt}, str(uuid.uuid4()))

    def runs(self, cid):
        return self.request("GET", f"/computers/{cid}/runs")

    def events(self, cid, after=0):
        return self.request("GET", f"/computers/{cid}/events", params={"after": after})

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
        return self.request(
            "POST", f"/computers/{cid}/actions/start", idempotency_key=str(uuid.uuid4())
        )

    def stop(self, cid):
        return self.request(
            "POST", f"/computers/{cid}/actions/stop", idempotency_key=str(uuid.uuid4())
        )

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
    def screenshot(self, cid):
        """PNG bytes of the live desktop."""
        return base64.b64decode(
            self.request("POST", f"/computers/{cid}/screenshot")["image"]
        )

    def screenshot_info(self, cid):
        return self.request("POST", f"/computers/{cid}/screenshot")

    def click(self, cid, x, y, button="left", count=1):
        return self.request(
            "POST",
            f"/computers/{cid}/click",
            {"x": x, "y": y, "button": button, "count": count},
        )

    def double_click(self, cid, x, y):
        return self.click(cid, x, y, count=2)

    def right_click(self, cid, x, y):
        return self.click(cid, x, y, button="right")

    def drag(self, cid, start, end):
        return self.request(
            "POST", f"/computers/{cid}/drag", {"from": list(start), "to": list(end)}
        )

    def scroll(self, cid, x, y, direction="down", amount=3):
        return self.request(
            "POST",
            f"/computers/{cid}/scroll",
            {"x": x, "y": y, "direction": direction, "amount": amount},
        )

    def type(self, cid, text):
        return self.request("POST", f"/computers/{cid}/type", {"text": text})

    def key(self, cid, key):
        """xdotool key syntax: Return, ctrl+l, alt+F4."""
        return self.request("POST", f"/computers/{cid}/key", {"key": key})

    def bash(self, cid, command):
        """Returns {"output": str, "error": str | None}. Commands run as administrator with a 45 second limit."""
        return self.request("POST", f"/computers/{cid}/bash", {"command": command})

    def wait(self, cid, seconds=1):
        return self.request("POST", f"/computers/{cid}/wait", {"seconds": seconds})

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
        return self.request(
            "POST", f"/computers/{cid}/runs", {"prompt": prompt}, str(uuid.uuid4())
        )

    def runs(self, cid):
        return self.request("GET", f"/computers/{cid}/runs")

    def events(self, cid, after=0):
        return self.request("GET", f"/computers/{cid}/events", params={"after": after})

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

request = json.loads(base64.b64decode(sys.argv[1]))
name = request["name"]
args = request["input"]
os.environ["DISPLAY"] = ":0"


def run(*command):
    return subprocess.check_output(command, timeout=45).decode()


if name in ("list_files", "read_file", "write_file", "delete_file"):
    home = Path("/home/desktop").resolve()
    target = (home / args.get("path", "")).resolve()
    if not target.is_relative_to(home):
        raise ValueError("Path must stay inside Home")
    if name == "delete_file":
        if target == home:
            raise ValueError("Home itself cannot be deleted")
        if target.is_dir():
            raise ValueError("Delete files only")
        if not target.exists():
            raise ValueError("File not found")
        target.unlink()
        print(json.dumps({"name": target.name, "deleted": True}))
    elif name == "write_file":
        data = base64.b64decode(args.get("data", ""), validate=True)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("Upload must be no larger than 20 MB")
        if target.exists() and target.is_dir():
            raise ValueError("Upload path must be a file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(json.dumps({"name": target.name, "size": len(data)}))
    elif name == "read_file":
        if not target.is_file() or target.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Download must be a file no larger than 20 MB")
        print(json.dumps({"name": target.name, "data": base64.b64encode(target.read_bytes()).decode()}))
    else:
        result = []
        for path in sorted(target.iterdir()):
            if path.name.startswith(".") or path.is_symlink():
                continue
            try:
                result.append({"name": path.name, "size": path.stat().st_size, "directory": path.is_dir()})
            except OSError:
                continue
        print(json.dumps(result))
elif name == "browser":
    # Delegate to a dedicated venv, while retaining the same visible browser.
    if sys.executable != "/opt/tools/bin/python":
        os.execv("/opt/tools/bin/python", ["/opt/tools/bin/python", __file__, sys.argv[1]])
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        action = args["action"]
        if action == "navigate":
            page.goto(args["url"], wait_until="domcontentloaded", timeout=30000)
        elif action == "click":
            page.locator(args["selector"]).first.click(timeout=15000)
        elif action == "fill":
            page.locator(args["selector"]).first.fill(args["text"], timeout=15000)
        elif action != "inspect":
            raise ValueError("Unsupported browser action")
        print(json.dumps({"url": page.url, "title": page.title(), "text": page.locator("body").inner_text()[:16000]}))
elif name == "computer":
    action = args["action"]
    if action == "screenshot":
        with tempfile.TemporaryDirectory() as d:
            path = d + "/screen.png"
            run("scrot", path)
            print(base64.b64encode(Path(path).read_bytes()).decode())
    elif action == "mouse_move":
        x, y = args["coordinate"]
        print(run("xdotool", "mousemove", str(int(x)), str(int(y))))
    elif action in ("left_click", "right_click", "middle_click", "double_click", "triple_click"):
        if "coordinate" in args:
            x, y = args["coordinate"]
            run("xdotool", "mousemove", str(int(x)), str(int(y)))
        button = {"right_click": "3", "middle_click": "2"}.get(action, "1")
        repeats = {"double_click": "2", "triple_click": "3"}.get(action, "1")
        print(run("xdotool", "click", "--repeat", repeats, "--delay", "120", button) or "OK")
    elif action == "type":
        # Clipboard avoids keyboard-layout corruption for Unicode text.
        subprocess.run(["xclip", "-selection", "clipboard"], input=args["text"].encode(), check=True)
        print(run("xdotool", "key", "--clearmodifiers", "ctrl+v") or "OK")
    elif action == "key":
        print(run("xdotool", "key", "--clearmodifiers", args["text"]) or "OK")
    elif action == "scroll":
        button = {"up": "4", "down": "5", "left": "6", "right": "7"}[args["scroll_direction"]]
        print(run("xdotool", "click", "--repeat", str(min(100, int(args["scroll_amount"]))), button) or "OK")
    elif action == "left_click_drag":
        x, y = args["coordinate"]
        run("xdotool", "mousedown", "1")
        try:
            run("xdotool", "mousemove", str(int(x)), str(int(y)))
        finally:
            run("xdotool", "mouseup", "1")
        print("OK")
    elif action == "cursor_position":
        print(run("xdotool", "getmouselocation"))
    elif action == "wait":
        import time

        time.sleep(min(10, max(0, float(args.get("duration", 1)))))
        print("OK")
    else:
        raise ValueError("Unsupported computer action: " + action)
else:
    raise ValueError("Unsupported tool")

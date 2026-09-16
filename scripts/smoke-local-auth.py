#!/usr/bin/env python3
"""Exercise local mail delivery, OTP verification, JWKS, and backend identity.

Uses only the local Supabase stack. Never prints keys, email codes, or JWTs.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--application-api", choices=["http://127.0.0.1:8000", "http://localhost:8000"])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
result = subprocess.run(
    ["npx", "--yes", "supabase@2.117.0", "status", "-o", "json"],
    cwd=root,
    capture_output=True,
    text=True,
    check=True,
)
config = json.loads(result.stdout)
api_url = config["API_URL"]
if api_url not in ("http://127.0.0.1:55321", "http://localhost:55321"):
    raise RuntimeError("Refusing to run the local smoke test against a nonlocal auth service")
email = f"smoke-{uuid4().hex[:10]}@example.test"
with httpx.Client(timeout=20) as client:
    sent = client.post(
        api_url + "/auth/v1/otp",
        headers={"apikey": config["ANON_KEY"]},
        json={"email": email},
    )
    sent.raise_for_status()
    code = None
    for _ in range(20):
        inbox = client.get("http://127.0.0.1:55324/api/v1/messages")
        inbox.raise_for_status()
        for entry in inbox.json().get("messages", []):
            if not any(to.get("Address") == email for to in entry.get("To", [])):
                continue
            message = client.get("http://127.0.0.1:55324/api/v1/message/" + entry["ID"])
            message.raise_for_status()
            match = re.search(r"\b\d{8}\b", message.json().get("Text", ""))
            if match:
                code = match.group()
                break
        if code:
            break
        time.sleep(1)
    if not code:
        raise RuntimeError("No email code arrived in local mail inbox")
    verified = client.post(
        api_url + "/auth/v1/verify",
        headers={"apikey": config["ANON_KEY"]},
        json={"email": email, "token": code, "type": "email"},
    )
    verified.raise_for_status()
    session = verified.json()
    os.environ["DEV_MODE"] = "true"
    os.environ["SUPABASE_URL"] = api_url
    sys.path.insert(0, str(root / "services" / "api"))
    from desktop_service.security import identity
    from fastapi.security import HTTPAuthorizationCredentials

    user = identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials=session["access_token"]))
    assert user["id"] == session["user"]["id"]
    assert user["email"] == email
    if args.application_api:
        headers = {"Authorization": "Bearer " + session["access_token"]}
        own = client.get(args.application_api + "/v1/workspaces", headers=headers)
        own.raise_for_status()
        assert own.json() == [], "A fresh account must not inherit another user's workspace"
        denied = client.get(args.application_api + "/v1/workspaces/local-workspace/members", headers=headers)
        assert denied.status_code == 403, "A new user must not access the developer workspace"
        print("PASS: running application accepts signed session and enforces workspace isolation")
    refreshed = client.post(
        api_url + "/auth/v1/token?grant_type=refresh_token",
        headers={"apikey": config["ANON_KEY"]},
        json={"refresh_token": session["refresh_token"]},
    )
    refreshed.raise_for_status()
    logout = client.post(
        api_url + "/auth/v1/logout",
        headers={
            "apikey": config["ANON_KEY"],
            "Authorization": "Bearer " + refreshed.json()["access_token"],
        },
    )
    logout.raise_for_status()
print("PASS: local email code, session verification, backend JWKS identity, refresh, sign-out")

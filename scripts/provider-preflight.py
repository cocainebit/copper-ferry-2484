#!/usr/bin/env python3
"""Check a workspace's configured Anthropic model without generating billable tokens.

Reads encrypted credentials server-side and prints booleans only. It never prints
credentials, response bodies, provider errors, or tokens.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True, help="Workspace ID to inspect")
args = parser.parse_args()
api_directory = Path(__file__).resolve().parents[1] / "services" / "api"
os.chdir(api_directory)
sys.path.insert(0, str(api_directory))
status = {"database_accessible": False, "credential_configured": False, "model_accessible": False}
try:
    from desktop_service.config import settings
    from desktop_service.db import Credential, Session
    from desktop_service.security import unseal

    with Session() as db:
        credential = db.get(Credential, args.workspace)
        status["database_accessible"] = True
        status["credential_configured"] = credential is not None
        if credential:
            response = httpx.get(
                "https://api.anthropic.com/v1/models/" + quote(settings().anthropic_model, safe=""),
                headers={"x-api-key": unseal(credential.encrypted_key), "anthropic-version": "2023-06-01"},
                timeout=15,
            )
            status["model_accessible"] = response.status_code == 200
except Exception:
    # Operator can investigate server/provider configuration separately; no secret-bearing exception logs.
    pass
print(json.dumps(status))
raise SystemExit(0 if status["model_accessible"] else 1)

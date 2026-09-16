"""Isolated real API for browser tests; never touches the developer database."""

import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))
with tempfile.TemporaryDirectory(prefix="agent-desktop-e2e-") as directory:
    os.environ.update(
        DEV_MODE="true",
        DATABASE_URL="sqlite:///" + directory + "/test.db",
        PUBLIC_URL="http://127.0.0.1:3107",
        LAUNCH_ENABLED="false",
        TRIAL_ADAPTER_URL="",
        STRIPE_SECRET_KEY="",
    )
    import uvicorn

    uvicorn.run("desktop_service.main:app", host="127.0.0.1", port=8107)

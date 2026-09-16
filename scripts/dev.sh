#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
( cd services/api && .venv/bin/python -m desktop_service.upgrade )
( cd services/api && .venv/bin/uvicorn desktop_service.main:app --host 127.0.0.1 --port 8000 ) &
api_pid=$!
( cd services/api && .venv/bin/python -m desktop_service.worker ) &
worker_pid=$!
trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true' EXIT INT TERM
npm run dev

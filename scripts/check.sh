#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
npm run typecheck
npm run format:check
(cd services/api && .venv/bin/ruff check --config pyproject.toml desktop_service tests && .venv/bin/python -m pytest -q)
npm run build
npm run test:e2e

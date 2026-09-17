FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app/services/api
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-package opensandbox
# Only rail settings/code: no API database, browser or user credentials needed.
COPY services/api/desktop_service/config.py services/api/desktop_service/x402_rail.py ./desktop_service/
COPY scripts/run_x402_facilitator.py /app/scripts/run_x402_facilitator.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 X402_FACILITATOR_HOST=0.0.0.0
USER 65532:65532
CMD ["/app/services/api/.venv/bin/python", "/app/scripts/run_x402_facilitator.py"]

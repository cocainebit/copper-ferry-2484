FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY evm_verifier ./evm_verifier
USER 65532:65532
EXPOSE 8090
CMD ["/app/.venv/bin/uvicorn", "evm_verifier.main:app", "--host", "0.0.0.0", "--port", "8090"]

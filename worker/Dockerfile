# Build context is the repo root: docker build -f worker/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.7.19 AS uv

FROM python:3.12.8-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY shared ./shared
COPY api ./api
COPY worker ./worker
RUN uv sync --frozen --no-dev

FROM python:3.12.8-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
# The worker has no HTTP port; the check confirms the Python process is alive
# and can import its code. Kubernetes liveness is handled in the Helm chart.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import worker.main"
CMD ["python", "-m", "worker.main"]

# syntax=docker/dockerfile:1.7
# Build context: repository root. Playwright image is multi-arch (amd64 + arm64).
# Library version must equal image version (playwright 1.65.2); the browser logic lands with builder-sandbox.
ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright/python:v1.65.2-noble
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM ${PLAYWRIGHT_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=/usr/bin/python3
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --no-editable --package falcon-sandbox

FROM ${PLAYWRIGHT_IMAGE} AS runtime
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# pwuser (uid 1000) ships in the Playwright image; never run Chromium as root for untrusted sites.
USER pwuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["python", "-m", "falcon_core.healthcheck", "http://127.0.0.1:8000/healthz"]
CMD ["python", "-m", "falcon_sandbox.main"]

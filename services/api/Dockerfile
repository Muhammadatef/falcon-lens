# syntax=docker/dockerfile:1.7
# Build context: repository root (docker compose sets it). Multi-arch: python + uv images are.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12.12-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --no-editable --package falcon-api

FROM python:3.12.12-slim-trixie AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY data/brands.yaml /app/data/brands.yaml
COPY config/reporting_channels.yaml /app/config/reporting_channels.yaml
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV FALCON_BRANDS_YAML=/app/data/brands.yaml FL_REPORTING_CHANNELS=/app/config/reporting_channels.yaml
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["python", "-m", "falcon_core.healthcheck", "http://127.0.0.1:8000/healthz"]
CMD ["python", "-m", "falcon_api.main"]

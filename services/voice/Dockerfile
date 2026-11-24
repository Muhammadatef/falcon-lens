# syntax=docker/dockerfile:1.7
# Build context: repository root. Multi-arch (amd64 + arm64): faster-whisper, ctranslate2 and PyAV ship manylinux wheels for both.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12.12-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock .python-version ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --no-editable --package falcon-voice

FROM python:3.12.12-slim-trixie AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /models && chown 10001:10001 /models
COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FL_VOICE_MODEL_DIR=/models HF_HOME=/models/hf
USER 10001:10001
VOLUME /models
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["python", "-m", "falcon_core.healthcheck", "http://127.0.0.1:8000/healthz"]
CMD ["python", "-m", "falcon_voice.main"]

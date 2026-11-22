# syntax=docker/dockerfile:1.7
# Build context: repository root. Stdlib-only service: no third-party dependencies to install.
FROM python:3.12.12-slim-trixie AS builder
WORKDIR /src
COPY services/egress/src/falcon_egress /out/falcon_egress
RUN python -m compileall -q /out

FROM python:3.12.12-slim-trixie AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=builder /out /app
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 3128 8081
HEALTHCHECK --interval=15s --timeout=4s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=3).status == 200 else 1)"]
CMD ["python", "-m", "falcon_egress.main"]

# syntax=docker/dockerfile:1.7
# Build context: repository root. Stdlib only: no dependencies to pin or audit.
FROM python:3.12.12-slim-trixie
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY services/evals-exporter/exporter.py /app/exporter.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FL_EVALS_DIR=/data/published FL_EXPORTER_PORT=9109
USER 10001:10001
EXPOSE 9109
HEALTHCHECK --interval=15s --timeout=4s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9109/healthz', timeout=3).status == 200 else 1)"]
CMD ["python", "/app/exporter.py"]

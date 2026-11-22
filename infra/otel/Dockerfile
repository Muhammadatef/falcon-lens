# The upstream collector image is scratch (no shell, no wget), so a container HEALTHCHECK is
# impossible. Re-package the same binary on Alpine (multi-arch) to get one. Non-root.
FROM otel/opentelemetry-collector-contrib:0.165.0 AS upstream

FROM alpine:3.22
RUN adduser -D -H -u 10001 otel
COPY --from=upstream /otelcol-contrib /otelcol-contrib
USER 10001:10001
EXPOSE 4317 4318 8888 8889 13133
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:13133/"]
ENTRYPOINT ["/otelcol-contrib"]
CMD ["--config=/etc/otelcol/config.yml"]

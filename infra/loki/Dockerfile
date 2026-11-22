# The upstream Loki image contains only the binary (no shell/wget), so a container HEALTHCHECK is
# impossible. Re-package the same binary on Alpine (multi-arch) to get one. Non-root.
FROM grafana/loki:3.7.10 AS upstream

FROM alpine:3.22
RUN adduser -D -H -u 10001 loki \
    && mkdir -p /loki /etc/loki \
    && chown -R 10001:10001 /loki
COPY --from=upstream /usr/bin/loki /usr/bin/loki
USER 10001:10001
EXPOSE 3100
HEALTHCHECK --interval=15s --timeout=4s --start-period=30s --retries=5 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:3100/ready"]
ENTRYPOINT ["/usr/bin/loki"]
CMD ["-config.file=/etc/loki/loki.yml"]

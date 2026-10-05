FROM alpine:3.24
RUN apk add --no-cache webhook curl ca-certificates
COPY hooks.yaml /etc/webhook/hooks.yaml
COPY --chmod=0755 mirror-sync /usr/local/bin/mirror-sync
USER nobody
ENTRYPOINT ["webhook", "-hooks", "/etc/webhook/hooks.yaml", "-template", "-port", "9000", "-verbose"]

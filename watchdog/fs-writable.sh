#!/bin/sh
set -eu

probe_dir="${PROBE_DIR:-/var/lib/fs-watchdog}"
probe="$probe_dir/probe"

ok=true
mkdir -p "$probe_dir" 2>/dev/null || ok=false

if [ "$ok" = true ]; then
    if printf '%s\n' "$(date -u +%FT%TZ)" > "$probe" 2>/dev/null && [ -s "$probe" ]; then
        rm -f "$probe" 2>/dev/null || ok=false
    else
        ok=false
    fi
fi

[ "$ok" = true ] || echo "root filesystem is not writable" >&2

if [ -n "${GATUS_PUSH_URL:-}" ] && [ -n "${GATUS_TOKEN:-}" ]; then
    curl -fsS -m 10 -X POST "$GATUS_PUSH_URL?success=$ok" \
        -H "Authorization: Bearer $GATUS_TOKEN" >/dev/null || true
fi

[ "$ok" = true ]

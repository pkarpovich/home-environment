#!/bin/sh
set -eu

kit_dir="$(dirname "$(readlink -f "$0")")"
host="${BACKUP_HOST:?BACKUP_HOST is not set}"
host_dir="$kit_dir/hosts/$host"
dump_dir="${DUMP_DIR:-/var/backups/restic-dumps}"

report_gatus() {
    status=$?
    if [ -n "${GATUS_PUSH_URL:-}" ] && [ -n "${GATUS_TOKEN:-}" ]; then
        if [ "$status" -eq 0 ]; then ok=true; else ok=false; fi
        curl -fsS -m 10 -X POST "$GATUS_PUSH_URL?success=$ok" \
            -H "Authorization: Bearer $GATUS_TOKEN" >/dev/null || true
    fi
    exit "$status"
}
trap report_gatus EXIT

if [ -x "$host_dir/pre-backup.sh" ]; then
    "$host_dir/pre-backup.sh" "$dump_dir"
fi

restic cat config >/dev/null 2>&1 || restic init
restic unlock

restic backup \
    --files-from "$host_dir/includes.txt" \
    --exclude-file "$host_dir/excludes.txt" \
    --exclude-caches \
    --tag scheduled

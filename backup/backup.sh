#!/bin/sh
set -eu

kit_dir="$(dirname "$(readlink -f "$0")")"
host="${BACKUP_HOST:?BACKUP_HOST is not set}"
host_dir="$kit_dir/hosts/$host"
dump_dir="${DUMP_DIR:-/var/backups/restic-dumps}"

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

if [ -n "${TEXTFILE_DIR:-}" ] && [ -d "$TEXTFILE_DIR" ]; then
    tmp="$TEXTFILE_DIR/restic_backup.prom.tmp"
    {
        printf '# HELP restic_backup_last_success_timestamp_seconds Unix time of last successful restic backup\n'
        printf '# TYPE restic_backup_last_success_timestamp_seconds gauge\n'
        printf 'restic_backup_last_success_timestamp_seconds{backup_host="%s"} %s\n' "$host" "$(date +%s)"
    } > "$tmp"
    mv "$tmp" "$TEXTFILE_DIR/restic_backup.prom"
fi

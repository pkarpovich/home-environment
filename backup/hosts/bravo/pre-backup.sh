#!/bin/sh
set -eu

dump_dir="${1:?usage: pre-backup.sh <dump-dir>}"
mkdir -p "$dump_dir"

sqlite3 /home/tuclaw/tuclaw/data/tuclaw.db ".backup '$dump_dir/tuclaw.db.tmp'"
mv "$dump_dir/tuclaw.db.tmp" "$dump_dir/tuclaw.db"

for c in mattermost-db; do
    docker ps --format '{{.Names}}' | grep -qx "$c" || continue
    user="$(docker exec "$c" printenv POSTGRES_USER 2>/dev/null || echo postgres)"
    docker exec "$c" pg_dumpall -U "$user" | gzip > "$dump_dir/$c.sql.gz.tmp"
    mv "$dump_dir/$c.sql.gz.tmp" "$dump_dir/$c.sql.gz"
done

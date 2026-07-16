#!/bin/sh
set -eu

dump_dir="${1:?usage: pre-backup.sh <dump-dir>}"
mkdir -p "$dump_dir"

for c in content-collector-postgres youtube-postgres overcast-postgres pgvector; do
    docker ps --format '{{.Names}}' | grep -qx "$c" || continue
    user="$(docker exec "$c" printenv POSTGRES_USER)"
    docker exec "$c" pg_dumpall -U "$user" | gzip > "$dump_dir/$c.sql.gz.tmp"
    mv "$dump_dir/$c.sql.gz.tmp" "$dump_dir/$c.sql.gz"
done

for db in /home/pi/turtle-hub/.db/*.db /home/pi/magnet-feed-sync/.db/*.db /home/pi/home-environment/volumes/linkding/*.sqlite3; do
    [ -f "$db" ] || continue
    out="$dump_dir/sqlite$(printf %s "$db" | tr / _)"
    sqlite3 "$db" ".backup '$out.tmp'"
    mv "$out.tmp" "$out"
done

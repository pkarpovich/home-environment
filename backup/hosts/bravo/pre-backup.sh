#!/bin/sh
set -eu

dump_dir="${1:?usage: pre-backup.sh <dump-dir>}"
mkdir -p "$dump_dir"

sqlite3 /home/tuclaw/tuclaw/data/tuclaw.db ".backup '$dump_dir/tuclaw.db.tmp'"
mv "$dump_dir/tuclaw.db.tmp" "$dump_dir/tuclaw.db"

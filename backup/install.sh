#!/bin/sh
set -eu

host="${1:?usage: install.sh <alpha|bravo>}"
kit_dir="$(dirname "$(readlink -f "$0")")"
host_dir="$kit_dir/hosts/$host"

if [ ! -d "$host_dir" ]; then
    echo "unknown host: $host" >&2
    exit 1
fi

if ! command -v restic >/dev/null || ! command -v sqlite3 >/dev/null; then
    apt-get update -qq
    apt-get install -y -qq restic sqlite3
fi

mkdir -p /etc/restic /var/backups/restic-dumps /var/cache/restic
chmod 700 /etc/restic /var/backups/restic-dumps

if [ ! -f /etc/restic/repo-pass ]; then
    umask 077
    openssl rand -base64 32 > /etc/restic/repo-pass
    echo "generated /etc/restic/repo-pass - store a copy in the password manager" >&2
fi

if [ ! -f /etc/restic/env ]; then
    umask 077
    cat > /etc/restic/env <<EOF
RESTIC_REPOSITORY=rest:http://$host:TRANSPORT_PASSWORD@192.168.198.2:8000/$host
RESTIC_PASSWORD_FILE=/etc/restic/repo-pass
RESTIC_CACHE_DIR=/var/cache/restic
BACKUP_HOST=$host
DUMP_DIR=/var/backups/restic-dumps
GATUS_PUSH_URL=https://gatus.pkarpovich.space/api/v1/endpoints/Backups_restic-$host/external
GATUS_TOKEN=REPLACE_ME
EOF
    echo "created /etc/restic/env - set TRANSPORT_PASSWORD and GATUS_TOKEN before first run" >&2
fi

ln -sf "$kit_dir/backup.sh" /usr/local/bin/restic-backup
cp "$kit_dir/systemd/restic-backup.service" /etc/systemd/system/
cp "$kit_dir/systemd/restic-check.service" /etc/systemd/system/
cp "$host_dir/systemd/restic-backup.timer" /etc/systemd/system/
cp "$host_dir/systemd/restic-check.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now restic-backup.timer restic-check.timer

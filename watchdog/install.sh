#!/bin/sh
set -eu

host="${1:?usage: install.sh <alpha|bravo>}"
kit_dir="$(dirname "$(readlink -f "$0")")"

case "$host" in
    alpha|bravo) ;;
    *) echo "unknown host: $host" >&2; exit 1 ;;
esac

mkdir -p /etc/fs-watchdog /var/lib/fs-watchdog
chmod 700 /etc/fs-watchdog

if [ ! -f /etc/fs-watchdog/env ]; then
    umask 077
    cat > /etc/fs-watchdog/env <<EOF
GATUS_PUSH_URL=https://ping.pkarpovich.space/api/v1/endpoints/Infrastructure_fs-$host/external
GATUS_TOKEN=REPLACE_ME
EOF
    echo "created /etc/fs-watchdog/env - set GATUS_TOKEN before the first run" >&2
fi

ln -sf "$kit_dir/fs-writable.sh" /usr/local/bin/fs-watchdog
cp "$kit_dir/systemd/fs-watchdog.service" /etc/systemd/system/
cp "$kit_dir/systemd/fs-watchdog.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fs-watchdog.timer

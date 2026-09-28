#!/bin/sh
set -eu

host="${1:?usage: install.sh <alpha|bravo>}"
kit_dir="$(dirname "$(readlink -f "$0")")"
repo_owner="$(stat -c %U "$kit_dir/..")"

case "$host" in
    alpha|bravo) ;;
    *) echo "unknown host: $host" >&2; exit 1 ;;
esac

mkdir -p /etc/autodeploy
chown "root:$repo_owner" /etc/autodeploy
chmod 750 /etc/autodeploy

if [ ! -f /etc/autodeploy/env ]; then
    relay_secret="$(sed -n 's/^RELAY_SECRET=//p' /etc/restic/env 2>/dev/null || true)"
    umask 027
    cat > /etc/autodeploy/env <<EOF
DEPLOY_HOST=$host
RELAY_SECRET=$relay_secret
EOF
    chown "root:$repo_owner" /etc/autodeploy/env
fi

ln -sf "$kit_dir/autodeploy.sh" /usr/local/bin/autodeploy
sed "s/@USER@/$repo_owner/" "$kit_dir/systemd/autodeploy.service" > /etc/systemd/system/autodeploy.service
cp "$kit_dir/systemd/autodeploy.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now autodeploy.timer

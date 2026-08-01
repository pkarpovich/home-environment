#!/usr/bin/env bash
# Install/refresh the subnet relay on the host that sits in the device subnet (bravo).
# Idempotent: safe to re-run after every git pull.
#
#   sudo ./subnet-relay/install.sh
#
# The config file is only seeded on first install - later edits on the host are
# kept. Re-run with --force-config to overwrite it from the repo copy.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
force_config="${1:-}"

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo $0)" >&2
    exit 1
fi

install -m 755 "$here/subnet-relay.py" /usr/local/bin/subnet-relay.py

if [ ! -f /etc/subnet-relay.conf ] || [ "$force_config" = "--force-config" ]; then
    install -m 644 "$here/subnet-relay.conf" /etc/subnet-relay.conf
    echo "installed /etc/subnet-relay.conf"
else
    echo "kept existing /etc/subnet-relay.conf (use --force-config to overwrite)"
fi

install -m 644 "$here/subnet-relay.service" /etc/systemd/system/subnet-relay.service
systemctl daemon-reload
systemctl enable --now subnet-relay
systemctl restart subnet-relay
sleep 2
systemctl --no-pager --lines=12 status subnet-relay || true

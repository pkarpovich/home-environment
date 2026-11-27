#!/bin/sh
set -eu

kit_dir="$(dirname "$(readlink -f "$0")")"

ln -sf "$kit_dir/nas-recover.sh" /usr/local/bin/nas-recover
cp "$kit_dir/systemd/nas-recover.service" /etc/systemd/system/
cp "$kit_dir/systemd/nas-recover.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nas-recover.timer

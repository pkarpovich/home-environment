#!/bin/bash
set -euo pipefail

mount_point="${MOUNT_POINT:-/mnt/nas}"
mount_unit="$(systemd-escape -p --suffix=mount "$mount_point")"
automount_unit="${mount_unit%.mount}.automount"
nfs_host="$(findmnt --fstab -n -o SOURCE "$mount_point" | cut -d: -f1)"

mounted() {
    findmnt -n -t nfs,nfs4 "$mount_point" >/dev/null
}

if ! mounted; then
    if ! timeout 3 bash -c "</dev/tcp/$nfs_host/2049" 2>/dev/null; then
        echo "NAS not reachable, nothing to do"
        exit 0
    fi
    echo "NAS reachable but $mount_point is not mounted, remounting"
    systemctl reset-failed "$mount_unit" "$automount_unit" 2>/dev/null || true
    systemctl restart "$automount_unit"
    timeout 30 ls "$mount_point" >/dev/null
    mounted || { echo "mount did not come up" >&2; exit 1; }
fi

# Containers whose NAS bind failed at boot: docker gives up on them and the restart policy never fires again.
for id in $(docker ps -aq --filter status=exited --filter status=created); do
    read -r name policy code error < <(docker inspect -f '{{.Name}} {{.HostConfig.RestartPolicy.Name}} {{.State.ExitCode}} {{if .State.Error}}failed{{else}}-{{end}}' "$id")
    case "$policy" in always|unless-stopped) ;; *) continue ;; esac
    [ "$code" = 255 ] || [ "$error" = failed ] || continue
    sources="$(docker inspect -f '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$id")"
    grep -q "^$mount_point/" <<<"$sources" || continue
    echo "starting ${name#/}"
    docker start "$id" >/dev/null
done

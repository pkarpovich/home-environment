#!/bin/bash
# Runs nas-recover.sh against stubbed docker/findmnt/systemctl/timeout.
# usage: nas-recover/test.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
fails=0

setup() {
    work="$(mktemp -d)"
    mkdir -p "$work/bin" "$work/nas"
    export STATE="$work" MOUNT_POINT="$work/nas"
    : >"$STATE/calls"
    cat >"$work/bin/systemd-escape" <<'EOF'
#!/bin/bash
echo "mnt-nas.mount"
EOF
    cat >"$work/bin/findmnt" <<'EOF'
#!/bin/bash
if [ "$1" = --fstab ]; then echo "nas.example:/share"; exit 0; fi
[ -f "$STATE/mounted" ]
EOF
    cat >"$work/bin/timeout" <<'EOF'
#!/bin/bash
shift
if [ "$1" = bash ]; then [ -f "$STATE/nas_up" ]; exit; fi
exec "$@"
EOF
    cat >"$work/bin/systemctl" <<'EOF'
#!/bin/bash
echo "systemctl $*" >>"$STATE/calls"
if [ "$1" = restart ] && [ -f "$STATE/mount_works" ]; then touch "$STATE/mounted"; fi
EOF
    cat >"$work/bin/docker" <<'EOF'
#!/bin/bash
case "$1" in
    ps) cut -d' ' -f1 "$STATE/containers" ;;
    inspect)
        row="$(grep "^$4 " "$STATE/containers")"
        if [[ "$3" == *RestartPolicy* ]]; then echo "$row" | cut -d' ' -f2-5; else echo "$row" | cut -d' ' -f6- | tr ' ' '\n'; fi ;;
    start) echo "docker start $2" >>"$STATE/calls" ;;
esac
EOF
    chmod +x "$work/bin/"*
    # id name policy exitcode error mounts...
    cat >"$STATE/containers" <<EOF
c1 /bookorbit unless-stopped 255 - $MOUNT_POINT/library /data
c2 /stopped unless-stopped 143 - $MOUNT_POINT/media
c3 /local always 255 - /var/lib/data
c4 /oneshot no 255 - $MOUNT_POINT/media
c5 /recorder always 128 failed $MOUNT_POINT/twitch
EOF
}

run() {
    PATH="$work/bin:$PATH" bash "$here/nas-recover.sh" >"$work/out" 2>&1 && echo 0 >"$work/rc" || echo $? >"$work/rc"
}

check() {
    local name="$1" want_rc="$2" want_calls="$3"
    local rc calls
    rc="$(cat "$work/rc")"
    calls="$(paste -sd';' "$STATE/calls")"
    if [ "$rc" = "$want_rc" ] && [ "$calls" = "$want_calls" ]; then
        echo "ok   $name"
    else
        echo "FAIL $name: rc=$rc (want $want_rc) calls='$calls' (want '$want_calls')"
        sed 's/^/     /' "$work/out"
        fails=$((fails + 1))
    fi
    rm -rf "$work"
}

setup
run
check "NAS down: nothing happens" 0 ""

setup
touch "$STATE/nas_up" "$STATE/mount_works"
run
check "NAS back: remount, start only crashed NAS containers" 0 \
    "systemctl reset-failed mnt-nas.mount mnt-nas.automount;systemctl restart mnt-nas.automount;docker start c1;docker start c5"

setup
touch "$STATE/mounted"
run
check "already mounted: container pass only" 0 "docker start c1;docker start c5"

setup
touch "$STATE/nas_up"
run
check "mount does not come up: fail" 1 "systemctl reset-failed mnt-nas.mount mnt-nas.automount;systemctl restart mnt-nas.automount"

[ "$fails" = 0 ]

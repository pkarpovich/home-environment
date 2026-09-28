#!/bin/sh
set -eu

host="${DEPLOY_HOST:?DEPLOY_HOST is not set}"
repo="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
state_dir="${STATE_DIRECTORY:-/var/lib/autodeploy}"
deployed_file="$state_dir/deployed"
failed_file="$state_dir/failed"

notify() {
    echo "$1" >&2
    [ -n "${RELAY_SECRET:-}" ] || return 0
    payload="$(printf %s "$1" | python3 -c 'import json,sys; print(json.dumps({"message": sys.stdin.read()}))')"
    curl -fsS -m 10 -X POST "${RELAY_URL:-https://relay.pkarpovich.space/send}" \
        -H "Content-Type: application/json" \
        -H "X-Secret: $RELAY_SECRET" \
        --data "$payload" >/dev/null || true
}

fail() {
    target="$1"
    reason="$2"
    if [ "$(cat "$failed_file" 2>/dev/null)" != "$target" ]; then
        notify "$(printf '🚀 autodeploy %s: %s at %.7s\n\n%s' "$host" "$reason" "$target" "$3")"
        printf '%s\n' "$target" > "$failed_file"
    fi
    exit 1
}

cd "$repo"
git fetch -q origin main
target="$(git rev-parse origin/main)"
deployed="$(cat "$deployed_file" 2>/dev/null || git rev-parse HEAD)"
[ "$target" = "$deployed" ] && exit 0

if ! out="$(git merge --ff-only -q origin/main 2>&1)"; then
    fail "$target" "git pull failed" "$out"
fi

case "$host" in
    alpha) set -- up -d --remove-orphans ;;
    bravo) set -- -f compose-traefik.yml -f compose-updater.yml up -d ;;
    *) echo "unknown host: $host" >&2; exit 1 ;;
esac

if ! out="$(docker compose "$@" 2>&1)"; then
    fail "$target" "compose up failed" "$(printf '%s\n' "$out" | tail -n 15)"
fi

changes="$(git log --no-merges --format='- %s' "$deployed..$target" 2>/dev/null | head -n 10)"
printf '%s\n' "$target" > "$deployed_file"
rm -f "$failed_file"
notify "$(printf '🚀 autodeploy %s: deployed %.7s\n\n%s' "$host" "$target" "$changes")"

#!/bin/sh
set -eu

kit_dir="$(dirname "$(readlink -f "$0")")"
host="${BACKUP_HOST:?BACKUP_HOST is not set}"
host_dir="$kit_dir/hosts/$host"
drift=""

is_covered() {
    cand="$1"
    for f in "$host_dir/includes.txt" "$host_dir/excludes.txt" "$host_dir/audit-ignore.txt"; do
        [ -f "$f" ] || continue
        while IFS= read -r line; do
            line="${line%%#*}"
            line="$(printf %s "$line" | sed 's/[[:space:]]*$//')"
            [ -n "$line" ] || continue
            case "$cand" in
                "$line"|"$line"/*) return 0 ;;
            esac
        done < "$f"
    done
    return 1
}

for v in $(docker volume ls --format '{{.Name}}' | grep -v -E '^[0-9a-f]{64}$' | grep -v -E '^(GITEA-ACTIONS|buildx_buildkit)'); do
    is_covered "/var/lib/docker/volumes/$v" || drift="$drift$(printf '\n- volume %s' "$v")"
done

for cfg in $(docker compose ls -a 2>/dev/null | tail -n +2 | awk '{print $NF}' | tr ',' '\n'); do
    d="$(dirname "$cfg")"
    is_covered "$d" || drift="$drift$(printf '\n- compose project %s' "$d")"
done

for c in $(docker ps --format '{{.Names}}\t{{.Image}}' | grep -Ei 'postgres|mysql|mariadb' | cut -f1); do
    grep -q "$c" "$host_dir/pre-backup.sh" 2>/dev/null && continue
    is_covered "$c" || drift="$drift$(printf '\n- db container %s without dump hook' "$c")"
done

if [ -z "$drift" ]; then
    echo "backup audit: clean"
    exit 0
fi

msg="$(printf '🗄 backup-audit: %s\n\nUncovered state:%s\n\nFix: add to backup/hosts/%s/includes.txt (or pre-backup.sh for databases), or to audit-ignore.txt with a reason.' "$host" "$drift" "$host")"
echo "$msg" >&2
if [ -n "${RELAY_SECRET:-}" ]; then
    payload="$(printf %s "$msg" | python3 -c 'import json,sys; print(json.dumps({"message": sys.stdin.read()}))')"
    curl -fsS -m 10 -X POST "${RELAY_URL:-https://relay.pkarpovich.space/send}" \
        -H "Content-Type: application/json" \
        -H "X-Secret: $RELAY_SECRET" \
        --data "$payload" >/dev/null || true
fi

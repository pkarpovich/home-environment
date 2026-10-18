#!/bin/sh
# Redeploys the ralphex-farm execution runner on this host.
#
# Reached only through the updater container's ssh key, which carries a forced
# command pointing here, so it takes no arguments: whatever the caller sends
# lands in SSH_ORIGINAL_COMMAND and is ignored. A stolen key redeploys the
# runner and can do nothing else.
#
# It refuses to touch the container in two cases, both of which cost more than a
# stale binary: when the registry holds the image already running, and when the
# runner has a job in flight.
set -eu

# /usr/local/bin is left out on purpose - see DOCKER_CONFIG below
PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
export PATH

# a credential-free docker config, because ~/.docker/config.json routes every
# registry through credsStore "desktop" and that helper reads the login keychain
# - which an ssh session cannot open ("the current session does not allow user
# interaction"). The image is public, so with no store configured docker takes
# the registry's anonymous token and pulls.
#
# An empty config alone is not enough: with credsStore unset the CLI detects a
# default one, and on darwin that means docker-credential-osxkeychain whenever
# it can find it - straight back into the keychain. Both helpers live in
# /usr/local/bin, so keeping that directory off PATH is what actually leaves the
# CLI on its plain file store.
#
# cli-plugins is a symlink back to the real one: buildx lives only there.
DOCKER_CONFIG=/Users/pavel.karpovich/.docker-updater
# the context lives in the config dir we just bypassed, so name the socket
DOCKER_HOST=unix:///Users/pavel.karpovich/.orbstack/run/docker.sock
export DOCKER_CONFIG DOCKER_HOST

ROOT=/Users/pavel.karpovich/Projects/home-environment
ENV_FILE=$ROOT/.env.mbp
IMAGE=git.pkarpovich.space/pkarpovich/ralphex-runner:latest
CONTAINER=ralphex-runner

compose() {
    docker compose -p runners --project-directory "$ROOT" \
        --env-file "$ENV_FILE" -f "$ROOT/compose-ralphex-runner.yml" "$@"
}

env_val() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

FARM_URL=$(env_val FARM_URL)
RUNNER_NAME=$(env_val RUNNER_NAME)

farm_runner() {
    curl -sf --max-time 10 "$FARM_URL/health" |
        jq -r --arg n "$RUNNER_NAME" --arg f "$1" \
            '.runners[] | select(.name==$n) | .[$f]'
}

# hash the manifest through a variable rather than a pipe: a failing inspect in
# a pipeline still exits 0 through awk, and shasum of no input returns the hash
# of the empty string - a digest that matches nothing and would make every pass
# look like an update is due
registry_digest() {
    raw=$(docker buildx imagetools inspect --raw "$IMAGE") || return 1
    [ -n "$raw" ] || return 1
    printf '%s' "$raw" | shasum -a 256 | awk '{print "sha256:" $1}'
}

# the digest of the image the container is running, not of whatever :latest
# points at locally: a pull that lands while the runner is busy moves the tag,
# and comparing against the tag would call the update done while the old binary
# keeps serving
running_digest() {
    img=$(docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null) || return 0
    docker image inspect "$img" --format '{{index .RepoDigests 0}}' 2>/dev/null | cut -d@ -f2
}

if ! REMOTE=$(registry_digest); then
    echo "cannot read the registry manifest, leaving the container alone"
    exit 1
fi
CURRENT=$(running_digest)

if [ "$REMOTE" = "$CURRENT" ]; then
    echo "already running ${CURRENT#sha256:}, nothing to do"
    exit 0
fi

echo "registry ${REMOTE#sha256:}, container ${CURRENT:-none}"

# pull before asking whether the runner is idle: it is the slow half and it
# touches nothing that is running, so a job claimed meanwhile still finds the
# old container intact and only the recreate has to wait for the next pass
compose pull

ACTIVE=$(farm_runner active || echo "")
if [ "$ACTIVE" != "0" ]; then
    echo "runner busy (active=${ACTIVE:-farm unreachable}), leaving the container alone"
    exit 0
fi

PREV_IMG=$(docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true)
BEFORE=$(farm_runner last_seen || echo "")

compose up -d

# up -d is a no-op when compose decides nothing changed, so confirm the
# container really moved onto the new image before believing anything else
if [ "$(running_digest)" != "$REMOTE" ]; then
    echo "compose left the container on ${CURRENT:-none}, not ${REMOTE#sha256:}"
    exit 1
fi

# the old process is gone with its container, so a last_seen that moves off its
# pre-recreate value can only be the new one checking in. Heartbeats are every
# 30s and registration happens on the first long poll
i=0
while [ "$i" -lt 20 ]; do
    sleep 3
    NOW=$(farm_runner last_seen || echo "")
    if [ -n "$NOW" ] && [ "$NOW" != "$BEFORE" ]; then
        echo "deployed ${REMOTE#sha256:}"
        exit 0
    fi
    i=$((i + 1))
done

echo "runner did not re-register within 60s, rolling back"
if [ -n "$PREV_IMG" ]; then
    docker tag "$PREV_IMG" "$IMAGE"
fi
compose up -d
exit 1

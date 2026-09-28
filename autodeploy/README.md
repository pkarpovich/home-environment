# Autodeploy: follow origin/main

Every host deploys `main` on its own within five minutes of a merge. A merged PR used to mean an ssh session, a `git pull`, a `docker compose up -d` and a checklist; a step forgotten in that list left a host on an old config with nothing to say so.

## How

A systemd timer runs every 5 minutes as the user that owns the checkout (`pi` on alpha, `tuclaw` on bravo). It fetches `origin/main` and does nothing if that commit is already deployed. Otherwise it fast-forwards the checkout and runs the host's compose command:

- alpha: `docker compose up -d --remove-orphans` (the full stack through `compose.yml`)
- bravo: `docker compose -f compose-traefik.yml -f compose-updater.yml up -d`

Each run reports to Telegram through the relay, the same channel the backup audit uses: one message per deployed commit, listing its changes, or one message per failed commit with the tail of the git or compose output. The deployed commit is recorded in `/var/lib/autodeploy/deployed`. A failed commit is retried every 5 minutes but reported only once.

Images are not pulled. A version bump in a compose file is pulled by `up` because the image is missing; floating tags (`latest`, `stable`) only move with a manual `docker compose pull`.

It is a pull rather than a webhook on purpose. GitHub cannot reach the updater, which only answers on the LAN. A webhook would need a Gitea mirror and an Actions run on the Mac runner, which is not always on. It would also have `compose up` recreate the updater container in the middle of its own deploy.

## Changes that need a host step

Anything outside git (`.env`, host-only files under `volumes/`) is not touched. When a PR needs such a step, do it before merging if it is compatible with the old compose files, or stop the timer around the merge:

```
sudo systemctl stop autodeploy.timer    # merge, do the host step
sudo systemctl start autodeploy.timer   # deploys within 5 minutes
```

## Install

```
cd ~/home-environment && git pull
sudo ./autodeploy/install.sh alpha   # or bravo
```

The installer creates `/etc/autodeploy/env` with `DEPLOY_HOST` and copies `RELAY_SECRET` from `/etc/restic/env`. Status: `systemctl list-timers autodeploy.timer`, `journalctl -u autodeploy -n 30`.

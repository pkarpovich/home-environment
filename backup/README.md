# Backups: restic -> Synology NAS

Nightly encrypted backups of alpha and bravo to the Synology NAS (192.168.198.2) over the restic REST protocol.

## Architecture

- **rest-server** runs on the NAS (Container Manager, `restic/rest-server`, data in `/volume2/restic_backups`) with `--append-only --private-repos`: each host authenticates as its own user (`alpha`, `bravo`), sees only its own repository, and cannot delete or overwrite existing snapshots - a compromised host cannot destroy its history.
- **Each Pi** runs a systemd timer (`restic-backup.timer`) that executes `backup.sh`: pre-backup hook (database dumps) -> `restic backup` with the host's include/exclude lists -> success metric for Prometheus.
- **Two secrets per host**, both outside git in `/etc/restic/`:
  - transport password (HTTP auth to rest-server, embedded in `RESTIC_REPOSITORY`)
  - repository encryption password (`/etc/restic/repo-pass`, generated on the host; keep a copy in the password manager - without it backups are unrecoverable)

## Schedule

| Host | Backup | Repo check | Why this slot |
|---|---|---|---|
| bravo | 02:30 | Sun 03:15 | before tuclaw dreaming (04:00) |
| alpha | 03:30 | Sun 05:30 | quiet hours, before turtle story (08:00) |

Retention policy (applied by the NAS prune task, see below): `--keep-daily 7 --keep-weekly 4 --keep-monthly 6`.

## Consistency

- Postgres (turtle-hub x4): `pg_dumpall | gzip` into `/var/backups/restic-dumps` before every run; raw pg volumes are deliberately NOT in the include list.
- SQLite (tuclaw.db, turtle-hub `.db/*.db`, magnet-feed-sync): `sqlite3 .backup` online copy into the dump dir; live files are additionally included raw where their directory is backed up.
- seaweedfs (21G, voice messages + generated images + turtle-hub artifacts): backed up live; volumes are append-only logs, crash-consistent copy is acceptable.
- Home Assistant: raw config dir (`volumes/homeassistant`), community-standard restore path.

## Install / update on a host

```
cd ~/home-environment && git pull
sudo ./backup/install.sh alpha   # or bravo
```

First install only: edit `/etc/restic/env` - replace `TRANSPORT_PASSWORD` with the host's rest-server password and `GATUS_TOKEN` with the endpoint token. Then run once manually:

```
sudo systemctl start restic-backup.service && journalctl -u restic-backup -f
```

`install.sh` is idempotent: re-running refreshes units and the `/usr/local/bin/restic-backup` symlink, never touches existing secrets.

## Monitoring

Gatus external endpoints (`Backups / restic-alpha`, `Backups / restic-bravo`), same pattern as the Time Machine heartbeats: every run pushes `success=true|false` to the Gatus API (instant telegram alert on failure), and the 26h `heartbeat.interval` fires when a backup silently never runs. Tokens: `RESTIC_ALPHA_TOKEN` / `RESTIC_BRAVO_TOKEN` in alpha's `.env` (gatus container) and `GATUS_TOKEN` in each host's `/etc/restic/env`.

## Retention prune (on the NAS)

Append-only means the Pis cannot prune. A monthly DSM Task Scheduler job (root) does it locally:

```
docker run --rm -v /volume2/restic_backups:/repos \
  -e RESTIC_PASSWORD_FILE=/repos/.secrets/alpha.pass \
  restic/restic -r /repos/alpha forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
docker run --rm -v /volume2/restic_backups:/repos \
  -e RESTIC_PASSWORD_FILE=/repos/.secrets/bravo.pass \
  restic/restic -r /repos/bravo forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
```

`/volume2/restic_backups/.secrets/` holds copies of the two repo passwords (chmod 700; not reachable through the REST API thanks to `--private-repos`). Trade-off: someone with root on the NAS can read the backups - acceptable, the NAS already holds most of the source data.

## Restore

```
sudo -s; . /etc/restic/env; export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
restic snapshots
restic restore latest --target /tmp/restore-test --include /home/tuclaw/tuclaw/data/tuclaw.db
```

Quarterly drill: restore one real file per host and open it. Yearly: `restic check --read-data-subset=5%`.

## Phase 2 (not implemented)

Offsite copy of the NAS itself: Hyper Backup of `/volume2/restic_backups` + Gitea volumes to Hetzner Storage Box (rsync) or Backblaze B2 (S3). The NAS is currently the single physical location of all backups.

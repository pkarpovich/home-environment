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

## Coverage audit (weekly)

`audit.sh` runs after the Sunday `restic check` (ExecStartPost) and compares live host state against the coverage lists: every named docker volume, every compose project dir, and every running postgres/mysql container must be matched by `includes.txt`, `excludes.txt`, a dump hook in `pre-backup.sh`, or an explicit line in `audit-ignore.txt` (with a `# reason`). Anything unmatched goes to telegram via [tg-relay-bot](https://github.com/pkarpovich/tg-relay-bot) (`RELAY_SECRET` in `/etc/restic/env`, URL defaults to `https://relay.pkarpovich.space/send`) - no bot token ever lands on the hosts. **The rule: any change that creates persistent state on a host must update these lists in the same PR** - the audit is the safety net for the forgotten case, not a substitute for doing it.

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

## Phase 2: offsite to DigitalOcean Spaces (fra1)

Nightly DSM Task Scheduler job `restic-offsite` (root, 05:30) runs `/volume2/restic_backups/offsite/offsite.sh`:

1. restic backup of Gitea (`/volume2/docker/gitea`, EXCLUDING `gitea/packages` - 39G of rebuildable container-registry blobs) into the local repo `/volume2/restic_backups/nas`, then forget+prune (local backend, no append-only restriction).
2. `rclone sync` of the whole share (minus `.secrets/`, `bin/`, `offsite/`) to the standard bucket `pkarpovich-restic-mirror`. The mirror is a byte-copy of the restic repos - restorable from any machine with `restic -r s3:... restore`, no Synology needed. `--backup-dir` keeps overwritten/deleted objects under `versions/YYYYMMDD/` for 90 days (Spaces has no bucket versioning).
3. `rclone copy` (never sync - local deletions do not propagate) of `/volume2/media/me` through the `media-crypt` rclone crypt remote into the cold bucket `pkarpovich-media-archive` ($0.007/GiB/mo). Client-side encryption incl. filenames; crypt keys in 1Password item "rclone crypt media" - without them the offsite media copy is undecryptable.
4. Success/failure push to the Gatus external endpoint `Backups/restic-offsite` (26h heartbeat).

Static `rclone` + `restic` binaries live in `/volume2/restic_backups/bin/` (no docker dependency). All credentials in `/volume2/restic_backups/.secrets/` (0600): `spaces.env` (DO keys), `rclone.conf`, `crypt.pass`/`crypt.salt`, `nas.pass`, `offsite.env` (gatus token). DO Spaces scoped keys deny HeadBucket, hence `no_check_bucket = true` in rclone.conf.

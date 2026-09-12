# alpha host

What alpha runs outside docker compose, what a from-scratch rebuild needs, and the order it has to follow. Written after the 2026-09-12 rebuild (Pi 4 with a worn-out SD card to Pi 5 on NVMe), when every item below turned out to live only on the dead card - none of it was in the restic snapshot, and none of it is deployed by `spot.yml`.

## Host services (not containers)

- **Grafana Alloy** from `apt.grafana.com`, config in `/etc/alloy/config.alloy`. The config must be `root:alloy` mode 640, and the `alloy` user must be in the `docker` group because the cadvisor exporter reads the socket - a restored config with a foreign gid leaves the service in `failed` with "permission denied".
- **Tailscale**. `/var/lib/tailscale` carries the node identity: restoring that directory before the first `tailscaled` start brings the node back under its old name and address without a login.
- **prometheus-node-exporter**, **glances**, **smartmontools**, **lm-sensors** from apt.
- **turtle-harbor**: `/usr/local/bin/th` and `/usr/local/bin/turtled` (GitHub releases), the user unit `~/.config/systemd/user/turtle-harbor.service`, and the script registry in `~/.local/share/turtle-harbor/` - `state.json` is what makes `/health` on port 9200 list scripts instead of `[]`. The unit only runs at boot with `loginctl enable-linger pi`. The scripts' python environment is rebuilt with mise per `turtle-harbor/README.md`; the checked-in `.venv` symlinks into the previous host's mise tree.
- **NFS**: `192.168.198.2:/volume2/media` on `/mnt/nas`, fstab options `rw,sec=sys,soft,timeo=150,_netdev,x-systemd.automount,x-systemd.mount-timeout=30`. turtle-hub binds `/mnt/nas/twitch` into a container, so the share has to be there before that container starts; with the automount a NAS outage fails only that container instead of the whole docker unit.
- **sysctl** `/etc/sysctl.d/99-thread.conf` disables IPv6.
- A second user **`app`** (uid/gid 1001, no password, `docker` group) owns most of `~/turtle-hub`, and its `~/.docker/config.json` holds the login for `git.pkarpovich.space` - `pi` needs the same login to pull turtle-hub images. On a fresh Raspberry Pi OS image gid 1001 is taken by `lpadmin`; move it before creating `app`, or every file of turtle-hub shows up group-owned by `lpadmin`.

## Pi 5 specifics

- `kernel=kernel8.img` in `/boot/firmware/config.txt`. The default `kernel_2712.img` uses 16 KiB pages, and images linked against jemalloc (content-oracle-app, continuum-client, nikki-app) abort on start with `<jemalloc>: Unsupported system page size`. The 4 KiB kernel costs a few percent of throughput; the proper fix is rebuilding those three images with jemalloc configured for 16 KiB pages.
- NVMe boot: `BOOT_ORDER=0xf416` (NVMe, then SD, then USB) and `PCIE_PROBE=1` in the bootloader config - the M.2 board in use exposes no HAT EEPROM, so without the probe flag the bootloader never looks at the drive even though the kernel sees it.
- The fan is driven by firmware from 50 °C; the old `dtoverlay=gpio-fan` line from the Pi 4 config must not be carried over.
- `192.168.198.3` is a UniFi DHCP reservation on the board's MAC, not a static address on the host. A board swap means moving the reservation to the new MAC; nothing on the host needs to change.

## Docker networks created by hand

`spot.yml` creates none of these on alpha:

```
docker network create proxy
docker network create telemetry
docker network create -d macvlan --subnet=192.168.198.0/24 --ip-range=192.168.198.16/28 --gateway=192.168.198.1 -o parent=eth0 homekit
```

`homekit` gives HomeKit-facing containers an address on the LAN itself (content-collector-hub takes `192.168.198.16`); its parameters are not written down anywhere else, they were recovered from the old daemon's network database.

## Restore order

1. **home-environment first.** `git.pkarpovich.space` is served by this Traefik, and every turtle-hub image is pulled through it, so nothing else can start until Traefik is up. Restore the `letsencrypt` volume before the first Traefik start or it re-issues every certificate against the Let's Encrypt rate limit.
2. Compose-managed volumes must exist with compose's own labels before data goes in: `docker compose create` in the project directory creates them (and pulls the images), then copy the data into `/var/lib/docker/volumes/<name>/_data` with ownership preserved, then `docker compose up -d`. Wipe `_data` first - image `VOLUME` directives pre-populate a fresh volume.
3. **turtle-hub, magnet-feed-sync, tg-relay-bot, tg-watchmen-turtle** with `docker compose -f compose.yml up -d`. Each has a `compose.override.yml` that adds `build:` stanzas for local development; a bare `docker compose up` merges it and rebuilds from source instead of pulling, and the magnet-feed-sync build no longer passes under current pnpm.
4. **Postgres.** A raw copy of a `postgres:15-alpine` volume (owner 70:70; pgvector pg17 is 999:999) recovers on the next start through WAL replay - the copy taken from the dead card at the moment of failure came up clean on all four. The nightly `pg_dumpall` output restores into an empty `postgres` database; ryot keeps its data there, not in a named database, so an app that already ran its migrations against the fresh database has to be stopped and the database dropped first.

## Gotchas

- A bind-mounted single file (the gatus config) keeps the old inode after `sed -i` or `git checkout` replaces it; the container needs `docker compose up -d --force-recreate <service>` to see the change, a plain restart is not enough.
- `pi`'s shell is fish. `ssh pi-alpha '<bash syntax>'` breaks; drive remote commands with `ssh pi-alpha bash -s <<'EOF'`, and never feed a tar stream into the same stdin as a heredoc.
- zima's `remote-shell-service` Dockerfile ran `ssh-copy-id pi@172.17.0.1` at build time, appending a `root@buildkitsandbox` key to `pi`'s `authorized_keys` on every rebuild - 21 of them by September. zima is retired (streamcast in turtle-hub replaced the live-stream forwarder); `authorized_keys` holds two keys again.
- `home-environment_grafana_data` was an orphan volume from an earlier compose layout, listed for backup but declared by nothing; dropped from the include list.

# Personal Home Environment

Docker Compose configs for the home lab: two Raspberry Pis (and a Synology NAS around them) running everything from Home Assistant to media tooling behind Traefik.

## Clusters and deployment

This repo drives two separate Raspberry Pis (separate Docker daemons), named with the NATO phonetic alphabet. Both reuse the same compose files; per-host differences come from each host's `.env`.

- **alpha** - the first Pi (`192.168.198.3`). Served on the root wildcard `*.pkarpovich.space` (no prefix). Deploys the full stack: `docker compose up -d` against `compose.yml`, which pulls every service in via its top-level `include:`.
- **bravo** - the second Pi / cluster (`192.168.199.72`). Served under `*.bravo.pkarpovich.space` via its own Traefik (longest-match wins over the root wildcard, no conflict). Deploys an explicit subset (no `compose.yml`): `docker compose -f compose-traefik.yml -f compose-updater.yml up -d`, i.e. Traefik + updater only.

So the *file set* per host is chosen by the deploy task (`include:` for alpha vs `-f` flags for bravo); the *values* per host come from `.env`. There are no `-bravo` duplicate compose files - `bravo`'s `.env` sets `ROOT_DOMAIN=bravo.pkarpovich.space`, so the shared `traefik/traefik.yml` issues the `*.bravo.pkarpovich.space` wildcard cert and the `updater.${ROOT_DOMAIN}` route resolves to the bravo zone with zero edits.

Deploy via [spot](https://github.com/umputun/spot), wrapped in [mise](https://mise.jdx.dev/) tasks:

```sh
mise run deploy-alpha   # full stack on the first Pi
mise run deploy-bravo   # traefik + updater on the second Pi
```

Secrets are never committed. Each host holds its own `.env` (git-ignored); alpha pulls some values from its on-host `stash` KV, while bravo has no KV so its `.env` is placed on the host manually. The repo ships `.env.bravo.example` as a non-secret template for the bravo host.

The shared Traefik HTTPS entrypoint sets `respondingTimeouts` (read/idle = 600s) so long requests through the proxy - notably Gitea container-registry image pushes - do not hit the default cutoffs. This applies to both clusters since `traefik/traefik.yml` is shared.

## Services

The compose files are the source of truth; this table is the map. Everything below runs on alpha unless noted.

| Compose file | Services | Exposed at |
|---|---|---|
| `compose.yml` | homepage, dozzle, phoenix, iSponsorBlockTV | `home.*`, `logs.*`, `phoenix.*` |
| `compose-traefik.yml` | traefik (alpha + bravo) | `traefik.*` |
| `compose-updater.yml` | updater (alpha + bravo) | `updater.*` |
| `compose-grafana.yml` | grafana, prometheus, loki, tempo, influxdb, telegraf, otel-collector, mcp-grafana, whoami | `grafana.*`, `prometheus.*`, `mcp-grafana.*` |
| `compose-homeassistant.yml` | homeassistant, matter-server | `homeassistant.*` |
| `compose-gatus.yml` | gatus (uptime + heartbeat monitoring, telegram alerts) | `ping.*` |
| `compose-media.yml` | tautulli | `tautulli.*` |
| `compose-jackett.yml` | jackett, flaresolverr (stateless CF solver, also used by scripts on both hosts) | `jackett.*`, `flaresolverr.*` |
| `compose-linkding.yml` | linkding (bookmarks) | `bookmarks.*` |
| `compose-ryot.yml` | ryot + postgres (media/fitness tracker) | `ryot.*` |
| `compose-deploy.yml` | stash (KV for secrets) | `stash.*` |
| `compose-torrents.yml`, `compose-twitch.yml` | qbittorrent + flood, ganymede - standalone `-f` deploys, not in the alpha `include:` set | |

Adjacent but not in this repo: Gitea + Plex live on the Synology NAS; tuclaw + ralphex-farm live on bravo in their own repos.

## Conventions

- **New service** = its own `compose-<name>.yml` + an entry in `compose.yml`'s `include:` list (or service block in an existing themed file). Traefik exposure via labels: `Host(\`<sub>.${ROOT_DOMAIN}\`)` + `entrypoints=https` + `tls.certresolver=le`. Wildcard DNS resolves any new subdomain to alpha automatically.
- **Healthchecks are expensive on a Pi**: steady-state interval 5m minimum (a 10s default across a dozen containers once cost a third of the CPU). For containers whose Traefik routing waits on `health: starting`, add `start_period` + `start_interval` so the router appears seconds after boot, not minutes.
- **Backup coverage moves with the change**: anything that creates persistent state on alpha or bravo must land in `backup/hosts/<host>/includes.txt` (or a dump hook in `pre-backup.sh` for databases, or `audit-ignore.txt` with a reason) in the same PR. A weekly audit diffs live volumes/projects/db-containers against these lists and reports drift to telegram.

## Backups

Nightly restic snapshots from both Pis to an append-only rest-server on the Synology, offsite mirror + encrypted media archive to DigitalOcean Spaces, monthly retention prune, Gatus heartbeats end to end. Full design, schedules, and the restore runbook: [`backup/README.md`](backup/README.md).

## Setup

Deployment is covered in [Clusters and deployment](#clusters-and-deployment) above. In short:

1. Clone this repository onto the target Pi (the `git checkout` step in `spot.yml` does this automatically on first deploy).
2. Place the host's `.env` (git-ignored) with that host's values - never edit the compose files. Use `.env.bravo.example` as a template for a bravo-style host.
3. Deploy with `mise run deploy-alpha` or `mise run deploy-bravo`.

## License

This project is open source, under the terms of the [MIT license](/LICENSE).

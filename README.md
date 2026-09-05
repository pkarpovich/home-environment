# Personal Home Environment

Docker Compose configs for the home lab: two Raspberry Pis (and a Synology NAS around them) running everything from Home Assistant to media tooling behind Traefik.

## Clusters and deployment

This repo drives two separate Raspberry Pis (separate Docker daemons), named with the NATO phonetic alphabet, plus one Mac running a single container. The Pis reuse the same compose files; per-host differences come from each host's `.env`.

- **alpha** - the first Pi (`192.168.198.3`). Served on the root wildcard `*.pkarpovich.space` (no prefix). Deploys the full stack: `docker compose up -d` against `compose.yml`, which pulls every service in via its top-level `include:`.
- **bravo** - the second Pi / cluster (`192.168.199.72`). Served under `*.bravo.pkarpovich.space` via its own Traefik (longest-match wins over the root wildcard, no conflict). Deploys an explicit subset (no `compose.yml`): `docker compose -f compose-traefik.yml -f compose-updater.yml up -d`, i.e. Traefik + updater only.

- **mbp** - the Mac (colima), not a Pi and not part of the spot deploys. It runs exactly one container, the ralphex-farm execution runner, from `compose-ralphex-runner.yml` and its own `.env.mbp`, brought up by hand. Nothing on it is exposed: the runner only dials out to the farm on bravo. Its state lives under `$HOME/ralphex` and is outside the backup audit below - the clones and caches are disposable and its credentials are provisioned by hand.

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
| `compose-authelia.yml` | authelia (SSO portal + the `authelia@docker` forward-auth middleware, see [Authentication](#authentication)) | `auth.*` |
| `compose-torrents.yml`, `compose-twitch.yml` | qbittorrent + flood, ganymede - standalone `-f` deploys, not in the alpha `include:` set | |
| `compose-ralphex-runner.yml` | ralphex-farm execution runner - **mbp only**, by hand: `docker compose -p runners --env-file .env.mbp -f compose-ralphex-runner.yml pull && ... up -d` | not exposed (outbound only) |

Adjacent but not in this repo: Gitea + Plex live on the Synology NAS; tuclaw and the ralphex-farm control plane live on bravo in their own repos. Only the farm's execution runner, which runs on mbp, is deployed from here - the farm repo ships a `docker-compose.runner.yml` of its own, but that one is reference documentation and deploys nothing.

Not everything here is a container. [`subnet-relay/`](subnet-relay/README.md) is a small systemd service on **bravo** that lets Home Assistant (on alpha) reach the Xiaomi devices and the Samsung TV sitting on the WiFi subnet - they only answer requests coming from their own subnet. Read it before adding such a device or when one changes its IP.

## Conventions

- **New service** = its own `compose-<name>.yml` + an entry in `compose.yml`'s `include:` list (or service block in an existing themed file). Traefik exposure via labels: `Host(\`<sub>.${ROOT_DOMAIN}\`)` + `entrypoints=https` + `tls.certresolver=le`. Wildcard DNS resolves any new subdomain to alpha automatically.
- **Healthchecks are expensive on a Pi**: steady-state interval 5m minimum (a 10s default across a dozen containers once cost a third of the CPU). For containers whose Traefik routing waits on `health: starting`, add `start_period` + `start_interval` so the router appears seconds after boot, not minutes.
- **Backup coverage moves with the change**: anything that creates persistent state on alpha or bravo must land in `backup/hosts/<host>/includes.txt` (or a dump hook in `pre-backup.sh` for databases, or `audit-ignore.txt` with a reason) in the same PR. A weekly audit diffs live volumes/projects/db-containers against these lists and reports drift to telegram.
- **Putting a service behind SSO** = one router label, `middlewares=authelia@docker`, after listing every non-browser caller of that host. See [Authentication](#authentication).

## Authentication

[Authelia](https://www.authelia.com/) at `auth.*` is the single sign-on portal for the whole estate: one account (`pkarpovich`), passkey login with the passkey kept in 1Password, and a Traefik `forwardAuth` middleware named `authelia` that any router opts into with one label. It runs on alpha only. The session cookie is set on the root domain, so a `*.bravo.*` route could reuse the same session later by pointing a bravo-side middleware at alpha; nothing on bravo is wired today, on purpose.

The default policy is `one_factor`, which a passkey login satisfies on its own; the account password exists for the first sign-in and as the fallback. `info.*` carries the single `two_factor` rule, and that rule is load-bearing: Authelia hides the whole second-factor UI, WebAuthn credential registration included, until at least one policy requires `two_factor`, so without it a passkey could never be registered. The canary therefore asks for one more WebAuthn tap after sign-in; everything else is one tap. Sessions live in memory (no Redis), so a restart of the `authelia` container means signing in again - one passkey tap. Persistent state (SQLite + the one-time-code file) is the `authelia` volume, listed in the alpha backup includes.

Protecting a service is `traefik.http.routers.<router>.middlewares=authelia@docker`. Before adding it, list every non-browser caller of that host - Gatus targets, Homepage widgets, tokens handed out through tuclaw's secret broker, CI webhooks - and either give them a `bypass` rule with `resources:` in `authelia/configuration.yml` or leave the service alone. `info.*` (whoami) is the canary: it is protected and echoes `remote-user` once you are signed in. `traefik.*` is deliberately still open: the Homepage Traefik widget fetches it through the public URL.

### Bootstrap (once, on alpha)

1. Two secrets into `.env`, `AUTHELIA_SESSION_SECRET` and `AUTHELIA_STORAGE_ENCRYPTION_KEY`, each from `docker run --rm ghcr.io/authelia/authelia:4.39 authelia crypto rand --length 64 --charset alphanumeric`.
2. `cp authelia/users_database.example.yml authelia/users_database.yml` (git-ignored - the repo is public), set the email, and paste the `Digest` line from `docker run --rm ghcr.io/authelia/authelia:4.39 authelia crypto hash generate argon2 --random --random.length 32 --no-confirm` as `password`. Keep the printed password in 1Password.
3. `docker compose up -d authelia whoami`.
4. Sign in at `auth.*` with the password, open `https://auth.<domain>/settings/two-factor-authentication` (user menu -> Settings -> Two-Factor Authentication) and Add a WebAuthn credential. The one-time code it asks for is in `docker exec authelia cat /data/notification.txt`. Save the passkey to 1Password.
5. From now on use the passkey button on the login page. `info.*` should answer with `remote-user: pkarpovich`.

## Backups

Nightly restic snapshots from both Pis to an append-only rest-server on the Synology, offsite mirror + encrypted media archive to DigitalOcean Spaces, monthly retention prune, Gatus heartbeats end to end. Full design, schedules, and the restore runbook: [`backup/README.md`](backup/README.md).

## Setup

Deployment is covered in [Clusters and deployment](#clusters-and-deployment) above. In short:

1. Clone this repository onto the target Pi (the `git checkout` step in `spot.yml` does this automatically on first deploy).
2. Place the host's `.env` (git-ignored) with that host's values - never edit the compose files. Use `.env.bravo.example` as a template for a bravo-style host. On alpha also place `authelia/users_database.yml` (git-ignored, see [Authentication](#authentication)).
3. Deploy with `mise run deploy-alpha` or `mise run deploy-bravo`.

## License

This project is open source, under the terms of the [MIT license](/LICENSE).

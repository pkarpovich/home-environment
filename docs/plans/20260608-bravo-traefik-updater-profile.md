# bravo cluster: Traefik + updater on the second RPi

## Overview

Bring the second Raspberry Pi — the **bravo cluster** (`192.168.199.72`, runs
tuclaw + ralphex-farm + tuclaw-voice) — under `home-environment` with its own
**Traefik** and **updater**, deployed via spot, reusing the same compose files
as the first Pi ("alpha") through `.env` parameterization. The alpha stack is
not duplicated.

**Naming convention (decided):** NATO-phonetic.

- **alpha** = first Pi (`192.168.198.3`), *implicit* — served on the root
  wildcard `*.pkarpovich.space`, no prefix.
- **bravo** = second Pi/cluster (`192.168.199.72`) — served under
  `*.bravo.pkarpovich.space` via its own Traefik. Longest-match wins over the
  root wildcard, no conflict.

**Deploy model (the key shape, agreed):**

- The two Pis are **separate Docker daemons**, so network/container/port names
  may be identical — no collisions. The same compose files serve both hosts;
  per-host differences come from each host's `.env`.
- **alpha** deploys as today: `docker compose up -d` against `compose.yml`,
  which pulls everything in via `include:` (traefik, updater, grafana, media, …).
- **bravo** deploys an explicit subset (no `compose.yml`):
  `docker compose -f compose-traefik.yml -f compose-updater.yml up -d`.
- So the *file set* per host is selected in the spot task; the *values* per host
  come from `.env`. No `-bravo` duplicate compose files.

**Parameterization (no new vars needed for the domain):** the shared
`traefik.yml` and updater already use `${ROOT_DOMAIN}` / `{{env "ROOT_DOMAIN"}}`.
bravo's `.env` simply sets `ROOT_DOMAIN=bravo.pkarpovich.space`, so the wildcard
cert and `updater.${ROOT_DOMAIN}` route resolve to the bravo zone with **zero
edits** to `traefik.yml`. Only host-path-shaped values are parameterized
(`UPDATER_CONFIG_DIR`, the updater SSH key host path).

**Why:** bravo today has no reverse proxy (raw `host:port`) and an ad-hoc
`systemd` updater whose config lives in the *tuclaw* repo. This gives bravo the
same clean ingress + TLS as alpha, moves the updater into `home-environment`
(config-as-code, same `ghcr.io/umputun/updater` image), retires the systemd
unit, and pairs with the in-flight tuclaw containerization (RAL-37) — after
which the tuclaw updater task is a clean `docker compose pull && up -d`.

**Scope:** config/playbook files in this repo + a small, backward-compatible
refactor of alpha's compose (extract the updater service into its own file,
parameterize host-specific values). Live actions (DNS, host secrets, deploy,
ports, CI webhook repoint, retiring systemd, deleting `tuclaw/deploy/updater.*`)
are Post-Completion / cross-repo.

## Context (from discovery)

**Deploy tooling (umputun spot):**

- `spot.yml` — currently simplified format (top-level `task:`), git clone/pull
  + `docker compose up -d`. Run via `Makefile` `deploy_local` →
  `spot -t local -v -i ./inventory.yml -k ~/.ssh/id_pi_ed25519`.
- spot CLI (verified from README): full format supports named `tasks:` +
  `targets:`; `--task/-n <name>` selects a task, `--target/-t <name>` selects a
  target/inventory group; one inventory may hold multiple groups.

**alpha compose composition (verified):**

- `compose.yml` uses a top-level `include:` of `compose-traefik.yml`,
  `compose-grafana.yml`, `compose-media.yml`, `compose-mcpjungle.yml`,
  `compose-homeassistant.yml`, `compose-gatus.yml`, `compose-deploy.yml`,
  `compose-jackett.yml`. Networks `proxy` and `telemetry` are `external: true`;
  `letsencrypt` is a top-level named volume.
- `compose-deploy.yml` holds **two** services: `stash` (alpha-only KV at
  `:9080`) and `updater` (`ghcr.io/umputun/updater`, `CONF=/config/updater.yml`,
  `KEY=${UPDATER_KEY}`, mounts `./.config/updater:/config:ro` + `/home/app/.ssh/
  id_rsa`, Traefik `Host(updater.${ROOT_DOMAIN})`, `extra_hosts: host.docker.
  internal:host-gateway`).
- `compose-traefik.yml` — `traefik:v3.6` on `proxy`, ports 25/80/443, mounts
  `traefik/traefik.yml` + `dynamic_conf.yml` + `letsencrypt`, env incl.
  `ROOT_DOMAIN`/`CF_API_EMAIL`/`CF_API_KEY`.
- `traefik/traefik.yml` — DNS-01 cloudflare resolver; https entrypoint cert
  `main: {{env "ROOT_DOMAIN"}}` + `sans: *.{{env "ROOT_DOMAIN"}}`. **No edit
  needed** — bravo drives it via its own `ROOT_DOMAIN`.
- `.config/updater/updater.yml` — alpha tasks SSH back to the host
  (`ssh app@host.docker.internal '... docker compose ... up -d'`).

**Standalone wrinkle (must handle):** `compose-traefik.yml`/`compose-updater.yml`
reference the `proxy` (external) network and the `letsencrypt` volume, which are
declared top-level in `compose.yml` (the includer). To run them standalone on
bravo via `-f`, the merged config must define those — so add top-level
`networks: proxy: {external: true}` + `volumes: letsencrypt:` to the shared
files (identical to alpha's declaration, merges cleanly under `include`), and
the bravo deploy task pre-creates the network (`docker network create proxy ||
true`). `telemetry` is alpha-only (phoenix) — bravo does not need it.

**Secrets:** repo `.env` is a stub; real values live in each host's `.env`
(alpha pulls some from its `stash` KV). bravo has no KV → its `.env` is placed
on the host manually; repo ships `.env.bravo.example`.

**bravo host facts (verified over SSH):** no Traefik, no `proxy` network;
updater is a running `systemd` unit (`updater.service`); `~/home-environment`
not cloned; host user `tuclaw`; `~/.ssh` holds deploy keys.

**Updater tasks to port** from `tuclaw/deploy/updater.yml` (`tuclaw`,
`tuclaw-voice`, `ralphex-farm`), SSHing to `tuclaw@host.docker.internal`. The
`tuclaw` task is compose-form per RAL-37.

## Development Approach

- **Testing approach**: Regular. Infra/config (YAML, compose, Traefik, spot) —
  no unit tests; each task's gate is a parse/validation step.
- **CRITICAL backward-compat:** alpha must deploy identically. The gate for any
  edit to a shared/alpha file is: `docker compose config` (full alpha set, with
  alpha's `.env`) produces an effectively-unchanged rendering, and
  `compose.yml`'s `include:` still resolves.
- bravo is additive at runtime; the only alpha-file edits are the updater
  extraction + env parameterization (values unchanged for alpha).
- No secrets committed — only `.env.bravo.example` placeholders.
- Keep this plan in sync if scope changes.

## Testing Strategy

- **Validation gates** (automatable, per task):
  - `docker compose config` over alpha's full set (with a sample alpha `.env`)
    parses and is unchanged vs before the refactor.
  - `docker compose -f compose-traefik.yml -f compose-updater.yml config`
    (with a sample bravo `.env`, `ROOT_DOMAIN=bravo.pkarpovich.space`) parses.
  - `spot --task=deploy-bravo --target=bravo -i ./inventory.yml --dry` parses
    and resolves the group (no host mutation); same for `deploy-alpha`.
  - `yamllint` on new/edited YAML.
- **No unit/e2e tests** — none exist; the live end-to-end (cert, routes,
  webhook) is Post-Completion on the host.

## Progress Tracking

- Mark `[x]` immediately. `➕` new tasks, `⚠️` blockers.

## What Goes Where

- **Implementation Steps** (checkboxes): files added/edited in this repo + gates.
- **Post-Completion** (no checkboxes): DNS, host secrets, deploy, ports, CI
  webhook, retiring systemd, cross-repo deletion in tuclaw.

## Implementation Steps

### Task 1: Single full-format spot playbook + bravo inventory + mise tasks

- [x] **read the spot full-format reference first** so the conversion is correct
      — umputun/spot README: https://github.com/umputun/spot (raw:
      https://raw.githubusercontent.com/umputun/spot/master/README.md ), the
      "playbook" / "full format" section. Key facts (verified): full format uses
      top-level named `tasks:` + `targets:`; `--task/-n <name>` selects a task,
      `--target/-t <name>` selects a target or inventory group; each task's
      `commands:` is a list of `{name, script}`. Minimal skeleton:
      ```yaml
      user: tuclaw
      targets:
        local: { hosts: [{host: "192.168.198.3", user: "pi"}] }   # or inventory groups
        bravo: { hosts: [{host: "192.168.199.72", user: "tuclaw"}] }
      tasks:
        - name: deploy-alpha
          commands:
            - { name: pull & up, script: "cd ~/home-environment && git pull && docker compose pull && docker compose up -d" }
        - name: deploy-bravo
          commands:
            - { name: deploy, script: "cd ~/home-environment && git pull && docker network create proxy || true && docker compose -f compose-traefik.yml -f compose-updater.yml pull && docker compose -f compose-traefik.yml -f compose-updater.yml up -d" }
      ```
      run: `spot --task=deploy-bravo --target=bravo -i ./inventory.yml`
- [x] convert `spot.yml` to the **full format**: `targets:` (or rely on
      inventory groups) + named `tasks:` `deploy-alpha` and `deploy-bravo`,
      preserving alpha's existing commands verbatim under `deploy-alpha`
      (git clone-guard + `git pull` + `docker compose pull && up -d`)
- [x] add `deploy-bravo` task: git clone-guard + `git pull` +
      `docker network create proxy || true` +
      `docker compose -f compose-traefik.yml -f compose-updater.yml pull` +
      `... up -d`
- [x] in `inventory.yml` add a `bravo` group
      `{host: "192.168.199.72", port: 22, user: "tuclaw", name: "bravo"}`
      (keep `local`/alpha untouched)
- [x] add `.mise.toml` with `deploy-alpha` (→ `spot --task=deploy-alpha
      --target=local -v -i ./inventory.yml -k ~/.ssh/id_pi_ed25519`) and
      `deploy-bravo` (→ `spot --task=deploy-bravo --target=bravo -v -i
      ./inventory.yml -k <bravo key>`); **delete `Makefile`** (bravo key =
      `~/.ssh/keys/tuclaw-rpi.pub`, matching the `tuclaw-rpi` ssh-config host)
- [x] validate: `spot --task=deploy-alpha --target=local --dry` and
      `--task=deploy-bravo --target=bravo --dry` both parse/resolve (playbook
      parses; targets resolve to 192.168.198.3 / 192.168.199.72+tuclaw; only the
      SSH handshake fails, which is expected without on-host keys); `mise tasks
      ls` lists both tasks
- [x] (no unit test — dry run is the gate)

### Task 2: Extract the updater into its own compose file (parameterized)

- [x] create `compose-updater.yml` with the `updater` service moved out of
      `compose-deploy.yml`, parameterizing host-specific values:
      `${UPDATER_CONFIG_DIR:-./.config/updater}:/config:ro`,
      `${UPDATER_SSH_KEY:-/home/app/.ssh/id_rsa}:/home/app/.ssh/id_rsa:ro`;
      keep `KEY=${UPDATER_KEY}`, `LISTEN`, `extra_hosts`, network `proxy`, and
      `Host(updater.${ROOT_DOMAIN})` (resolves per-host via `ROOT_DOMAIN`)
- [x] leave `stash` in `compose-deploy.yml` (alpha-only); add
      `compose-updater.yml` to `compose.yml`'s `include:` list so alpha still
      gets the updater (net result for alpha unchanged)
- [x] validate: `docker compose config` over alpha's full set with a sample
      alpha `.env` renders the same `updater` + `stash` services as before
      (byte-for-byte identical vs pre-refactor baseline; include resolves with
      no errors; updater volume defaults render `/home/app/.ssh/id_rsa`)
- [x] (no unit test — `docker compose config` diff is the gate)

### Task 3: Make shared compose files standalone-usable for bravo

- [ ] add top-level `networks: proxy: {external: true}` and `volumes:
      letsencrypt:` to `compose-traefik.yml` and `compose-updater.yml` so they
      run via `-f` without `compose.yml` (identical to alpha's declarations →
      merges cleanly under `include`)
- [ ] confirm `traefik/traefik.yml` needs **no change** (uses
      `{{env "ROOT_DOMAIN"}}`); bravo's `.env` sets `ROOT_DOMAIN=bravo.pkarpovich.space`
- [ ] validate: `docker compose -f compose-traefik.yml -f compose-updater.yml
      config` with a sample bravo `.env` parses (proxy external, letsencrypt
      volume, cert domain = `*.bravo.pkarpovich.space`); re-run the alpha
      full-set `config` to confirm still unchanged
- [ ] (no unit test — `docker compose config` is the gate)

### Task 4: bravo updater task config

- [ ] create `.config/updater-bravo/updater.yml` porting the three tasks from
      `tuclaw/deploy/updater.yml`, each `ssh tuclaw@host.docker.internal`:
      - `tuclaw` — compose form (RAL-37):
        `cd ~/tuclaw && git pull && docker compose pull && docker compose up -d`
        (⚠️ pre-RAL-37 bridge: git pull + binary download + `sudo systemctl
        restart tuclawd`, with a TODO to switch to compose form)
      - `ralphex-farm` — `docker compose pull farm && docker compose up -d farm`
      - `tuclaw-voice` — `git pull && uv sync && sudo systemctl restart tuclaw-voice`
- [ ] note: bravo's `.env` sets `UPDATER_CONFIG_DIR=./.config/updater-bravo` and
      `UPDATER_SSH_KEY=/home/tuclaw/.ssh/id_rsa`
- [ ] validate: YAML lint; `docker compose -f compose-updater.yml config` with
      the bravo `.env` mounts `./.config/updater-bravo`
- [ ] (no unit test — lint/config is the gate)

### Task 5: Example env + docs

- [ ] add `.env.bravo.example`: `ROOT_DOMAIN=bravo.pkarpovich.space`,
      `CF_API_EMAIL=`, `CF_API_KEY=`, `UPDATER_KEY=`,
      `UPDATER_CONFIG_DIR=./.config/updater-bravo`,
      `UPDATER_SSH_KEY=/home/tuclaw/.ssh/id_rsa` (no real secrets)
- [ ] update `README.md`: alpha / bravo-cluster naming, `mise run deploy-alpha`
      vs `mise run deploy-bravo`, the include-vs-`-f` model, and that bravo
      secrets live in the host `.env`
- [ ] validate: `yamllint`/`docker compose config` clean

### Task 6: Verify acceptance criteria

- [ ] alpha full-set `docker compose config` (sample alpha `.env`) unchanged vs
      pre-refactor; `compose.yml` `include:` resolves `compose-updater.yml`
- [ ] `docker compose -f compose-traefik.yml -f compose-updater.yml config`
      (sample bravo `.env`) parses with cert domain `*.bravo.pkarpovich.space`,
      `Host(updater.bravo.pkarpovich.space)`, config dir `./.config/updater-bravo`
- [ ] `spot --task=deploy-alpha --target=local --dry` and
      `--task=deploy-bravo --target=bravo --dry` resolve
- [ ] `Makefile` removed; `.mise.toml` has both tasks
- [ ] no secrets committed (grep the diff for token-shaped values)

### Task 7: [Final] Documentation

- [ ] ensure `README.md` documents the bravo cluster + naming + deploy model
- [ ] note in Post-Completion the cross-repo deletion in tuclaw

## Technical Details

### Per-host `.env` (the only differences)

| Var | alpha | bravo |
|---|---|---|
| `ROOT_DOMAIN` | `pkarpovich.space` | `bravo.pkarpovich.space` |
| `UPDATER_CONFIG_DIR` | `./.config/updater` (default) | `./.config/updater-bravo` |
| `UPDATER_SSH_KEY` | `/home/app/.ssh/id_rsa` (default) | `/home/tuclaw/.ssh/id_rsa` |
| `CF_API_EMAIL`/`CF_API_KEY`/`UPDATER_KEY` | alpha's | bravo's |

### DNS / TLS

`*.bravo.pkarpovich.space → 192.168.199.72` (Cloudflare, **DNS-only**, private
IP, LAN-scoped). Longest-match beats the root `*.pkarpovich.space`. bravo Traefik
issues its own DNS-01 wildcard cert for `*.bravo.pkarpovich.space` via the same
Cloudflare token, independent of alpha's cert.

### Files touched

```
spot.yml                            (simplified → full format: deploy-alpha + deploy-bravo)
inventory.yml                       (+ bravo group)
.mise.toml                          (new: deploy-alpha + deploy-bravo)
Makefile                            (deleted — replaced by .mise.toml)
compose-updater.yml                 (new: updater extracted from compose-deploy.yml, parameterized)
compose-deploy.yml                  (edit: stash only now)
compose.yml                         (edit: include compose-updater.yml)
compose-traefik.yml                 (edit: + top-level proxy/letsencrypt for standalone)
.config/updater-bravo/updater.yml   (new)
.env.bravo.example                  (new)
README.md                           (+ bravo cluster section)
```

`traefik/traefik.yml` — unchanged (driven by `ROOT_DOMAIN`).

## Post-Completion

*Manual / external / cross-repo — no checkboxes.*

**Cloudflare:** add `*.bravo.pkarpovich.space` A record → `192.168.199.72`,
DNS-only.

**bravo host:** place `.env` (real `ROOT_DOMAIN=bravo.pkarpovich.space` +
CF/UPDATER secrets + `UPDATER_CONFIG_DIR`/`UPDATER_SSH_KEY`); ensure the SSH
deploy key can `ssh tuclaw@host.docker.internal` and run docker/git/uv + needed
`sudo` (reuse tuclaw sudoers); open `80`/`443`. The `deploy-bravo` task creates
the `proxy` network.

**Deploy:** `mise run deploy-bravo`. Verify the `*.bravo` cert issues,
`updater.bravo.pkarpovich.space` answers, routes resolve.

**Cutover:** repoint CI `UPDATER_URL` to `https://updater.bravo.pkarpovich.space/...`;
stop + disable the bravo `systemd` `updater.service`.

**Cross-repo (tuclaw):** delete `deploy/updater.yml` + `deploy/updater.service`
once the bravo updater is live.

**Sequencing:** land after RAL-37 so the `tuclaw` updater task is compose-form.

**Execution:** `home-environment` is not served by ralphex-farm — run this with
local `ralphex`, or add the repo to the farm first (Workflow B).

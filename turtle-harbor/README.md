# Turtle Harbor (Pi)

Scripts managed by [turtle-harbor](https://github.com/pkarpovich/turtle-harbor) daemon on Raspberry Pi (`192.168.198.3`).

## Scripts

| Script | Type | Description |
|--------|------|-------------|
| radio-t-checker | daemon | Monitors Radio-T stream, sends push notification when live |
| radio-t-recorder | daemon | Records Radio-T stream to NAS |
| twitch-nfo-generator | cron (hourly) | Generates Plex NFO files from Twitch recording metadata |

## Setup

### Install turtle-harbor

```bash
# First install (download latest release)
curl -sL https://github.com/pkarpovich/turtle-harbor/releases/latest/download/turtle-harbor-aarch64-unknown-linux-gnu.tar.gz | sudo tar xz -C /usr/local/bin

# Install as systemd user service with health endpoint
th install --http-port 9200

# Verify
systemctl --user status turtle-harbor
```

### Update turtle-harbor

```bash
th update
```

### Python environment

```bash
cd ~/home-environment/turtle-harbor/scripts
mise install          # installs python 3.13 + uv
uv venv .venv         # creates virtualenv
```

### NAS mount (NFS)

Synology NAS (`192.168.198.2`) mounted at `/mnt/nas`:

```bash
# Manual mount
sudo mount -t nfs -o vers=4,sec=sys,rw 192.168.198.2:/volume2/media /mnt/nas

# Auto-mount via fstab (already configured)
# 192.168.198.2:/volume2/media /mnt/nas nfs4 rw,sec=sys,soft,timeo=150,_netdev 0 0
```

Synology NFS settings:
- Shared Folder > media > NFS Permissions > Squash: **Map all users to admin**
- File Services > NFS > Advanced > NFSv4/4.1 domain: **localdomain**

Pi NFSv4 idmapping (`/etc/idmapd.conf`):
```
[General]
Domain = localdomain
```

### Environment variables

Scripts read secrets from `scripts/.env` (not committed):

```bash
# Required for radio-t-checker
RELAY_SECRET=<relay-secret>

# Optional overrides
TWITCH_DIR=/mnt/nas/twitch       # default
RECORDING_DIR=/mnt/nas/radio-t   # default
STREAM_URL=https://stream.radio-t.com/  # default
```

## Common commands

```bash
th ps                              # list scripts and status
th up                              # start all scripts
th up radio-t-checker              # start specific script
th down                            # stop all scripts
th logs radio-t-checker -n 50      # show last 50 log lines
th logs radio-t-checker -f         # follow logs
th reload                          # reload scripts.yml after changes
```

## Health check

```bash
curl http://192.168.198.3:9200/health              # all scripts
curl http://192.168.198.3:9200/health/radio-t-checker  # specific script
```

Returns 200 when all healthy, 503 if any script failed. Monitored by Gatus.

## Log shipping

Logs are shipped to Loki (`192.168.198.3:3100`) with label `host: raspberry-pi`.

# Watchdog: root filesystem writability

Catches the failure mode where a host stays up and answers HTTP while its disk has silently stopped accepting writes.

## Why

On 2026-09-09 at 20:07 alpha's SD card stopped accepting writes (`mmc0: Card stuck being busy`, then a storm of write I/O errors). ext4 put the root filesystem into `emergency_ro`. For the next five hours everything looked healthy: containers stayed `Up`, Grafana drew graphs from memory, Gatus was green because Gatus checks HTTP and HTTP answered. Nothing was reaching the disk the whole time, and nobody knew.

Every existing check in this repo is a liveness check. None of them writes anything, so none of them can see a read-only disk.

## How

A systemd timer runs every 5 minutes and writes a file to `/`, reads it back, deletes it. Then it pushes the outcome to a Gatus external endpoint - the same pattern the restic and Time Machine heartbeats already use:

- write succeeds -> `success=true`, endpoint stays green
- write fails -> `success=false`, telegram alert on the next evaluation
- host is gone entirely -> no push at all, the 15m `heartbeat.interval` expires and Gatus alerts

The push carries no payload beyond the success flag; the probe file is written to `/var/lib/fs-watchdog` and removed immediately.

## Known limitation

Gatus runs on alpha. It reliably catches "host alive, disk read-only" - which is the failure that actually happened - but it cannot report alpha being fully powered off, since it would be off too. Detecting that needs a watcher outside alpha and is deliberately not in scope here.

## Install

```
cd ~/home-environment && git pull
sudo ./watchdog/install.sh alpha   # or bravo
```

First install only: put the endpoint token into `/etc/fs-watchdog/env` (`FS_ALPHA_TOKEN` / `FS_BRAVO_TOKEN` from alpha's `.env`), then check it:

```
sudo systemctl start fs-watchdog.service && systemctl status fs-watchdog.service
```

`install.sh` is idempotent: re-running refreshes the units and the `/usr/local/bin/fs-watchdog` symlink, never touches an existing env file.

## Verify it actually fires

```
sudo mount -o remount,ro /
sudo systemctl start fs-watchdog.service   # expected: unit fails, telegram alert
sudo mount -o remount,rw /
```

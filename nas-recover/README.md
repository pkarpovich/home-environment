# NAS recover: remount after a power cut

Brings the NAS share and the containers that live on it back on alpha after both lost power, whichever came up first.

## Why

On 2026-11-27 a power cut took down alpha and the NAS. alpha booted on its own, the NAS did not. At boot the NFS automount (`x-systemd.automount` in fstab) could not reach the NAS, so `mnt-nas.automount` and `mnt-nas.mount` ended up `failed` and stayed that way after the NAS was back. Docker tried to start the containers with binds under `/mnt/nas` (BookOrbit, the stream recorder), they exited with 255, and their `unless-stopped` policy never fired again. Everything else was green, so nothing pointed at it.

## How

A systemd timer runs every 2 minutes:

- the share is mounted -> only the container pass below
- not mounted and the NAS does not answer on the NFS port -> nothing, try again next run
- not mounted and the NAS answers -> `reset-failed` both units, restart the automount, touch the mount point, then the container pass

The container pass starts every container that has a bind under the mount point, an `always` or `unless-stopped` policy, and either exit code 255 or a start error. A container stopped by hand exits with 0 or 143 and is left alone.

The NAS address comes from the fstab entry, so the script holds no host names.

## Install

```
cd ~/home-environment && git pull
sudo ./nas-recover/install.sh
```

`install.sh` is idempotent: re-running refreshes the units and the `/usr/local/bin/nas-recover` symlink.

## Check

```
sudo systemctl start nas-recover.service && journalctl -u nas-recover.service -n 20
```

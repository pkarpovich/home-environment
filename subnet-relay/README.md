# subnet relay

Makes smart devices that live on the WiFi network (`192.168.199.x`) controllable
from Home Assistant, which runs on **alpha** (`192.168.198.x`).

Some consumer devices answer only when the request comes from their own subnet,
even though routing between the subnets works perfectly well. Two of them are in
this house, and both were unusable from Home Assistant until this relay existed:

- **Xiaomi** `zhimi`/`yeelink` firmware silently drops miio packets (UDP 54321)
  from a foreign source. It does answer ICMP from anywhere, which makes the
  failure look like a Home Assistant bug rather than a device one.
- **Samsung Smart TVs** refuse the control WebSocket across subnets. Home
  Assistant's own [docs](https://www.home-assistant.io/integrations/samsungtv/)
  say so and suggest "IP masquerading or a proxy" - this is that proxy.

## Evidence (measured 2026-08-01/02)

Xiaomi purifier `192.168.199.101`:

| From | miio handshake (UDP 54321) |
|---|---|
| bravo `192.168.199.72` (same subnet) | 32-byte reply, instantly |
| alpha `192.168.198.3` | packets leave `eth0`, **nothing comes back** (tcpdump) |

Samsung TV `192.168.199.39` - subtler, it is not a blanket block:

| From | REST `:8001/api/v2/` | WebSocket `:8002` (TLS) |
|---|---|---|
| bravo (same subnet) | HTTP 200 | `101 Switching Protocols` |
| alpha | HTTP 200 | TCP connects, **TLS handshake never completes** |

That last row is why pairing appeared broken: Home Assistant opens the socket and
waits forever, so the TV never gets far enough to show the confirmation prompt.

**UniFi is not the culprit.** A plain UDP listener on bravo:54321 answers alpha
fine, and so do the relay alias addresses below - which live in `192.168.199.x`
and are reached from alpha over the very same path. Return traffic from the
device subnet is not filtered; the devices themselves are picky.

Other Home Assistant devices work across subnets because they speak mDNS, HTTP,
MQTT or Matter. These two are the odd ones out.

## How it works

The relay runs on **bravo**, which is on the device subnet. For each device it
takes over a spare **alias IP** in `192.168.199.x` and forwards the relevant
ports to the real device, so the device sees a same-subnet source and answers.

```
HA (alpha 192.168.198.3) --> 192.168.199.201 (alias on bravo) --udp 54321--> 192.168.199.101 (purifier)
                             192.168.199.202 (alias on bravo) --udp 54321--> 192.168.199.26  (fan)
                             192.168.199.203 (alias on bravo) --tcp 8001/8002/9197--> 192.168.199.39 (TV)
```

Home Assistant is configured against the **alias** address. That indirection is
the point: a device changing its DHCP lease becomes a one-line config edit, and
the integration keeps working untouched.

Files: `subnet-relay.py` (relay + alias setup), `subnet-relay.conf` (the
mappings), `subnet-relay.service` (systemd unit), `install.sh` (idempotent
installer).

Deploy / update on bravo:

```bash
cd ~/home-environment && git pull
sudo ./subnet-relay/install.sh
```

Nothing lives outside git except `/etc/subnet-relay.conf`, which is seeded from
this directory - the whole component is reproducible from the repo and needs no
backup entry of its own.

## Current devices

| Device | Alias (used by HA) | Real IP | Ports |
|---|---|---|---|
| Xiaomi Smart Air Purifier 4 Pro (`zhimi.airp.vb4`) | 192.168.199.201 | 192.168.199.101 | udp 54321 |
| Smartmi Standing Fan 3 (`zhimi.fan.za5`) | 192.168.199.202 | 192.168.199.26 | udp 54321 |
| Samsung UE55TU7022KXXH (7 Series 55") | 192.168.199.203 | 192.168.199.39 | tcp 8001, 8002, 9197 |

## Adding a Xiaomi device

1. **Get its token** with [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor):

   ```bash
   curl -sL https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor/raw/master/run_docker.sh | bash
   ```

   Choose **QR-code login**. The Xiaomi account is registered on a phone number,
   and neither the phone number nor the recovery e-mail works as a username; the
   numeric Xiaomi account ID does, but the QR flow skips the problem entirely.
   The account's devices live on server **`de`** (one stray light is on `ru`).

2. Add a line to `/etc/subnet-relay.conf` with a free alias IP:

   ```
   udp 192.168.199.204 192.168.199.55 54321   # Some New Device (model.id)
   ```

3. `sudo systemctl restart subnet-relay`, then in Home Assistant: Settings >
   Devices > Add integration > Xiaomi Miio > tick *manual*, host = the **alias
   IP**, token = from step 1.

### Do not bother with the Home Assistant cloud login

The Xiaomi Miio config flow offers "cloud credentials" instead of IP + token. It
cannot work with this account: it uses the `micloud` library (0.5), which has
**no 2FA support whatsoever** (no `notificationUrl`, no captcha handling), so
Xiaomi's verification prompt surfaces as the useless
`Could not log in to Xiaomi Home, check the credentials.` Use tokens.

## Adding a Samsung TV

1. Find its IP and confirm the ports (from bravo, which is on its subnet):

   ```bash
   curl -s http://<tv-ip>:8001/api/v2/ | head -c 300     # name, model, PowerState
   ```

   The TV must be **on** - in deep standby it closes 8001/8002 entirely and is
   invisible to a port scan.

2. Add a line to `/etc/subnet-relay.conf` and restart the service:

   ```
   tcp 192.168.199.205 192.168.199.40 8001,8002,9197   # Samsung <model>
   ```

3. Add the integration in Home Assistant pointing at the **alias IP**. Coming
   from inside its own subnet the TV issues the token silently - no on-screen
   confirmation was needed for the TU7022.

**`turn_on` will not work.** Samsung is woken with Wake-on-LAN, a broadcast UDP
packet that does not cross subnets at all; a relay cannot help. Everything that
goes over the WebSocket - off, volume, sources, apps, remote keys - works. If
switching on from HA is ever needed, it takes a separate tiny service on bravo
that emits the magic packet inside the device subnet.

## When a device changes its IP

Edit the device address in `/etc/subnet-relay.conf`, `sudo systemctl restart
subnet-relay`, and mirror the change here. **Home Assistant needs no change** -
it only ever talks to the alias address.

Better yet, give these devices static DHCP leases in UniFi so it does not happen.

## Getting rid of the relay

If the devices are ever moved onto the main network (`192.168.198.x`), Home
Assistant can reach them directly:

```bash
sudo systemctl disable --now subnet-relay
sudo rm /usr/local/bin/subnet-relay.py /etc/systemd/system/subnet-relay.service /etc/subnet-relay.conf
```

Then re-add them in HA against their real IPs. Xiaomi tokens change on
re-pairing, so extract them again first.

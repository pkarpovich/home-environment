# Tailnet

Who does what in the tailnet, and why the roles sit where they do. Besides the owner's own devices, a few remote users rely on it for an internet exit and for Plex at home.

## Roles

| Node | Host | Role |
|---|---|---|
| `pi-alpha` | alpha (Pi 5, kernel TUN, apt package) | exit node with the home (Polish) address; subnet router for `192.168.198.0/24` and `192.168.199.0/24`, which is what makes `*.pkarpovich.space` (public DNS points at `192.168.198.3`) and bravo reachable from anywhere as if at home |
| `vpn-exit-node-de` | lasso (container, [vpn-exit-node](https://github.com/pkarpovich/vpn-exit-node)) | exit node whose egress goes through a gluetun VPN tunnel |
| `derp.pkarpovich.dev` | lasso (`compose-derp.yml`) | the tailnet's only DERP relay, see below |
| `diskstation` | Synology | a plain node since 2026-09-13 |
| `lasso` | the droplet's own tailscaled | a plain node; also what `--verify-clients` on the relay consults |

There is no ACL: every node sees every node, by decision. Authelia guards the HTTP services; non-HTTP ports on the LAN are reachable through the subnet route.

Until 2026-09-13 the Synology was the exit node and subnet router, in Tailscale's userspace networking mode (DSM 7 gives the package no TUN device). That cost 1.5 cores of a J4125 and topped out far below the line, and the traffic was mostly the owner's own Mac: macOS SMB multichannel opened a channel to the NAS over `utun4` because the NAS's own subnet route made the tunnel a valid path, so Time Machine and the media share ran through the NAS's netstack while the Mac sat at home. `/etc/nsmb.conf` with `mc_on=no` on the Mac stops that; moving the roles to alpha's kernel-mode Tailscale removed the CPU cost.

## Why a private relay

Two nodes that cannot reach each other directly fall back to a DERP relay: each connects outbound to it and it forwards the encrypted WireGuard packets between them, so it works through any NAT and cannot read the traffic. Home is behind the ISP's CGNAT (the ONT gets a `100.64.0.0/10` address, the public one is shared with other customers, and no port forward on the ONT or the UDR7 can change that - both were tried and verified with tcpdump on the UDR7's WAN), and the remote users are behind their operators' CGNAT too, so their connections to home are relayed.

Measured with iperf3 between lasso and alpha on 2026-09-13: direct 782 Mbit/s home to remote, 282 the other way; forced through Tailscale's Warsaw relay, 22.7 Mbit/s each way. A video podcast in Plex does not fit into 22 Mbit/s, which is the buffering remote viewers saw. A relay that carries only this tailnet is bounded by the droplet's port and the home uplink instead.

## Tailnet policy

The relay is announced to the tailnet in the policy file (admin console, Access controls):

```json
"derpMap": {
  "OmitDefaultRegions": true,
  "Regions": {
    "900": {
      "RegionID": 900,
      "RegionCode": "lasso",
      "RegionName": "lasso (Frankfurt)",
      "Nodes": [{
        "Name": "lasso",
        "RegionID": 900,
        "HostName": "derp.pkarpovich.dev",
        "IPv4": "46.101.182.43",
        "DERPPort": 443,
        "STUNPort": 3478
      }]
    }
  }
}
```

`OmitDefaultRegions` is deliberate. A node picks its home relay by latency, and from home Tailscale's Warsaw (8 ms) always beats Frankfurt (25 ms), so without it the private relay would never carry anything. The cost is that with the droplet down, relayed connections have no fallback until it is back; direct connections are unaffected.

`derp.pkarpovich.dev` is a DNS-only Cloudflare record to lasso's public IPv4. The Cloudflare proxy would break the DERP protocol switch inside TLS, so it must stay grey-clouded.

## Checks

- `curl -si https://derp.pkarpovich.dev/derp/probe` answers 200 through Traefik; Gatus watches the same URL as `Infrastructure / DERP`
- `tailscale netcheck` on any node lists region `lasso` once the policy is applied
- `tailscale ping <peer>` on a relayed pair reports `via DERP(lasso)`; on a remote device `tailscale status` shows `relay "lasso"` instead of `relay "waw"`
- `tailscale status` on the Mac at home must show `direct` for `pi-alpha` and no `active` traffic to `diskstation`

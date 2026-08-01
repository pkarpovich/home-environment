#!/usr/bin/env python3
"""Relay that makes local-subnet-only smart devices reachable from another subnet.

Several classes of consumer devices answer only when the request comes from
their own subnet, even though routing between the subnets works fine:

  * Xiaomi zhimi/yeelink firmware silently drops miio packets (UDP 54321) from a
    foreign source - it does reply to ICMP from anywhere.
  * Samsung Smart TVs refuse WebSocket connections (TCP 8001/8002) across
    subnets or VLANs; Home Assistant's own docs suggest masquerading or a proxy.

Home Assistant runs on alpha (192.168.198.x) while these devices live on the
WiFi network (192.168.199.x), so HA cannot talk to them directly.

This relay runs on a host that IS on the device subnet (bravo). For every device
it takes over a spare alias IP in that subnet and forwards the relevant ports to
the real device, so the device sees a same-subnet source and answers. Home
Assistant is configured against the alias IP, which never changes - if a device
gets a new DHCP lease only the config file needs an edit, HA keeps working.

Config format (see subnet-relay.conf):

    <proto> <alias-ip> <device-ip> <port>[,<port>...]     # comment
    <alias-ip> <device-ip>                                # legacy: udp/54321
"""

import socket
import subprocess
import sys
import threading

IFACE = "wlan0"
UDP_TIMEOUT = 5
BUFFER = 65535


def log(message):
    print(message, flush=True)


def read_config(path):
    entries = []
    with open(path) as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 2:
                entries.append(("udp", parts[0], parts[1], [54321]))
            elif len(parts) == 4:
                proto = parts[0].lower()
                if proto not in ("tcp", "udp"):
                    log("skipping line with unknown protocol: %s" % raw.strip())
                    continue
                try:
                    ports = [int(p) for p in parts[3].split(",") if p]
                except ValueError:
                    log("skipping line with bad ports: %s" % raw.strip())
                    continue
                entries.append((proto, parts[1], parts[2], ports))
            else:
                log("skipping malformed line: %s" % raw.strip())
    return entries


def ensure_alias(alias_ip):
    result = subprocess.run(
        ["ip", "addr", "add", alias_ip + "/24", "dev", IFACE],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        log("added alias %s on %s" % (alias_ip, IFACE))
    elif "File exists" in result.stderr or "already assigned" in result.stderr:
        log("alias %s already present" % alias_ip)
    else:
        log("could not add alias %s: %s" % (alias_ip, result.stderr.strip()))


def udp_relay(alias_ip, device_ip, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((alias_ip, port))
    upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    upstream.settimeout(UDP_TIMEOUT)
    log("udp %s:%d -> %s:%d" % (alias_ip, port, device_ip, port))

    while True:
        data, client = server.recvfrom(BUFFER)
        try:
            upstream.sendto(data, (device_ip, port))
            response, _ = upstream.recvfrom(BUFFER)
            server.sendto(response, client)
        except socket.timeout:
            log("%s: no answer from %s:%d (device offline?)" % (client[0], device_ip, port))
        except OSError as err:
            log("%s -> %s:%d failed: %s" % (client[0], device_ip, port, err))


def pump(src, dst):
    try:
        while True:
            chunk = src.recv(BUFFER)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def tcp_session(client, device_ip, port):
    try:
        upstream = socket.create_connection((device_ip, port), timeout=10)
    except OSError as err:
        log("connect to %s:%d failed: %s" % (device_ip, port, err))
        client.close()
        return
    upstream.settimeout(None)
    threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pump, args=(upstream, client), daemon=True).start()


def tcp_relay(alias_ip, device_ip, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((alias_ip, port))
    server.listen(16)
    log("tcp %s:%d -> %s:%d" % (alias_ip, port, device_ip, port))

    while True:
        client, _ = server.accept()
        threading.Thread(target=tcp_session, args=(client, device_ip, port), daemon=True).start()


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/etc/subnet-relay.conf"
    entries = read_config(config_path)
    if not entries:
        log("no mappings in %s, nothing to do" % config_path)
        return 1

    for _, alias_ip, _, _ in entries:
        ensure_alias(alias_ip)

    workers = []
    for proto, alias_ip, device_ip, ports in entries:
        target = udp_relay if proto == "udp" else tcp_relay
        for port in ports:
            workers.append((target, (alias_ip, device_ip, port)))

    for target, args in workers[:-1]:
        threading.Thread(target=target, args=args, daemon=True).start()
    last_target, last_args = workers[-1]
    last_target(*last_args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

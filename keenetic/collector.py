"""Collect mode: several API requests with aggregation of remote hosts."""

import time

import keenetic.config as config

from keenetic.connections import get_all_endpoint_connections
from keenetic.models import (
    Host, CollectedHost, parse_connection, ips_for_host, to_connection,
)
from keenetic.session import KeeneticSession
from keenetic.whois import WhoisInfo, lookup as whois_lookup


def port_label(port: int) -> str:
    """Human-readable port label: 0 → 'all ports'."""
    return "all ports" if port == 0 else f"port {port}"


def fetch_and_collect(
    session: KeeneticSession,
    host: Host,
    collected: dict[str, CollectedHost],
    sample: int,
    total: int,
    port: int,
):
    """One cycle: fetch connections → extract remote hosts → aggregate."""
    print(f"\n  [{sample}/{total}] Requesting connections...", end=" ", flush=True)

    try:
        raw_list = get_all_endpoint_connections(session)
    except Exception as e:
        print(f"[!] Error: {e}")
        return

    if not raw_list:
        print("no data")
        return

    now = time.time()
    count_conns = 0

    for c in raw_list:
        raw = parse_connection(c)
        if raw is None:
            continue
        all_ips = ips_for_host(raw)
        if host.ip not in all_ips:
            continue

        conn = to_connection(raw, host.ip)
        # Port 0 means "no port filter" (all ports)
        if conn.src_ip == host.ip and (port == 0 or conn.dst_port == str(port)):
            dst_ip = conn.dst_ip
            if dst_ip == "-" or dst_ip == host.ip:
                continue
            count_conns += 1

            if dst_ip not in collected:
                collected[dst_ip] = CollectedHost(ip=dst_ip, ports=set(), first_seen=now)
            ch = collected[dst_ip]
            ch.ports.add(conn.dst_port)
            ch.count += 1
            ch.last_seen = now

    print(f"{count_conns} connections, unique hosts so far: {len(collected)}")


def print_collected(collected: dict[str, CollectedHost], host: Host, port: int) -> dict[str, WhoisInfo]:
    """Prints the summary of collected remote hosts with WHOIS info.

    Returns the WHOIS response cache {ip: WhoisInfo} for further use
    (e.g. comparing Google/YouTube subnets with the router's routes).
    """
    if not collected:
        print(f"\n[!] No traffic ({port_label(port)}) over {config.COLLECT_COUNT} requests.")
        return {}

    sorted_hosts = sorted(collected.values(), key=lambda x: -x.count)

    # ── WHOIS lookups for each unique IP ───────────────────────
    print("\n[*] Requesting WHOIS info for the found hosts...", flush=True)
    whois_cache: dict[str, WhoisInfo] = {}
    for i, ch in enumerate(sorted_hosts, 1):
        print(f"  [{i}/{len(sorted_hosts)}] {ch.ip}...", end=" ", flush=True)
        whois_cache[ch.ip] = whois_lookup(ch.ip)
        print("✓" if not whois_cache[ch.ip].error else f"({whois_cache[ch.ip].error})")

    # ── Header ─────────────────────────────────────────────────
    total_sec = config.COLLECT_INTERVAL * (config.COLLECT_COUNT - 1)
    print(f"\n{'═' * 130}")
    print(f"  🎯 Remote hosts contacted by {host.ip} ({host.name})")
    print(f"     {port_label(port)}, {config.COLLECT_COUNT} requests every {config.fmt_interval(config.COLLECT_INTERVAL)}")
    print(f"{'═' * 130}")

    print(f"\n  {'#':<4} {'IP':<16} {'Ports':<10} {'Cnt':<6} {'CIDR':<24} {'Organization':<28} {'First':<10} {'Last':<10}")
    print(f"  {'─' * 124}")

    for i, ch in enumerate(sorted_hosts, 1):
        wi = whois_cache.get(ch.ip)
        cidr = wi.cidr if wi and wi.cidr else "-"
        org = wi.org_name or wi.organization or "-" if wi and not wi.error else "-"
        ports_str = ", ".join(sorted((p for p in ch.ports if p != "-"), key=int))
        first = time.strftime("%H:%M:%S", time.localtime(ch.first_seen))
        last = time.strftime("%H:%M:%S", time.localtime(ch.last_seen))
        print(f"  {i:<4} {ch.ip:<16} {ports_str:<10} {ch.count:<6} {cidr:<24} {org:<28} {first:<10} {last}")

    print(f"  {'─' * 124}")
    print(f"  Total unique remote hosts: {len(collected)}")

    # ── Detailed WHOIS info ────────────────────────────────────
    print(f"\n{'═' * 130}")
    print("  📋 Detailed WHOIS info")
    print(f"{'═' * 130}")

    for i, ch in enumerate(sorted_hosts, 1):
        wi = whois_cache.get(ch.ip)
        print(f"\n  [{i}] {ch.ip}")
        if wi and not wi.error:
            print(f"      NetRange:      {wi.net_range or '-'}")
            print(f"      CIDR:          {wi.cidr or '-'}")
            print(f"      Organization:  {wi.organization or '-'}")
            print(f"      OrgName:       {wi.org_name or '-'}")
        else:
            error_msg = wi.error if wi else "unknown"
            print(f"      WHOIS: {error_msg}")

    return whois_cache

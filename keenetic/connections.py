"""Fetching and displaying active connections from the Keenetic API."""

import json
import sys

import keenetic.config as config

from keenetic.models import (
    Host, Connection, parse_connection, ips_for_host, to_connection,
)
from keenetic.session import KeeneticSession


# Endpoints for active connections (in priority order)
CONNECTION_ENDPOINTS = [
    "/rci/show/ip/connections",
    "/rci/show/ip/conntrack",
    "/rci/show/ip/nat",
    "/rci/status/connection",
    "/rci/show/ip/accounting",
]


def try_get_connections(session: KeeneticSession, endpoint: str) -> tuple[dict, int] | None:
    """Tries to fetch connections from the endpoint. Returns (parsed, status) or None."""
    if config.DEBUG:
        print(f"\n[DEBUG] Trying {endpoint}...")
    data, status = session.get(endpoint)
    if status == 200:
        parsed = json.loads(data.decode("utf-8"))
        if config.DEBUG:
            print(f"[DEBUG] {endpoint} → {json.dumps(parsed, indent=2, ensure_ascii=False)[:2000]}")
        return parsed, status
    if config.DEBUG:
        print(f"[DEBUG] {endpoint} → HTTP {status}")
    return None


def get_all_endpoint_connections(session: KeeneticSession) -> list[dict] | None:
    """Iterates over endpoints until it gets a connection list."""
    for ep in CONNECTION_ENDPOINTS:
        result = try_get_connections(session, ep)
        if result is None:
            continue
        parsed, _ = result

        # Keenetic may return a dict with keys or a plain list
        raw: list | None = None
        if isinstance(parsed, list):
            raw = parsed
        elif isinstance(parsed, dict):
            raw = (
                parsed.get("connection")
                or parsed.get("connections")
                or parsed.get("nat")
                or parsed.get("entry")
                or parsed.get("accounting")
                or None
            )

        if raw is not None:
            print(f"[✓] Endpoint: {ep}")
            return raw

    print("[!] No endpoint returned connection data.")
    return None


def get_host_connections(session: KeeneticSession, host: Host) -> list[Connection]:
    """Fetches all connections involving the selected host."""
    raw_list = get_all_endpoint_connections(session)
    if raw_list is None:
        sys.exit(1)

    conns: list[Connection] = []
    for c in raw_list:
        raw = parse_connection(c)
        if raw is None:
            continue
        all_ips = ips_for_host(raw)
        if host.ip in all_ips:
            conns.append(to_connection(raw, host.ip))

    return conns


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _port_filter_label(port_filter: int | None) -> str:
    """Filter label: None → 'all ports'."""
    return "all ports" if port_filter is None else f"port {port_filter}"


def print_connections(conns: list[Connection], host: Host, port_filter: int | None = 443):
    """Prints the host's connections, optionally filtered by port."""
    if not conns:
        print(f"\n[!] No connections for {host.ip} ({host.name})")
        return

    if port_filter is not None:
        filtered = [
            c for c in conns
            if c.dst_port == str(port_filter) or c.src_port == str(port_filter)
        ]
    else:
        filtered = conns

    print(f"\n{'═' * 108}")
    print(f"  Host: {host.ip} ({host.name}) — {host.mac}")
    if port_filter:
        print(f"  Filter: port {port_filter}")
    print(f"{'═' * 108}")

    if not filtered:
        print(f"\n  [!] No connections ({_port_filter_label(port_filter)}).")
        if port_filter is not None:
            print(f"  Total host connections: {len(conns)} (show all: port 0)")
        return

    print(f"\n  {'Protocol':<8} {'Src IP':<20} {'Port':<8} {'':>2} {'Dst IP':<20} {'Port':<8} {'State':<14} {'RX':<10} {'TX'}")
    print(f"  {'─' * 106}")

    for c in filtered:
        if c.src_ip == host.ip:
            print(f"  {c.protocol:<8} {c.src_ip:<20} {c.src_port:<8} → {c.dst_ip:<20} {c.dst_port:<8} {c.state:<14} {c.bytes_in:<10} {c.bytes_out}")
        else:
            print(f"  {c.protocol:<8} {c.src_ip:<20} {c.src_port:<8} ← {c.dst_ip:<20} {c.dst_port:<8} {c.state:<14} {c.bytes_in:<10} {c.bytes_out}")

    print(f"  {'─' * 106}")
    print(f"  Total: {len(filtered)} connections ({_port_filter_label(port_filter)})")

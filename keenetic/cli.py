"""Main module: arguments, interactive menu, main() entry point."""

import os
import sys
import time

from getpass import getpass

import keenetic.config as config

from keenetic.auth import auth_flow
from keenetic.collector import fetch_and_collect, port_label, print_collected
from keenetic.connections import get_host_connections, print_connections
from keenetic.hosts import get_hosts, print_hosts, select_host
from keenetic.last_choice import (
    DEFAULT_MODE, DEFAULT_PORT, load_last_choice, save_last_choice,
)
from keenetic.models import CollectedHost
from keenetic.session import KeeneticSession
from keenetic.static_routes import (
    compare_google_subnets, run_subnet_audit, select_fqdn_group,
)


def choose_mode_and_port(mode_default: str = DEFAULT_MODE,
                         port_default: int = DEFAULT_PORT) -> tuple[str, int]:
    """Interactive mode and port selection.

    By default (Enter) the user's last choice is suggested, or standard
    values (collect mode, port 443) if there is none.
    """
    if mode_default not in ("collect", "once", "audit"):
        mode_default = DEFAULT_MODE
    if not isinstance(port_default, int) or not (port_default == 0 or 1 <= port_default <= 65535):
        port_default = DEFAULT_PORT

    default_mode_label = {"once": "2", "audit": "3"}.get(mode_default, "1")

    print(f"\n{'─' * 50}")
    print("  Select mode:")
    print(f"    1. Collect remote hosts ({config.COLLECT_COUNT} requests, interval {config.fmt_interval(config.COLLECT_INTERVAL)})")
    print("    2. One-shot connection snapshot")
    print("    3. DNS route audit (duplicate/overlapping subnets)")
    print(f"{'─' * 50}")

    while True:
        try:
            raw = input(f"  Mode [{default_mode_label}]: ").strip()
            if raw == "":
                mode = mode_default
                break
            elif raw == "1":
                mode = "collect"
                break
            elif raw == "2":
                mode = "once"
                break
            elif raw == "3":
                mode = "audit"
                break
            else:
                print("  [!] Enter 1, 2 or 3")
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)

    if mode == "audit":
        # The port filter is not used in the audit — keep the last value
        return mode, port_default

    while True:
        try:
            raw = input(f"  Filter port [{port_default}] (0 — all ports): ").strip()
            if raw == "":
                port = port_default
                break
            port = int(raw)
            if port == 0 or 1 <= port <= 65535:
                break
            print("  [!] Port must be between 1 and 65535 (0 — show all)")
        except ValueError:
            print("  [!] Enter a number")
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)

    return mode, port


def main():
    # ─── Arguments ─────────────────────────────────────────────
    for a in sys.argv[1:]:
        if a in ("--debug", "-d"):
            config.DEBUG = True
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"[!] Unknown argument: {a}\n")
            print(__doc__)
            sys.exit(1)

    # ─── Password ──────────────────────────────────────────────
    password = os.environ.get("KEENETIC_ROUTER_PASSWORD")
    if password:
        print("[*] Password from KEENETIC_ROUTER_PASSWORD")
    else:
        password = getpass(f"🔑 Password for {config.LOGIN}@{config.ROUTER_IP}: ")

    session = KeeneticSession()
    print(f"\n[*] Connecting to {config.BASE_URL}...")

    # ─── Authentication ────────────────────────────────────────
    auth_flow(session, password)

    # ─── Host list ─────────────────────────────────────────────
    print("[*] Fetching host list...")
    hosts = get_hosts(session)
    print_hosts(hosts)

    # ─── User's last choice ────────────────────────────────────
    last = load_last_choice()
    last_host_value = last.get("host")
    last_ip = last_host_value if isinstance(last_host_value, str) else None

    # ─── Host selection ────────────────────────────────────────
    host = select_host(hosts, last_ip=last_ip)
    print(f"\n[✓] Selected host: {host.ip} ({host.name})")

    # ─── Mode and port selection ───────────────────────────────
    mode, port = choose_mode_and_port(
        mode_default=last.get("mode", DEFAULT_MODE),
        port_default=last.get("port", DEFAULT_PORT),
    )

    # ─── DNS route group for auto-adding subnets ───────────────
    # Suggested at startup in collect mode (Enter — last group).
    group_name = None
    if mode == "collect":
        last_group = last.get("group")
        group_name = select_fqdn_group(
            session, last_group if isinstance(last_group, str) else None,
        )
    save_last_choice(host.ip, mode, port, group_name)

    if mode == "once":
        # ─── Snapshot ──────────────────────────────────────────
        print(f"\n[*] One-shot snapshot (port {port})...")
        conns = get_host_connections(session, host)
        print_connections(conns, host, port_filter=port if port else None)
    elif mode == "audit":
        # ─── DNS route audit ───────────────────────────────────
        run_subnet_audit(session)
    else:
        # ─── Collect ───────────────────────────────────────────
        total_sec = config.COLLECT_INTERVAL * (config.COLLECT_COUNT - 1)
        print(f"\n{'═' * 60}")
        print("  📡 COLLECT REMOTE HOSTS")
        print(f"  Local host: {host.ip} ({host.name})")
        port_str = port_label(port) if port == 0 else str(port)
        print(f"  Port: {port_str}  |  Requests: {config.COLLECT_COUNT}  |  Interval: {config.fmt_interval(config.COLLECT_INTERVAL)}")
        print(f"  Total duration: ~{config.fmt_interval(total_sec)}")
        print(f"{'═' * 60}")

        collected: dict[str, CollectedHost] = {}

        for i in range(1, config.COLLECT_COUNT + 1):
            if i > 1:
                now_str = time.strftime("%H:%M:%S")
                print(f"  ⏳ Waiting {config.fmt_interval(config.COLLECT_INTERVAL)} until request {i}...  (current time: {now_str})", flush=True)
                time.sleep(config.COLLECT_INTERVAL)
            fetch_and_collect(session, host, collected, i, config.COLLECT_COUNT, port)
            print(f"  ✅ Request {i} done", flush=True)

        whois_cache = print_collected(collected, host, port)
        compare_google_subnets(session, whois_cache, group_name)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sys.exit(1)

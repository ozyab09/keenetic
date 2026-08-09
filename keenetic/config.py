"""Configuration and constants for the Keenetic API."""

import os

# Router IP can be overridden with an environment variable (defaults to the
# standard Keenetic LAN address)
ROUTER_IP = os.environ.get("KEENETIC_ROUTER_IP", "192.168.1.1")
BASE_URL = f"http://{ROUTER_IP}"
LOGIN = "admin"

# Debug flag (set via --debug)
DEBUG = False

# Collection settings
COLLECT_COUNT = 5          # number of requests
COLLECT_INTERVAL = 5       # seconds between requests


def fmt_interval(seconds: int) -> str:
    """Formats an interval: 5 → '5 sec', 300 → '5 min', 3600 → '1 h'."""
    if seconds < 60:
        return f"{seconds} sec"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds / 3600:.1f} h"

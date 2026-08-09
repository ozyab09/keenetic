# Keenetic API Tool

[![CI](https://github.com/ozyab09/keenetic/actions/workflows/ci.yml/badge.svg)](https://github.com/ozyab09/keenetic/actions/workflows/ci.yml)

A utility for monitoring network connections through a Keenetic router.  
It fetches the active connections of a selected host, collects remote IP addresses, enriches them with WHOIS data, and compares Google/YouTube subnets against the router's DNS static routes.

---

## Table of contents

- [Quick start](#quick-start)
- [Ways to run](#ways-to-run)
- [How it works](#how-it-works)
- [Interactive menu](#interactive-menu)
- [Modes](#modes)
  - [Collect mode](#1-collect-mode)  
  - [Snapshot mode](#2-snapshot-mode)
- [WHOIS enrichment](#whois-enrichment)
- [Google/YouTube subnet comparison](#googleyoutube-subnet-comparison)
- [Remembering the last choice](#remembering-the-last-choice)
- [Environment variables](#environment-variables)
- [Debug mode](#debug-mode)
- [Tests](#tests)
- [Continuous integration](#continuous-integration)
- [Project structure](#project-structure)
- [Modules (API)](#modules-api)
- [Requirements](#requirements)

---

## Quick start

```bash
# 1. Set the password (once)
export KEENETIC_ROUTER_PASSWORD="your_keenetic_password"

# 2. If the router is not at 192.168.1.1, point to its address
# export KEENETIC_ROUTER_IP="192.168.1.1"

# 3. Run
./keenetic.sh
```

The script finds Python 3 on its own and runs the module.

## Ways to run

| Way | Command | When convenient |
|---|---|---|
| **Bash launcher** | `./keenetic.sh` | From the repository root |
| **Python module** | `python -m keenetic` | From the repository root |
| **Install** | `pip install .` (then `keenetic`) | After install — from anywhere |
| **With debugging** | `./keenetic.sh --debug` | For diagnostics |

The `--debug` argument can be passed to any of the ways above.

## How it works

```
┌────────────┐    ┌──────────────┐    ┌────────────┐    ┌───────────┐
│ Auth       │ →  │ Host list    │ →  │ Target     │ →  │ Run mode  │
│ challenge- │    │ /rci/show/ip │    │ selection  │    │           │
│ response   │    │ /hotspot     │    │ by IP/name │    │           │
└────────────┘    └──────────────┘    │ /number    │    └───────────┘
                                       └────────────┘         │
                                          ┌───────────────────┼──────────────┐
                                          ▼                   ▼              ▼
                                    ┌──────────┐        ┌──────────┐   ┌────────┐
                                    │ Collect  │        │ Snapshot │   │ WHOIS  │
                                    │ 5×5 sec  │        │ 1 request│   │ arin   │
                                    └──────────┘        └──────────┘   └────────┘
```

**Authentication protocol:** Keenetic uses **challenge-response**:
1. `GET /auth` → the router returns `X-NDM-Realm` and `X-NDM-Challenge`
2. The client computes `MD5(login:realm:password)` → `SHA256(challenge + md5_hash)`
3. `POST /auth` with the hash → a session cookie is obtained

**API endpoints:** the script iterates several endpoints to fetch connections:
- `/rci/show/ip/connections`
- `/rci/show/ip/conntrack` (text format, not used)
- `/rci/show/ip/nat` (the main working endpoint)
- `/rci/status/connection`
- `/rci/show/ip/accounting`

**NAT record format (real):**
```json
{
  "protocol": "TCP",
  "src": "192.168.1.50",
  "dst": "178.130.128.49",
  "sport": 55809,
  "dport": 443,
  "bytes": 265980,
  "packets": 577,
  "src-out": "178.130.128.49",
  "dst-out": "46.39.239.52",
  "bytes-out": 37821
}
```

## Interactive menu

After authentication a host selection appears, then the menu:

```
🔍 Select host (number / IP / name, Enter — MyPhone (192.168.1.100), 'quit' to exit):
──────────────────────────────────────────────────
  Select mode:
    1. Collect remote hosts (5 requests, interval 5 sec)
    2. One-shot connection snapshot
──────────────────────────────────────────────────
  Mode [1]:                    ← Enter = last choice (or 1)
  Filter port [443] (0 — all ports):   ← Enter = last port
```

- **Enter** — default value: the user's last choice (on first run — mode 1, port 443)
- **Enter** in host selection — confirm the last selected host; **`quit`** — exit
- **0** as the port — all ports, no filtering (works in both collect and snapshot)

See [Remembering the last choice](#remembering-the-last-choice) for details.

## Modes

### 1. Collect mode

Makes **5 requests** to the API every **5 seconds** (~20 seconds in total).  
For each request:

1. Fetches the router's active connections
2. Filters by the selected host's IP
3. Extracts remote destination addresses (dst_ip) on the given port
4. Aggregates: unique IP, list of ports, hit count, first and last seen time

After collection — automatic WHOIS lookup for each found IP,  
then — comparison of Google/YouTube subnets with the router's DNS routes (see [below](#googleyoutube-subnet-comparison)).

> **Port 0** — collect traffic on **all** ports (no filtering).

**Example output:**
```
  📡 COLLECT REMOTE HOSTS
  Local host: 192.168.1.100 (MyPhone)
  Port: 443  |  Requests: 5  |  Interval: 5 sec
  Total duration: ~20 sec

  [1/5] Requesting connections... 12 connections, unique hosts so far: 5
  ✅ Request 1 done
  ⏳ Waiting 5 sec until request 2...  (current time: 14:35:01)
  ...
```

### 2. Snapshot mode

A one-shot request of the selected host's active connections.  
Shows a table:

```
  ═══════════════════════════════════════════════════════════
  Host: 192.168.1.100 (MyPhone) — aa:bb:cc:dd:ee:ff
  Filter: port 443
  ═══════════════════════════════════════════════════════════

  Protocol  Src IP               Port        Dst IP               Port     State        RX         TX
  ────────────────────────────────────────────────────────────────────────────────────────────────────
  tcp       192.168.1.100        54321    →  142.250.185.78       443      established  1024       2048
```

## WHOIS enrichment

For every collected remote IP the script performs a lookup against `whois.arin.net:43` (raw TCP).

**Extracted fields:**

| Field | Description | Example |
|---|---|---|
| `NetRange` | IP address range | `8.8.8.0 - 8.8.8.255` |
| `CIDR` | CIDR notation | `8.8.8.0/24` |
| `Organization` | Short name | `Google LLC (GOGL)` |
| `OrgName` | Full name | `Google LLC` |

**Output:**
```
  🎯 Remote hosts contacted by 192.168.1.100 (MyPhone)
     port 443, 5 requests every 5 sec

  #    IP               Ports  Cnt  CIDR                     Organization
  ────────────────────────────────────────────────────────────────────────
  1    142.250.185.78   443    3    142.250.0.0/15            Google LLC
  2    157.240.1.35     443    2    157.240.0.0/16            Facebook Inc.

  📋 Detailed WHOIS info

  [1] 142.250.185.78
      NetRange:      142.250.0.0 - 142.250.255.255
      CIDR:          142.250.0.0/15
      Organization:  Google LLC (GOGL)
      OrgName:       Google LLC

  [2] 157.240.1.35
      NetRange:      157.240.0.0 - 157.240.255.255
      CIDR:          157.240.0.0/16
      Organization:  Facebook Inc. (FB)
      OrgName:       Facebook Inc.
```

**Timeout:** 8 seconds per request. If the server is unavailable or the IP is not found, a message is printed.

## Google/YouTube subnet comparison

Runs automatically **after the collect mode**. The script:

1. Picks subnets (CIDR) belonging to **Google** or **YouTube** from the WHOIS data (if `OrgName`/`Organization` contains `google` or `youtube`)
2. Fetches the router's DNS static routes
3. Compares the found subnets with the list and prints the **missing** ones

**Endpoints (KeeneticOS 4.x):**

| Endpoint | What it contains |
|---|---|
| `/rci/object-group/fqdn` | FQDN groups: `{name: {description, include: [{address}]}}` — subnets/domains live here |
| `/rci/dns-proxy/route` | The DNS routes themselves: `[{group, interface, auto, reject, index}]` |

> **Note:** on KeeneticOS 4.x the `/rci/staticRoutes/dns` path **does not exist** (HTTP 404) — it's from the old UI. The real endpoints are above.

A subnet is considered **already present** if the router has the same subnet or a wider one that fully covers it. Domain entries in groups don't participate in the comparison — a notice about them is printed.

**Example output:**
```
  🌐 Google/YouTube subnets: comparison with router DNS routes
  Found: 5  |  Already on router: 3  |  Missing: 2

  #    Subnet                  Organization                      Status
  ────────────────────────────────────────────────────────────────────────────────
  1    34.128.0.0/10            Google LLC                       ✗ missing
  2    64.233.160.0/19          Google LLC                       ✓ on router
  3    74.125.0.0/16            Google LLC                       ✗ missing
  4    142.250.0.0/15           Google LLC                       ✓ on router
  ────────────────────────────────────────────────────────────────────────────────

  ⚠️  Missing subnets (2) — not present in the router's DNS routes:
    • 34.128.0.0/10  (Google LLC)
    • 74.125.0.0/16  (Google LLC)
```

**Adding to the router:** at startup in collect mode the script asks to choose the DNS route group where missing subnets will be added (Enter — the last selected group, `0` — don't add). If subnets are missing, the script **automatically** (no confirmation) adds them to the selected group via `POST /rci/object-group/fqdn` (existing group entries are kept, duplicates are dropped). The last group choice is stored in `last_choice.json`; on a write error a message is printed and nothing is changed.

## Remembering the last choice

The script stores the last choice — **host, mode, port and DNS route group** — in the `last_choice.json` file and suggests it by default on the next run:

- **Host selection:** the prompt shows the last host (`Enter — MyPhone (192.168.1.100)`); **Enter** confirms it, **`quit`** exits the program
- **Mode and port:** Enter fills in the last values (`Mode [2]`, `Port [0]`); on first run — mode 1 and port 443
- **DNS route group:** in collect mode Enter fills in the last selected group, `0` — don't add automatically

The `last_choice.json` file is created automatically in the repository root (next to `README.md`). It contains personal data (the selected host's IP) and is not tracked by git — it's listed in `.gitignore`.

## Environment variables

| Variable | Description | Required |
|---|---|---|
| `KEENETIC_ROUTER_IP` | Router IP address (default `192.168.1.1`) | No |
| `KEENETIC_ROUTER_PASSWORD` | Keenetic web UI password | No (prompts interactively) |

```bash
# Ways to pass the settings:
export KEENETIC_ROUTER_IP="192.168.1.1"
export KEENETIC_ROUTER_PASSWORD="my_password"
./keenetic.sh

# Or in one line:
KEENETIC_ROUTER_IP="192.168.1.1" KEENETIC_ROUTER_PASSWORD="my_password" ./keenetic.sh
```

## Debug mode

```
./keenetic.sh --debug
```

Enables raw JSON output from all API endpoints:
- `/rci/show/ip/hotspot` — host list
- `/rci/show/ip/connections` — active connections (and other endpoints)
- `/rci/object-group/fqdn` — FQDN groups of DNS routes

## Tests

Tests are written with the standard `unittest` module — no external dependencies:

```bash
cd /path/to/repo
python -m unittest discover -s tests -v
```

Coverage: data models, interactive host selection, DNS route group selection,
subnet comparison and auto-add, last-choice storage, configuration.

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every **push** and **pull request**:

- Python **3.10**
- `python -m compileall` — syntax check
- `python -m unittest discover -s tests` — unit tests

## Project structure

```
keenetic/
├── keenetic/             # Package
│   ├── __init__.py       # Exports main()
│   ├── __main__.py       # Entry point: python -m keenetic
│   ├── cli.py            # Arguments, interactive menu, main()
│   ├── config.py         # Constants (ROUTER_IP, LOGIN, COLLECT_COUNT...)
│   ├── models.py         # Dataclasses: Host, Connection, RawConn, CollectedHost
│   ├── session.py        # KeeneticSession — cookie-aware HTTP client
│   ├── auth.py           # Challenge-response authentication
│   ├── hosts.py          # Fetching, displaying and selecting hosts
│   ├── connections.py    # Fetching active connections (multi-endpoint)
│   ├── collector.py      # Collect mode: 5 requests + aggregation
│   ├── whois.py          # WHOIS lookups (whois.arin.net:43)
│   ├── static_routes.py  # Google/YouTube subnet comparison with DNS routes
│   └── last_choice.py    # User's last choice (last_choice.json)
├── tests/                # Unit tests (unittest, no dependencies)
│   ├── test_models.py
│   ├── test_hosts.py
│   ├── test_static_routes.py
│   ├── test_last_choice.py
│   ├── test_config.py
│   └── test_collector.py
├── .github/workflows/ci.yml   # CI: tests on push and pull request
├── pyproject.toml        # Package metadata and the 'keenetic' entry point
├── keenetic.sh           # Bash launcher
├── AGENTS.md             # Guidelines for AI assistants
├── LICENSE               # MIT License
├── README.md             # This file
├── last_choice.json      # Last choice (created on run, in .gitignore)
└── .gitignore
```

## Modules (API)

| Module | Purpose | Key functions/classes |
|---|---|---|
| `config.py` | Configuration | `ROUTER_IP`, `LOGIN`, `COLLECT_COUNT`, `DEBUG` (global) |
| `models.py` | Data models | `Host`, `Connection`, `RawConn`, `CollectedHost`, `str_val()`, `parse_connection()` |
| `session.py` | HTTP | `KeeneticSession` — GET/POST with cookie |
| `auth.py` | Authentication | `get_challenge()`, `compute_password_hash()`, `auth_flow()` |
| `hosts.py` | Hosts | `get_hosts()`, `print_hosts()`, `select_host()` |
| `connections.py` | Connections | `get_host_connections()`, `print_connections()`, `CONNECTION_ENDPOINTS` |
| `collector.py` | Collection | `fetch_and_collect()`, `print_collected()` |
| `whois.py` | WHOIS | `WhoisInfo`, `lookup(ip)` |
| `static_routes.py` | Subnet comparison | `compare_google_subnets()`, `select_fqdn_group()`, `get_router_subnets()`, `OBJECT_GROUP_FQDN_ENDPOINT` |
| `last_choice.py` | Last choice | `load_last_choice()`, `save_last_choice()`, `DEFAULT_MODE`, `DEFAULT_PORT` |
| `cli.py` | CLI | `choose_mode_and_port()`, `main()` |

## Requirements

- **Python 3.10+** (type hints: `str \| None`, `list[Host]`)
- **Standard library only** — no dependencies to run
  - `urllib` — HTTP requests
  - `socket` — WHOIS (raw TCP)
  - `hashlib` — MD5/SHA256 for authentication
  - `json`, `dataclasses`, `getpass`, `time` — standard
- For install (`pip install .`) `setuptools` is needed — it ships with every Python
- **Router access:** `http://192.168.1.1` (port 80 by default; IP is configurable via `KEENETIC_ROUTER_IP`)
- **whois.arin.net access:** port 43 (only for WHOIS enrichment)

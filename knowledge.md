# Project knowledge

This file gives Freebuff context about your project: goals, commands, conventions, and gotchas.

## What this is
CLI tool that monitors network connections through a Keenetic router. It authenticates to the router (challenge-response), lists hosts, fetches active connections of a chosen host, aggregates remote IPs, and enriches them with WHOIS data (whois.arin.net:43). Three modes: collect (5 requests), one-shot snapshot, and DNS route audit (finds/fixes duplicate and overlapping subnets in FQDN groups).

The repo root is the project root; the Python package lives in `keenetic/keenetic/`, tests in `tests/`, packaging in `pyproject.toml` (entry point `keenetic = keenetic.cli:main`).

## Quickstart
- **Run:** `./keenetic.sh` (auto-finds Python 3; `--debug` flag supported) — needs `KEENETIC_ROUTER_PASSWORD` env var set, else prompts interactively
- **Direct run:** `python -m keenetic` from the repo root (launcher sets `PYTHONPATH` to repo root), or `pip install .` then the `keenetic` command
- **Dev:** Python 3.10+; **stdlib only** — no runtime deps, no requirements.txt. Build backend: setuptools (in pyproject.toml)
- **Test:** `python -m unittest discover -s tests -v` (unittest, no deps). Sanity checks: `python -c "from keenetic.cli import main"` and `python -c "import ast; ast.parse(open('X.py').read())"`
- **CI:** `.github/workflows/ci.yml` — GitHub Actions, Python 3.10, compileall + unittest, on push and pull_request
- **Env vars:** `KEENETIC_ROUTER_IP` (default `192.168.1.1`) and `KEENETIC_ROUTER_PASSWORD` (optional; prompts interactively if unset)

## Architecture
- `keenetic/config.py` — constants (`ROUTER_IP` from env `KEENETIC_ROUTER_IP`, default `192.168.1.1`; `LOGIN=admin`, `COLLECT_COUNT=5`, `DEBUG` global)
- `auth.py` — challenge-response auth: `MD5(login:realm:password)` then `SHA256(challenge + hash)`; POST `/auth`, gets session cookie
- `session.py` — `KeeneticSession` HTTP client (urllib, cookie-aware); `post_parse(commands)` POSTs `[{"parse": "<cli>"}]` to `/rci/` to run CLI commands on the router (the same mechanism as the web UI console)
- `hosts.py` — fetch/list/select hosts from `/rci/show/ip/hotspot`
- `connections.py` — `get_host_connections()` tries `CONNECTION_ENDPOINTS` (e.g. `/rci/show/ip/connections`, `/rci/show/ip/nat`); `print_connections()`
- `collector.py` — collect mode: N requests every 5s, aggregate unique dst IPs + ports; `port == 0` means "no port filter" (all ports)
- `whois.py` — `WhoisInfo` dataclass + `lookup(ip)` over raw TCP socket to whois.arin.net:43, 8s timeout
- `static_routes.py` — compares Google/YouTube subnets from WHOIS against the router's DNS routes; runs after collect mode. The group for auto-add is chosen by the user at startup (`select_fqdn_group`, Enter — last one, `0` — don't add); missing subnets are auto-added via `POST /rci/object-group/fqdn` (no confirmation) (payload: `{group_name: {description, include: [{address}]}}`, the write replaces include entirely — merge with current entries when adding). Also hosts the standalone audit mode (menu item 3): `run_subnet_audit()` → `find_subnet_conflicts()` detects exact duplicates, subnets covered by a wider one in the same group, cross-group coverage and misaligned (non-canonical) entries; three fix variants are offered (dedupe → also remove covered → also canonicalize), applied only after explicit `y` confirmation via CLI commands through `session.post_parse()` (`no object-group fqdn <g> include <a>` to remove, then `system configuration save`) — a plain POST to `/rci/object-group/fqdn` can only ADD entries, never remove them; `0.0.0.0/0` and `0.0.0.0/32` service values are ignored, domains are not subnets
- `last_choice.py` — user's last choice (host/mode/port/group) in `last_choice.json` (JSON in the repo root, path computed one level up from the `keenetic/` package); Enter in prompts takes the last value; in host selection Enter confirms the last host, `quit`/`exit`/`q` — exit (the word `last` also works like Enter); the group is saved only in `collect` mode, an empty string = explicitly declined auto-add; the file is in .gitignore (personal data)

**DNS static routes (KeeneticOS 4.x, real endpoints, discovered from the web UI JS bundle):**
- `/rci/object-group/fqdn` — FQDN groups: `{name: {description, include: [{address}]}}` — subnets/domains live here (the `/rci/staticRoutes/dns` path does NOT exist on KeeneticOS 4.x — 404)
- `/rci/dns-proxy/route` — the routes: `[{group, interface, auto, reject, index}]` (groups reference names from object-group)
- `cli.py` — interactive menu (`choose_mode_and_port()`, `main()`), sets `config.DEBUG`
- `models.py` — dataclasses (`Host`, `Connection`, `RawConn`, `CollectedHost`) + `str_val()`, `parse_connection()`
- Entry points: `__main__.py` (`python -m keenetic`), `pyproject.toml` script (`keenetic` after `pip install .`), `keenetic.sh` (bash launcher)

Data flow: auth → host list → user selects host → mode (collect 5×5s | snapshot | audit) → filter by port (default 443, 0 = all; skipped in audit mode) → WHOIS enrichment → tables. Mode `audit` is stored in `last_choice.json` like the others.

## Conventions
- **Language: English** — code comments, docstrings, AGENTS.md and README.md are in English
- Python 3.10+ type hints (`str | None`, `list[Host]`); dataclasses for models; lines ~120 chars max
- Internal imports as `import keenetic.config as config`; access mutable config via `config.XXX`
- **Never** `from keenetic.config import DEBUG` — it copies the value and `--debug` breaks. Always `config.DEBUG`
- API responses vary in shape (`{"address": "..."}` or bare string) — use `models.str_val()` for safe extraction
- NAT records have `x_src_ip`/`x_dst_ip` fields — check those when filtering
- README.md is the authoritative user-facing doc; AGENTS.md has AI-assistant guidelines

## Gotchas
- Only reachable from the router's LAN (http://192.168.1.1:80 by default, configurable via `KEENETIC_ROUTER_IP`); WHOIS needs outbound port 43
- No personal data in repo: real router/host IPs are replaced with placeholders; `last_choice.json` (real IPs) and `.agents/` are gitignored; LICENSE is MIT
- `python -m keenetic` only works from the repo root (or with repo root on `PYTHONPATH`); `keenetic.sh` sets it automatically
- Tests: `python -m unittest discover -s tests -v` — no linter configured; validate with the ast.parse / import checks above

# AGENTS.md — guidelines for AI assistants

This file contains recommendations for AI assistants (Claude, Codebuff, Copilot, etc.)
working on the **keenetic** project.

---

## General rules

### Language
- Code, comments and docstrings — **English**.
- AGENTS.md — **English**.
- README.md and user-facing output — **English**.

### Code style
- Python 3.10+ with type hints (`str | None`, `list[Host]`).
- Dataclasses for data models.
- **Standard library only** — no external dependencies (`pip install`).
- `urllib` for HTTP, `socket` for WHOIS, `hashlib` for MD5/SHA256.
- Maximum line length — ~120 characters.

### Imports
- Internal modules are imported via `import keenetic.X as X` or `from keenetic.X import Y`.
- Configuration: `import keenetic.config as config`, access via `config.XXX`.
- **Never** use `from keenetic.config import DEBUG` — it creates a local copy and the `--debug` flag stops working. Always use `config.DEBUG`.

### Module structure

```
keenetic/                  ← repository root
├── keenetic/              ← package
│   ├── __init__.py        → exports main()
│   ├── __main__.py        → python -m keenetic
│   ├── cli.py             → arguments, interactive menu, main()
│   ├── config.py          → constants (ROUTER_IP, LOGIN, DEBUG, COLLECT_COUNT...)
│   ├── models.py          → dataclasses + helpers
│   ├── session.py         → KeeneticSession (HTTP client)
│   ├── auth.py            → challenge-response authentication
│   ├── hosts.py           → fetching/displaying/selecting hosts
│   ├── connections.py     → fetching/displaying active connections
│   ├── collector.py       → collect mode (5 requests + aggregation)
│   ├── whois.py           → WHOIS lookups
│   ├── static_routes.py   → subnet comparison + group selection
│   └── last_choice.py     → user's last choice (last_choice.json)
├── tests/                 → unit tests (unittest, stdlib)
├── pyproject.toml         → package metadata
├── keenetic.sh            → bash launcher
├── AGENTS.md              → this file
└── README.md              → documentation
```

### Debugging
- The global `config.DEBUG` flag enables raw JSON output.
- The flag is set via `--debug` in `cli.py`: `config.DEBUG = True`.

## Main scenarios

### Adding new functionality
1. Decide which module the functionality logically belongs to
2. Create a new module if needed (e.g. `dns.py` for DNS lookups)
3. Wire it up in `cli.py`
4. Check: `python -c "from keenetic.cli import main"`

### Changing configuration
- All tunable parameters live in `keenetic/config.py`
- If a parameter changes at runtime (e.g. `DEBUG`) — **only** via `import keenetic.config as config; config.XXX = val`
- If a parameter is static, `from keenetic.config import XXX` is fine

### Working with the Keenetic API
- Endpoints: `/rci/show/ip/hotspot` (hosts), `/rci/show/ip/connections` and alternatives (connections)
- Responses may come in different formats: `{"address": "..."}` or a plain string
- Use `models.str_val()` for safe value extraction
- NAT records contain `x_src_ip` / `x_dst_ip` fields — check them when filtering
- Authentication: challenge-response (MD5 + SHA256), described in `keenetic/auth.py`
- DNS route fixes are sent as **CLI commands** via `KeeneticSession.post_parse()` (`POST /rci/` with `[{"parse": "<cli>"}]`) followed by `system configuration save` —
  `POST /rci/object-group/fqdn` can only **add** group entries, it cannot remove them

### Testing
- Unit tests: `python -m unittest discover -s tests -v` (from the repository root)
- `./keenetic.sh` or `python -m keenetic` — full run (from the repository root)
- Import check: `python -c "from keenetic.cli import main"`
- Syntax check: `python -c "import ast; ast.parse(open('path/to/file.py').read())"`

## Typical tasks

### Adding a new connection endpoint
Extend the `CONNECTION_ENDPOINTS` list in `keenetic/connections.py`.

### Adding a new audit check
Extend `find_subnet_conflicts()` in `keenetic/static_routes.py` (new key in the returned dict),
print it in `run_subnet_audit()`, cover with tests in `tests/test_static_routes.py`.

### Adding a new output field
- If the field comes from the API: add a key to `_pick()` in `models.parse_connection()`
- If it's a new model field: extend the corresponding dataclass
- Update the output in `print_connections()` (connections.py) or `print_collected()` (collector.py)

### Adding a new data source (not WHOIS)
- Create a module `keenetic/new_source.py` with a `lookup(ip) -> SomeInfo` function
- Call it from `print_collected()` or from a new mode in `cli.py`
- Format: a dataclass with fields + a `lookup(ip) -> Dataclass` function, errors in the `error` field

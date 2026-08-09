# Project knowledge

This file gives Freebuff context about your project: goals, commands, conventions, and gotchas.

## What this is
CLI tool that monitors network connections through a Keenetic router. It authenticates to the router (challenge-response), lists hosts, fetches active connections of a chosen host, aggregates remote IPs, and enriches them with WHOIS data (whois.arin.net:43).

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
- `session.py` — `KeeneticSession` HTTP client (urllib, cookie-aware)
- `hosts.py` — fetch/list/select hosts from `/rci/show/ip/hotspot`
- `connections.py` — `get_host_connections()` tries `CONNECTION_ENDPOINTS` (e.g. `/rci/show/ip/connections`, `/rci/show/ip/nat`); `print_connections()`
- `collector.py` — collect mode: N requests every 5s, aggregate unique dst IPs + ports
- `whois.py` — `WhoisInfo` dataclass + `lookup(ip)` over raw TCP socket to whois.arin.net:43, 8s timeout
- `static_routes.py` — сравнение подсетей Google/YouTube из WHOIS со списком DNS-маршрутов роутера; вызывается после режима сбора. Группа для автодобавления выбирается пользователем при старте (`select_fqdn_group`, Enter — последняя, `0` — не добавлять); при наличии отсутствующих подсетей автоматически добавляет их через `POST /rci/object-group/fqdn` (без подтверждения) (payload: `{имя_группы: {description, include: [{address}]}}`, запись целиком заменяет include — при добавлении нужно сливать с текущими записями)
- `last_choice.py` — последний выбор пользователя (хост/режим/порт/группа) в `last_choice.json` (JSON в корне репозитория, путь вычисляется от пакета `keenetic/` на уровень вверх); Enter в промптах берёт последнее значение; в выборе хоста Enter подтверждает последний хост, `quit`/`exit`/`q`/`выход` — выход (слово `last` тоже работает как Enter); группа сохраняется только в режиме `collect`, пустая строка = явный отказ от автодобавления; файл в .gitignore (личные данные)

**DNS-статические маршруты (KeeneticOS 4.x, реальные эндпоинты, найдены по JS бандлу веб-интерфейса):**
- `/rci/object-group/fqdn` — группы доменных имён: `{имя: {description, include: [{address}]}}` — здесь лежат подсети/домены (адрес `/rci/staticRoutes/dns` на KeeneticOS 4.x НЕ существует — 404)
- `/rci/dns-proxy/route` — сами маршруты: `[{group, interface, auto, reject, index}]` (группы ссылаются на имена из object-group)
- `cli.py` — interactive menu (`choose_mode_and_port()`, `main()`), sets `config.DEBUG`
- `models.py` — dataclasses (`Host`, `Connection`, `RawConn`, `CollectedHost`) + `str_val()`, `parse_connection()`
- Entry points: `__main__.py` (`python -m keenetic`), `pyproject.toml` script (`keenetic` after `pip install .`), `keenetic.sh` (bash launcher)

Data flow: auth → host list → user selects host → mode (collect 5×5s | snapshot) → filter by port (default 443, 0 = all) → WHOIS enrichment → tables.

## Conventions
- **Language: Russian** — code comments, docstrings, and AGENTS.md are in Russian; project targets a Russian-speaking user
- Python 3.10+ type hints (`str | None`, `list[Host]`); dataclasses for models; lines ~120 chars max
- Internal imports as `import keenetic.config as config`; access mutable config via `config.XXX`
- **Never** `from keenetic.config import DEBUG` — it copies the value and `--debug` breaks. Always `config.DEBUG`
- API responses vary in shape (`{"address": "..."}` or bare string) — use `models.str_val()` for safe extraction
- NAT records have `x_src_ip`/`x_dst_ip` fields — check those when filtering
- README.md (Russian) is the authoritative user-facing doc; AGENTS.md has AI-assistant guidelines

## Gotchas
- Only reachable from the router's LAN (http://192.168.1.1:80 by default, configurable via `KEENETIC_ROUTER_IP`); WHOIS needs outbound port 43
- No personal data in repo: real router/host IPs are replaced with placeholders; `last_choice.json` (real IPs) and `.agents/` are gitignored; LICENSE is MIT
- `python -m keenetic` only works from the repo root (or with repo root on `PYTHONPATH`); `keenetic.sh` sets it automatically
- Tests: `python -m unittest discover -s tests -v` — no linter configured; validate with the ast.parse / import checks above

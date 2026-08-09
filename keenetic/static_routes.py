"""Сравнение подсетей Google/YouTube с DNS-статическими маршрутами роутера.

KeeneticOS 4.x (Keenetic Giga и новее) хранит DNS-статические маршруты так:
  - /rci/dns-proxy/route      — сами маршруты: [{group, interface, auto, ...}]
  - /rci/object-group/fqdn    — группы доменных имён: {имя: {include: [{address}]}}

Подсети и домены лежат в записях include групп (поле "address"). Скрипт после
WHOIS-обогащения (режим сбора) выбирает подсети Google/YouTube, сравнивает их
с подсетями на роутере и выводит отсутствующие. Пользователь при старте
скрипта выбирает группу DNS-маршрутов, в которую будут добавляться
отсутствующие подсети (последний выбор сохраняется в last_choice.json).

Эндпоинты найдены по ключам из бандла веб-интерфейса KeeneticOS
("dns-proxy.route", "object-group.fqdn").
"""

import ipaddress
import json
import sys

import keenetic.config as config

from keenetic.session import KeeneticSession
from keenetic.whois import WhoisInfo

# Эндпоинт групп доменных имён DNS-статических маршрутов KeeneticOS 4.x
OBJECT_GROUP_FQDN_ENDPOINT = "/rci/object-group/fqdn"

# Ключевые слова для определения принадлежности подсети Google/YouTube
# (ищутся в OrgName / Organization из WHOIS, без учёта регистра)
GOOGLE_ORG_KEYWORDS = ("google", "youtube")


# ---------------------------------------------------------------------------
# Получение данных с роутера
# ---------------------------------------------------------------------------

def _safe_json(session: KeeneticSession, path: str) -> dict | list | None:
    """GET-запрос с безопасным JSON-разбором (и выводом в DEBUG)."""
    data, status = session.get(path)
    if status != 200:
        print(f"[!] Ошибка получения {path}: HTTP {status}")
        return None

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print(f"[!] Роутер вернул не-JSON ответ на запрос {path}.")
        return None

    if config.DEBUG:
        preview = json.dumps(parsed, indent=2, ensure_ascii=False)[:2000]
        print(f"[DEBUG] {path} → {preview}")
    return parsed


def get_fqdn_groups_full(session: KeeneticSession) -> dict[str, dict] | None:
    """Полные группы доменных имён: {имя: {description, include: [{address}]}}."""
    parsed = _safe_json(session, OBJECT_GROUP_FQDN_ENDPOINT)
    if parsed is None:
        return None

    groups: dict[str, dict] = {}
    if isinstance(parsed, dict):
        for name, group in parsed.items():
            if not isinstance(group, dict):
                continue
            include = group.get("include")
            if not isinstance(include, list):
                include = []
            entries = [
                e for e in include
                if isinstance(e, dict) and isinstance(e.get("address"), str)
            ]
            groups[name] = {
                "description": group.get("description") or "",
                "include": entries,
            }
    return groups


def get_fqdn_groups(session: KeeneticSession) -> dict[str, list[str]] | None:
    """Группы доменных имён: {имя_группы: [подсеть/домен, ...]}."""
    full = get_fqdn_groups_full(session)
    if full is None:
        return None
    return {name: [e["address"] for e in g["include"]] for name, g in full.items()}


def extract_subnets(addresses: list[str]) -> set[str]:
    """Канонизирует список адресов/подсетей (и отбрасывает 0.0.0.0)."""
    subnets: set[str] = set()
    for address in addresses:
        try:
            net = ipaddress.ip_network(address, strict=False)
        except ValueError:
            continue  # не IP — домен или мусор, не участвует в сравнении
        if str(net) in ("0.0.0.0/32", "0.0.0.0/0"):
            continue  # служебное значение
        subnets.add(str(net))
    return subnets


def get_router_subnets(session: KeeneticSession) -> tuple[set[str], int] | None:
    """Подсети из DNS-маршрутов роутера и число доменных записей в группах.

    Возвращает (подсети, количество доменных записей). Домены не участвуют
    в сравнении подсетей, но о них нужно сообщить пользователю.
    """
    groups = get_fqdn_groups(session)
    if groups is None:
        return None

    if config.DEBUG:
        print(f"[DEBUG] Групп DNS-маршрутов: {len(groups)}")

    all_addresses = [a for addresses in groups.values() for a in addresses]
    subnets = extract_subnets(all_addresses)
    domain_count = 0
    for address in all_addresses:
        try:
            ipaddress.ip_network(address, strict=False)
        except ValueError:
            domain_count += 1
    return subnets, domain_count


# ---------------------------------------------------------------------------
# Фильтр подсетей Google/YouTube из WHOIS
# ---------------------------------------------------------------------------

def google_subnets_from_whois(whois_cache: dict[str, WhoisInfo]) -> dict[str, str]:
    """Подсети Google/YouTube из WHOIS: {cidr: организация}."""
    found: dict[str, str] = {}
    for wi in whois_cache.values():
        if wi is None or wi.error or not wi.cidr:
            continue
        org = (wi.org_name or wi.organization or "").lower()
        if not any(k in org for k in GOOGLE_ORG_KEYWORDS):
            continue
        try:
            net = ipaddress.ip_network(wi.cidr, strict=False)
        except ValueError:
            continue
        cidr = str(net)
        if cidr not in found:
            found[cidr] = wi.org_name or wi.organization
    return found


# ---------------------------------------------------------------------------
# Сравнение и вывод
# ---------------------------------------------------------------------------

def _is_covered(cidr: str, router_subnets: set[str]) -> bool:
    """Покрыта ли подсеть уже имеющимися на роутере маршрутами.

    Подсеть считается покрытой, если на роутере есть та же подсеть
    или более широкая, содержащая её целиком.
    """
    try:
        found = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False

    for rs in router_subnets:
        try:
            net = ipaddress.ip_network(rs, strict=False)
        except ValueError:
            continue
        if found == net or found.subnet_of(net):
            return True
    return False


def _sorted_subnets(found: dict[str, str]) -> list[tuple[str, str]]:
    """Сортирует подсети в числовом порядке (по адресу сети и префиксу)."""
    def _key(item: tuple[str, str]):
        net = ipaddress.ip_network(item[0], strict=False)
        return int(net.network_address), net.prefixlen

    return sorted(found.items(), key=_key)


def compare_google_subnets(session: KeeneticSession,
                           whois_cache: dict[str, WhoisInfo],
                           group_name: str | None = None) -> None:
    """Сравнивает подсети Google/YouTube из WHOIS со списком DNS-маршрутов роутера.

    Выводит на экран найденные подсети и отдельно — отсутствующие на роутере.
    Если передано имя группы (group_name) — автоматически добавляет
    отсутствующие подсети в неё.
    """
    found = google_subnets_from_whois(whois_cache)
    if not found:
        print("\n[!] Среди найденных хостов нет подсетей Google/YouTube — сравнение пропущено.")
        return

    print(f"\n[*] Запрашиваем DNS-статические маршруты роутера ({OBJECT_GROUP_FQDN_ENDPOINT})...")
    router_result = get_router_subnets(session)
    if router_result is None:
        return
    router_subnets, domain_count = router_result

    if domain_count:
        print(f"  [i] В группах маршрутов {domain_count} доменных записей — они не участвуют в сравнении подсетей.")

    missing = {
        cidr: org for cidr, org in found.items()
        if not _is_covered(cidr, router_subnets)
    }
    _print_result(found, missing)

    if missing:
        if group_name:
            _add_missing_subnets(session, missing, group_name)
        else:
            print("  [i] Автоматическое добавление пропущено (группа не выбрана).")


# ---------------------------------------------------------------------------
# Выбор группы для добавления и запись на роутер
# ---------------------------------------------------------------------------

def select_fqdn_group(session: KeeneticSession,
                      last_group: str | None = None) -> str | None:
    """Интерактивный выбор группы DNS-маршрутов для автодобавления подсетей.

    Пользователь выбирает группу по номеру, имени или описанию.
    Enter — последняя выбранная группа (если есть), иначе первая в списке;
    '0' — не добавлять автоматически (возвращает None).
    """
    full_groups = get_fqdn_groups_full(session)
    if full_groups is None:
        return None
    if not full_groups:
        print("  [!] На роутере нет групп DNS-маршрутов — автодобавление отключено.")
        return None

    # Группы с описанием — выше, остальные сортируем по имени
    items = sorted(
        full_groups.items(),
        key=lambda kv: (not (kv[1].get("description") or ""), kv[0].lower()),
    )

    # По умолчанию: последняя группа, «не добавлять» или первая в списке
    default = 1
    if last_group:
        default = next((i for i, (n, _) in enumerate(items, 1) if n == last_group), 1)
    elif last_group == "":
        default = 0  # пользователь ранее отказался от автодобавления

    print(f"\n{'─' * 80}")
    print("  Выберите группу DNS-маршрутов для автодобавления отсутствующих подсетей:")
    for i, (name, group) in enumerate(items, 1):
        desc = group.get("description") or ""
        count = len(group.get("include") or [])
        marker = "  ◀ последняя" if name == last_group else ""
        print(f"    {i:<3} {name:<26} «{desc}» ({count} зап.){marker}")
    print("    0    Не добавлять автоматически")
    print(f"{'─' * 80}")

    while True:
        try:
            raw = input(f"  Группа [{default}]: ").strip()
            if raw == "":
                return None if default == 0 else items[default - 1][0]
            if raw == "0":
                return None
            try:
                idx = int(raw)
            except ValueError:
                idx = None
            if idx is not None:
                if 1 <= idx <= len(items):
                    return items[idx - 1][0]
                print(f"  [!] Номер от 1 до {len(items)} или 0")
                continue
            # Поиск по имени или описанию (частичное совпадение)
            raw_lower = raw.lower()
            matches = [
                n for n, g in full_groups.items()
                if raw_lower in n.lower() or raw_lower in (g.get("description") or "").lower()
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print(f"  [!] Несколько совпадений: {', '.join(matches)}")
            else:
                print(f"  [!] Группа '{raw}' не найдена")
        except (KeyboardInterrupt, EOFError):
            print("\nВыход.")
            sys.exit(0)


def build_group_payload(group_name: str, description: str,
                        current_entries: list[dict],
                        new_addresses: list[str]) -> dict:
    """Payload для записи группы: существующие записи + новые, без дублей."""
    seen: set[str] = set()
    include: list[dict] = []
    for entry in current_entries:
        address = entry.get("address")
        if address in seen:
            continue
        seen.add(address)
        include.append({"address": address})
    for address in new_addresses:
        if address in seen:
            continue
        seen.add(address)
        include.append({"address": address})
    return {group_name: {"description": description, "include": include}}


def _status_has_errors(value) -> bool:
    """Ищет 'status': 'error' в статусном дереве ответа роутера."""
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str) and status.lower() == "error":
            return True
        return any(_status_has_errors(v) for v in value.values())
    if isinstance(value, list):
        return any(_status_has_errors(v) for v in value)
    return False


def write_fqdn_group(session: KeeneticSession, payload: dict) -> bool:
    """Записывает группу доменных имён на роутер. True — успех."""
    data, status = session.post_json(OBJECT_GROUP_FQDN_ENDPOINT, payload)
    if status != 200:
        return False
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return True  # ответ не разобрали — полагаемся на HTTP 200
    return not _status_has_errors(parsed)


def _add_missing_subnets(session: KeeneticSession, missing: dict[str, str],
                         group_name: str) -> None:
    """Автоматически добавляет отсутствующие подсети в выбранную группу."""
    full_groups = get_fqdn_groups_full(session)
    if full_groups is None:
        return
    if group_name not in full_groups:
        print(f"  [!] Группа «{group_name}» не найдена на роутере — добавление пропущено.")
        return

    group = full_groups[group_name]
    payload = build_group_payload(
        group_name, group["description"], group["include"], list(missing.keys()),
    )
    print(f"  [i] Добавляем отсутствующие подсети ({len(missing)}) в группу «{group['description']}» ({group_name})...")
    if not write_fqdn_group(session, payload):
        print("  [!] Не удалось записать группу на роутер.")
        return

    print(f"  [✓] Подсети добавлены в группу {group_name} («{group['description']}»):")
    for cidr in sorted(missing):
        print(f"      • {cidr}  ({missing[cidr] or '-'})")


def _print_result(found: dict[str, str], missing: dict[str, str]) -> None:
    """Выводит результат сравнения подсетей с DNS-маршрутами роутера."""
    present = len(found) - len(missing)

    print(f"\n{'═' * 100}")
    print("  🌐 Подсети Google/YouTube: сравнение с DNS-маршрутами роутера")
    print(f"  Найдено подсетей: {len(found)}  |  Уже на роутере: {present}  |  Отсутствует: {len(missing)}")
    print(f"{'═' * 100}")

    print(f"\n  {'#':<4} {'Подсеть':<24} {'Организация':<32} {'Статус'}")
    print(f"  {'─' * 96}")
    for i, (cidr, org) in enumerate(_sorted_subnets(found), 1):
        status = "✗ отсутствует" if cidr in missing else "✓ есть на роутере"
        print(f"  {i:<4} {cidr:<24} {(org or '-'):<32} {status}")
    print(f"  {'─' * 96}")

    if missing:
        print(f"\n  ⚠️  Отсутствующие подсети ({len(missing)}) — их нет в DNS-маршрутах роутера:")
        for cidr, org in _sorted_subnets(missing):
            print(f"    • {cidr}  ({org or '-'})")
    else:
        print("\n  ✅ Все найденные подсети Google/YouTube уже есть на роутере.")

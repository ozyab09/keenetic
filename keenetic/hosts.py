"""Получение, отображение и интерактивный выбор хостов из Keenetic API."""

import json
import sys

import keenetic.config as config

from keenetic.models import Host, str_val
from keenetic.session import KeeneticSession


def get_hosts(session: KeeneticSession) -> list[Host]:
    """Получает список всех хостов через /rci/show/ip/hotspot."""
    data, status = session.get("/rci/show/ip/hotspot")
    if status != 200:
        print(f"[!] Ошибка получения хостов: HTTP {status}")
        sys.exit(1)

    parsed = json.loads(data.decode("utf-8"))
    if config.DEBUG:
        print(f"\n[DEBUG] /rci/show/ip/hotspot → {json.dumps(parsed, indent=2, ensure_ascii=False)[:2000]}")

    raw_list = parsed.get("host", parsed.get("hotspot", []))

    hosts: list[Host] = []
    for i, h in enumerate(raw_list, 1):
        active_raw = h.get("active", h.get("online", False))
        active = active_raw is True or str(active_raw) in ("yes", "1", "True")
        hosts.append(Host(
            index=i,
            ip=str_val(h.get("ip")),
            mac=str_val(h.get("mac")),
            name=str_val(h.get("name") or h.get("hostname")),
            interface=str_val(h.get("interface", h.get("iface"))),
            active=active,
        ))
    return hosts


def print_hosts(hosts: list[Host]):
    """Выводит таблицу хостов."""
    if not hosts:
        print("\n[!] Нет подключённых клиентов.")
        return

    print(f"\n{'─' * 88}")
    print(f"  {'#':<3} {'IP':<16} {'MAC':<18} {'Имя':<24} {'Интерфейс':<12} {'Статус'}")
    print(f"{'─' * 88}")
    for h in hosts:
        status = "● ONLINE" if h.active else "○ OFFLINE"
        print(f"  {h.index:<3} {h.ip:<16} {h.mac:<18} {h.name:<24} {h.interface:<12} {status}")
    print(f"{'─' * 88}")
    print(f"  Всего хостов: {len(hosts)}")


def select_host(hosts: list[Host], last_ip: str | None = None) -> Host:
    """Интерактивный выбор хоста по номеру, IP или имени.

    Enter — подтверждает последний выбранный хост (если он есть).
    'quit' (или 'exit', 'q', 'выход') — выход из программы.
    Слово 'last' работает как и Enter — выбирает последний хост.
    """
    last_host = None
    if last_ip:
        last_host = next((h for h in hosts if h.ip == last_ip), None)

    while True:
        try:
            if last_host is not None:
                last_name = last_host.name or last_host.ip
                prompt = (f"\n🔍 Выберите хост (номер / IP / имя, Enter — {last_name} "
                          f"({last_host.ip}), 'quit' для выхода): ")
            else:
                prompt = "\n🔍 Выберите хост (номер / IP / имя, Enter или 'quit' для выхода): "
            raw = input(prompt).strip()
            if not raw:
                if last_host is not None:
                    return last_host  # Enter — подтвердить последний хост
                print("Выход.")
                sys.exit(0)

            if raw.lower() in ("quit", "exit", "q", "выход"):
                print("Выход.")
                sys.exit(0)

            # Быстрый выбор последнего хоста (то же, что Enter)
            if last_host is not None and raw.lower() == "last":
                return last_host

            # Попытка по номеру
            try:
                idx = int(raw)
                if 1 <= idx <= len(hosts):
                    return hosts[idx - 1]
            except ValueError:
                pass

            # Поиск по IP или имени (частичное совпадение)
            raw_lower = raw.lower()
            matches = [
                h for h in hosts
                if raw_lower in h.ip.lower()
                or raw_lower in h.name.lower()
                or raw_lower in h.mac.lower()
            ]
            if len(matches) == 1:
                return matches[0]
            elif len(matches) > 1:
                print(f"  Найдено несколько совпадений:")
                for m in matches:
                    print(f"    {m.index:>3}. {m.ip:<16} {m.mac:<18} {m.name:<24}")
                continue
            else:
                print(f"  [!] Ничего не найдено по запросу '{raw}'")
        except KeyboardInterrupt:
            print("\nВыход.")
            sys.exit(0)

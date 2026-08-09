"""Главный модуль: аргументы, интерактивное меню, точка входа main()."""

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
from keenetic.static_routes import compare_google_subnets, select_fqdn_group


def choose_mode_and_port(mode_default: str = DEFAULT_MODE,
                         port_default: int = DEFAULT_PORT) -> tuple[str, int]:
    """Интерактивный выбор режима и порта.

    По умолчанию (Enter) предлагается последний выбор пользователя,
    а если его нет — стандартные значения (режим сбора, порт 443).
    """
    if mode_default not in ("collect", "once"):
        mode_default = DEFAULT_MODE
    if not isinstance(port_default, int) or not (port_default == 0 or 1 <= port_default <= 65535):
        port_default = DEFAULT_PORT

    default_mode_label = "2" if mode_default == "once" else "1"

    print(f"\n{'─' * 50}")
    print("  Выберите режим:")
    print(f"    1. Сбор удалённых хостов (5 запросов, интервал {config.fmt_interval(config.COLLECT_INTERVAL)})")
    print("    2. Одноразовый снимок соединений")
    print(f"{'─' * 50}")

    while True:
        try:
            raw = input(f"  Режим [{default_mode_label}]: ").strip()
            if raw == "":
                mode = mode_default
                break
            elif raw == "1":
                mode = "collect"
                break
            elif raw == "2":
                mode = "once"
                break
            else:
                print("  [!] Введите 1 или 2")
        except KeyboardInterrupt:
            print("\nВыход.")
            sys.exit(0)

    while True:
        try:
            raw = input(f"  Порт для фильтрации [{port_default}] (0 — все порты): ").strip()
            if raw == "":
                port = port_default
                break
            port = int(raw)
            if port == 0 or 1 <= port <= 65535:
                break
            print("  [!] Порт должен быть от 1 до 65535 (0 — показать все)")
        except ValueError:
            print("  [!] Введите число")
        except KeyboardInterrupt:
            print("\nВыход.")
            sys.exit(0)

    return mode, port


def main():
    # ─── Аргументы ──────────────────────────────────────────────
    for a in sys.argv[1:]:
        if a in ("--debug", "-d"):
            config.DEBUG = True
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            print(f"[!] Неизвестный аргумент: {a}\n")
            print(__doc__)
            sys.exit(1)

    # ─── Пароль ─────────────────────────────────────────────────
    password = os.environ.get("KEENETIC_ROUTER_PASSWORD")
    if password:
        print("[*] Пароль из KEENETIC_ROUTER_PASSWORD")
    else:
        password = getpass(f"🔑 Пароль для {config.LOGIN}@{config.ROUTER_IP}: ")

    session = KeeneticSession()
    print(f"\n[*] Подключение к {config.BASE_URL}...")

    # ─── Авторизация ────────────────────────────────────────────
    auth_flow(session, password)

    # ─── Список хостов ──────────────────────────────────────────
    print("[*] Запрашиваем список хостов...")
    hosts = get_hosts(session)
    print_hosts(hosts)

    # ─── Последний выбор пользователя ───────────────────────────
    last = load_last_choice()
    last_host_value = last.get("host")
    last_ip = last_host_value if isinstance(last_host_value, str) else None

    # ─── Выбор хоста ────────────────────────────────────────────
    host = select_host(hosts, last_ip=last_ip)
    print(f"\n[✓] Выбран хост: {host.ip} ({host.name})")

    # ─── Выбор режима и порта ───────────────────────────────────
    mode, port = choose_mode_and_port(
        mode_default=last.get("mode", DEFAULT_MODE),
        port_default=last.get("port", DEFAULT_PORT),
    )

    # ─── Группа DNS-маршрутов для автодобавления подсетей ────────
    # Предлагается при старте в режиме сбора (Enter — последняя группа).
    group_name = None
    if mode == "collect":
        last_group = last.get("group")
        group_name = select_fqdn_group(
            session, last_group if isinstance(last_group, str) else None,
        )
    save_last_choice(host.ip, mode, port, group_name)

    if mode == "once":
        # ─── Снимок ─────────────────────────────────────────────
        print(f"\n[*] Одноразовый снимок (порт {port})...")
        conns = get_host_connections(session, host)
        print_connections(conns, host, port_filter=port if port else None)
    else:
        # ─── Сбор ───────────────────────────────────────────────
        total_sec = config.COLLECT_INTERVAL * (config.COLLECT_COUNT - 1)
        print(f"\n{'═' * 60}")
        print(f"  📡 СБОР УДАЛЁННЫХ ХОСТОВ")
        print(f"  Локальный хост: {host.ip} ({host.name})")
        port_str = port_label(port) if port == 0 else str(port)
        print(f"  Порт: {port_str}  |  Запросов: {config.COLLECT_COUNT}  |  Интервал: {config.fmt_interval(config.COLLECT_INTERVAL)}")
        print(f"  Общая длительность: ~{config.fmt_interval(total_sec)}")
        print(f"{'═' * 60}")

        collected: dict[str, CollectedHost] = {}

        for i in range(1, config.COLLECT_COUNT + 1):
            if i > 1:
                now_str = time.strftime("%H:%M:%S")
                print(f"  ⏳ Ожидание {config.fmt_interval(config.COLLECT_INTERVAL)} до запроса {i}...  (текущее время: {now_str})", flush=True)
                time.sleep(config.COLLECT_INTERVAL)
            fetch_and_collect(session, host, collected, i, config.COLLECT_COUNT, port)
            print(f"  ✅ Запрос {i} выполнен", flush=True)

        whois_cache = print_collected(collected, host, port)
        compare_google_subnets(session, whois_cache, group_name)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Отменено пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Ошибка: {e}")
        sys.exit(1)

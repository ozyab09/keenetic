"""Получение и отображение активных соединений из Keenetic API."""

import json
import sys

import keenetic.config as config

from keenetic.models import (
    Host, Connection, parse_connection, ips_for_host, to_connection,
)
from keenetic.session import KeeneticSession


# Эндпоинты для активных соединений (в порядке приоритета)
CONNECTION_ENDPOINTS = [
    "/rci/show/ip/connections",
    "/rci/show/ip/conntrack",
    "/rci/show/ip/nat",
    "/rci/status/connection",
    "/rci/show/ip/accounting",
]


def try_get_connections(session: KeeneticSession, endpoint: str) -> tuple[dict, int] | None:
    """Пробует получить соединения по endpoint'у. Возвращает (parsed, status) или None."""
    if config.DEBUG:
        print(f"\n[DEBUG] Пробуем {endpoint}...")
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
    """Перебирает эндпоинты, пока не получит список соединений."""
    for ep in CONNECTION_ENDPOINTS:
        result = try_get_connections(session, ep)
        if result is None:
            continue
        parsed, _ = result

        # Keenetic может вернуть как dict с ключами, так и список напрямую
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
            print(f"[✓] Эндпоинт: {ep}")
            return raw

    print("[!] Ни один эндпоинт не вернул данные о соединениях.")
    return None


def get_host_connections(session: KeeneticSession, host: Host) -> list[Connection]:
    """Получает все соединения, в которых участвует выбранный хост."""
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
# Вывод
# ---------------------------------------------------------------------------

def _port_filter_label(port_filter: int | None) -> str:
    """Метка фильтра: None → «все порты»."""
    return "все порты" if port_filter is None else f"порт {port_filter}"


def print_connections(conns: list[Connection], host: Host, port_filter: int | None = 443):
    """Выводит соединения для хоста, опционально отфильтрованные по порту."""
    if not conns:
        print(f"\n[!] Нет соединений для {host.ip} ({host.name})")
        return

    if port_filter is not None:
        filtered = [
            c for c in conns
            if c.dst_port == str(port_filter) or c.src_port == str(port_filter)
        ]
    else:
        filtered = conns

    print(f"\n{'═' * 108}")
    print(f"  Хост: {host.ip} ({host.name}) — {host.mac}")
    if port_filter:
        print(f"  Фильтр: порт {port_filter}")
    print(f"{'═' * 108}")

    if not filtered:
        print(f"\n  [!] Нет соединений ({_port_filter_label(port_filter)}).")
        if port_filter is not None:
            print(f"  Всего соединений хоста: {len(conns)} (показать все: порт 0)")
        return

    print(f"\n  {'Протокол':<8} {'Src IP':<20} {'Порт':<8} {'':>2} {'Dst IP':<20} {'Порт':<8} {'Состояние':<14} {'RX':<10} {'TX'}")
    print(f"  {'─' * 106}")

    for c in filtered:
        if c.src_ip == host.ip:
            print(f"  {c.protocol:<8} {c.src_ip:<20} {c.src_port:<8} → {c.dst_ip:<20} {c.dst_port:<8} {c.state:<14} {c.bytes_in:<10} {c.bytes_out}")
        else:
            print(f"  {c.protocol:<8} {c.src_ip:<20} {c.src_port:<8} ← {c.dst_ip:<20} {c.dst_port:<8} {c.state:<14} {c.bytes_in:<10} {c.bytes_out}")

    print(f"  {'─' * 106}")
    print(f"  Всего: {len(filtered)} соединений ({_port_filter_label(port_filter)})")

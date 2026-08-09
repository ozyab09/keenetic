"""Режим сбора: несколько запросов к API с агрегацией удалённых хостов."""

import time

import keenetic.config as config

from keenetic.connections import get_all_endpoint_connections
from keenetic.models import (
    Host, CollectedHost, parse_connection, ips_for_host, to_connection,
)
from keenetic.session import KeeneticSession
from keenetic.whois import WhoisInfo, lookup as whois_lookup


def port_label(port: int) -> str:
    """Человекочитаемая метка порта: 0 → «все порты»."""
    return "все порты" if port == 0 else f"порт {port}"


def fetch_and_collect(
    session: KeeneticSession,
    host: Host,
    collected: dict[str, CollectedHost],
    sample: int,
    total: int,
    port: int,
):
    """Один цикл: запрос соединений → извлечение удалённых хостов → агрегация."""
    print(f"\n  [{sample}/{total}] Запрос соединений...", end=" ", flush=True)

    try:
        raw_list = get_all_endpoint_connections(session)
    except Exception as e:
        print(f"[!] Ошибка: {e}")
        return

    if not raw_list:
        print("нет данных")
        return

    now = time.time()
    count_conns = 0

    for c in raw_list:
        raw = parse_connection(c)
        if raw is None:
            continue
        all_ips = ips_for_host(raw)
        if host.ip not in all_ips:
            continue

        conn = to_connection(raw, host.ip)
        # Порт 0 означает «без фильтра по порту» (все порты)
        if conn.src_ip == host.ip and (port == 0 or conn.dst_port == str(port)):
            dst_ip = conn.dst_ip
            if dst_ip == "-" or dst_ip == host.ip:
                continue
            count_conns += 1

            if dst_ip not in collected:
                collected[dst_ip] = CollectedHost(ip=dst_ip, ports=set(), first_seen=now)
            ch = collected[dst_ip]
            ch.ports.add(conn.dst_port)
            ch.count += 1
            ch.last_seen = now

    print(f"{count_conns} соединений, всего уникальных хостов: {len(collected)}")


def print_collected(collected: dict[str, CollectedHost], host: Host, port: int) -> dict[str, WhoisInfo]:
    """Выводит сводку собранных удалённых хостов с WHOIS-информацией.

    Возвращает кэш WHOIS-ответов {ip: WhoisInfo} для дальнейшего использования
    (например, сравнения подсетей Google/YouTube с маршрутами роутера).
    """
    if not collected:
        print(f"\n[!] Не обнаружено обращений ({port_label(port)}) за {config.COLLECT_COUNT} запросов.")
        return {}

    sorted_hosts = sorted(collected.values(), key=lambda x: -x.count)

    # ── WHOIS-запросы для каждого уникального IP ────────────────
    print("\n[*] Запрашиваем WHOIS-информацию для найденных хостов...", flush=True)
    whois_cache: dict[str, WhoisInfo] = {}
    for i, ch in enumerate(sorted_hosts, 1):
        print(f"  [{i}/{len(sorted_hosts)}] {ch.ip}...", end=" ", flush=True)
        whois_cache[ch.ip] = whois_lookup(ch.ip)
        print("✓" if not whois_cache[ch.ip].error else f"({whois_cache[ch.ip].error})")

    # ── Заголовок ───────────────────────────────────────────────
    total_sec = config.COLLECT_INTERVAL * (config.COLLECT_COUNT - 1)
    print(f"\n{'═' * 130}")
    print(f"  🎯 Удалённые хосты, к которым обращался {host.ip} ({host.name})")
    print(f"     {port_label(port)}, {config.COLLECT_COUNT} запросов с интервалом {config.fmt_interval(config.COLLECT_INTERVAL)}")
    print(f"{'═' * 130}")

    print(f"\n  {'#':<4} {'IP':<16} {'Порты':<10} {'Встр':<6} {'CIDR':<24} {'Организация':<28} {'Первый':<10} {'Последний':<10}")
    print(f"  {'─' * 124}")

    for i, ch in enumerate(sorted_hosts, 1):
        wi = whois_cache.get(ch.ip)
        cidr = wi.cidr if wi and wi.cidr else "-"
        org = wi.org_name or wi.organization or "-" if wi and not wi.error else "-"
        ports_str = ", ".join(sorted((p for p in ch.ports if p != "-"), key=int))
        first = time.strftime("%H:%M:%S", time.localtime(ch.first_seen))
        last = time.strftime("%H:%M:%S", time.localtime(ch.last_seen))
        print(f"  {i:<4} {ch.ip:<16} {ports_str:<10} {ch.count:<6} {cidr:<24} {org:<28} {first:<10} {last}")

    print(f"  {'─' * 124}")
    print(f"  Всего уникальных удалённых хостов: {len(collected)}")

    # ── Детальная WHOIS-информация ──────────────────────────────
    print(f"\n{'═' * 130}")
    print("  📋 Детальная WHOIS-информация")
    print(f"{'═' * 130}")

    for i, ch in enumerate(sorted_hosts, 1):
        wi = whois_cache.get(ch.ip)
        print(f"\n  [{i}] {ch.ip}")
        if wi and not wi.error:
            print(f"      NetRange:      {wi.net_range or '-'}")
            print(f"      CIDR:          {wi.cidr or '-'}")
            print(f"      Organization:  {wi.organization or '-'}")
            print(f"      OrgName:       {wi.org_name or '-'}")
        else:
            error_msg = wi.error if wi else "unknown"
            print(f"      WHOIS: {error_msg}")

    return whois_cache

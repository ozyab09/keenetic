"""WHOIS-запросы через raw TCP-сокеты (только stdlib).

Поля, которые извлекаем из ответа whois.arin.net:
  - NetRange:   диапазон IP-адресов
  - CIDR:       CIDR-нотация
  - Organization: краткое название организации
  - OrgName:    полное название организации
"""

import dataclasses
import socket

WHOIS_SERVER = "whois.arin.net"
WHOIS_PORT = 43
TIMEOUT = 8  # секунд на запрос


@dataclasses.dataclass
class WhoisInfo:
    """Результат WHOIS-запроса."""
    ip: str
    net_range: str = ""
    cidr: str = ""
    organization: str = ""
    org_name: str = ""
    error: str = ""


def lookup(ip: str) -> WhoisInfo:
    """Выполняет WHOIS-запрос для указанного IP и возвращает структурированный результат."""
    info = WhoisInfo(ip=ip)

    try:
        with socket.create_connection((WHOIS_SERVER, WHOIS_PORT), timeout=TIMEOUT) as sock:
            sock.sendall(f"{ip}\r\n".encode("utf-8"))
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        info.error = str(e)
        return info

    raw = response.decode("utf-8", errors="ignore")

    if "No match found" in raw or "No Data Found" in raw:
        info.error = "IP not found in ARIN"
        return info

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("NetRange:"):
            info.net_range = stripped[len("NetRange:"):].strip()
        elif stripped.startswith("CIDR:"):
            info.cidr = stripped[len("CIDR:"):].strip()
        elif stripped.startswith("Organization:"):
            info.organization = stripped[len("Organization:"):].strip()
        elif stripped.startswith("OrgName:"):
            info.org_name = stripped[len("OrgName:"):].strip()

    return info

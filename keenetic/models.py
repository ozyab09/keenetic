"""Модели данных и вспомогательные функции для работы с Keenetic API."""

from dataclasses import dataclass, field


@dataclass
class Host:
    """Локальный хост (клиент роутера)."""
    index: int
    ip: str
    mac: str
    name: str
    interface: str
    active: bool


@dataclass
class Connection:
    """Активное соединение (отображаемое)."""
    src_ip: str
    src_port: str
    dst_ip: str
    dst_port: str
    protocol: str
    state: str
    bytes_in: str
    bytes_out: str


@dataclass
class RawConn:
    """Сырая запись соединения из API, сохраняет все IP-поля для фильтрации."""
    src_ip: str
    x_src_ip: str
    dst_ip: str
    x_dst_ip: str
    src_port: str
    dst_port: str
    protocol: str
    state: str
    bytes_in: str
    bytes_out: str


@dataclass
class CollectedHost:
    """Удалённый хост, к которому обращался локальный хост (режим сбора)."""
    ip: str
    ports: set[str] = field(default_factory=set)
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def str_val(value) -> str:
    """Извлекает строку из значения (строка, dict с 'address'/'name', None, bool, число)."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("address", value.get("name", "-")))
    return str(value)


def _pick(entry: dict, *keys: str) -> str:
    """Берёт первое не-None значение из списка ключей словаря."""
    for k in keys:
        v = entry.get(k)
        if v is not None:
            return str_val(v)
    return "-"


def parse_connection(c: dict) -> RawConn | None:
    """Парсит один элемент соединения из разных форматов Keenetic.

    Keenetic может возвращать поля в разных вариантах:
      - {src: {address:...}, dst: {address:...}, sport, dport, ...}
      - {src_ip: "...", dst_ip: "...", src_port, dst_port, ...}
      - NAT: {src, dst, sport, dport, src-out, dst-out, bytes, bytes-out}
    """
    raw = RawConn(
        src_ip   = _pick(c, "src", "src_ip", "source"),
        x_src_ip = _pick(c, "x_src_ip", "src-out"),
        dst_ip   = _pick(c, "dst", "dst_ip", "dest", "destination"),
        x_dst_ip = _pick(c, "x_dst_ip", "dst-out"),
        src_port = _pick(c, "sport", "src_port", "source_port"),
        dst_port = _pick(c, "dport", "dst_port", "dest_port", "destination_port"),
        protocol = _pick(c, "protocol", "proto"),
        state    = _pick(c, "state"),
        bytes_in = _pick(c, "bytes", "bytes_in", "rx_bytes"),
        bytes_out = _pick(c, "bytes-out", "bytes_out", "tx_bytes"),
    )

    if raw.src_ip == "-" and raw.dst_ip == "-" and raw.x_src_ip == "-" and raw.x_dst_ip == "-":
        return None  # пустая запись

    return raw


def ips_for_host(raw: RawConn) -> set[str]:
    """Собирает все IP-адреса из записи (обычные + NAT)."""
    ips = {raw.src_ip, raw.dst_ip}
    if raw.x_src_ip != "-":
        ips.add(raw.x_src_ip)
    if raw.x_dst_ip != "-":
        ips.add(raw.x_dst_ip)
    ips.discard("-")
    return ips


def to_connection(raw: RawConn, host_ip: str) -> Connection:
    """Преобразует RawConn в Connection, выбирая IP-пару, где присутствует host_ip.

    Если host_ip совпадает с src_ip — это исходящее соединение, src_ip = host_ip.
    Если host_ip совпадает с x_src_ip — NAT-трансляция, src_ip = x_src_ip.
    Аналогично для dst/x_dst (входящие соединения).
    """
    def _pick_ip(primary: str, secondary: str, target: str) -> str:
        """Выбирает IP: сначала совпадающий с target, иначе primary → secondary."""
        if target == primary:
            return primary
        if target == secondary:
            return secondary
        return primary if primary != "-" else secondary

    src_ip = _pick_ip(raw.src_ip, raw.x_src_ip, host_ip)
    dst_ip = _pick_ip(raw.dst_ip, raw.x_dst_ip, host_ip)

    return Connection(
        src_ip=src_ip,
        src_port=raw.src_port,
        dst_ip=dst_ip,
        dst_port=raw.dst_port,
        protocol=raw.protocol,
        state=raw.state,
        bytes_in=raw.bytes_in,
        bytes_out=raw.bytes_out,
    )

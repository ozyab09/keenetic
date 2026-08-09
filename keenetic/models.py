"""Data models and helpers for working with the Keenetic API."""

from dataclasses import dataclass, field


@dataclass
class Host:
    """Local host (a router client)."""
    index: int
    ip: str
    mac: str
    name: str
    interface: str
    active: bool


@dataclass
class Connection:
    """Active connection (displayed)."""
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
    """Raw connection record from the API; keeps all IP fields for filtering."""
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
    """Remote host contacted by the local host (collect mode)."""
    ip: str
    ports: set[str] = field(default_factory=set)
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def str_val(value) -> str:
    """Extracts a string from a value (string, dict with 'address'/'name', None, bool, number)."""
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
    """Returns the first non-None value among the dict keys."""
    for k in keys:
        v = entry.get(k)
        if v is not None:
            return str_val(v)
    return "-"


def parse_connection(c: dict) -> RawConn | None:
    """Parses one connection entry from the different Keenetic formats.

    Keenetic may return fields in different variants:
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
        return None  # empty record

    return raw


def ips_for_host(raw: RawConn) -> set[str]:
    """Collects all IP addresses from a record (regular + NAT)."""
    ips = {raw.src_ip, raw.dst_ip}
    if raw.x_src_ip != "-":
        ips.add(raw.x_src_ip)
    if raw.x_dst_ip != "-":
        ips.add(raw.x_dst_ip)
    ips.discard("-")
    return ips


def to_connection(raw: RawConn, host_ip: str) -> Connection:
    """Converts RawConn into Connection, picking the IP pair that contains host_ip.

    If host_ip matches src_ip it is an outbound connection, so src_ip = host_ip.
    If host_ip matches x_src_ip it is a NAT translation, so src_ip = x_src_ip.
    Likewise for dst/x_dst (inbound connections).
    """
    def _pick_ip(primary: str, secondary: str, target: str) -> str:
        """Picks an IP: first the one matching target, otherwise primary → secondary."""
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

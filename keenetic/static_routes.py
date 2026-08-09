"""Comparing Google/YouTube subnets with the router's DNS static routes.

KeeneticOS 4.x (Keenetic Giga and newer) stores DNS static routes like this:
  - /rci/dns-proxy/route      — the routes: [{group, interface, auto, ...}]
  - /rci/object-group/fqdn    — FQDN groups: {name: {include: [{address}]}}

Subnets and domains live in the "include" entries of the groups (field
"address"). After WHOIS enrichment (collect mode) the script picks
Google/YouTube subnets, compares them with the subnets on the router and
prints the missing ones. At startup the user selects the DNS route group
into which missing subnets are added (the last choice is stored in
last_choice.json).

Endpoints were discovered from the KeeneticOS web UI bundle keys
("dns-proxy.route", "object-group.fqdn").
"""

import ipaddress
import json
import sys

import keenetic.config as config

from keenetic.session import KeeneticSession
from keenetic.whois import WhoisInfo

# Endpoint of FQDN groups for DNS static routes on KeeneticOS 4.x
OBJECT_GROUP_FQDN_ENDPOINT = "/rci/object-group/fqdn"

# Keywords used to tell whether a subnet belongs to Google/YouTube
# (searched in OrgName / Organization from WHOIS, case-insensitive)
GOOGLE_ORG_KEYWORDS = ("google", "youtube")


# ---------------------------------------------------------------------------
# Fetching data from the router
# ---------------------------------------------------------------------------

def _safe_json(session: KeeneticSession, path: str) -> dict | list | None:
    """GET request with safe JSON parsing (and DEBUG output)."""
    data, status = session.get(path)
    if status != 200:
        print(f"[!] Error fetching {path}: HTTP {status}")
        return None

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        print(f"[!] Router returned a non-JSON response for {path}.")
        return None

    if config.DEBUG:
        preview = json.dumps(parsed, indent=2, ensure_ascii=False)[:2000]
        print(f"[DEBUG] {path} → {preview}")
    return parsed


def get_fqdn_groups_full(session: KeeneticSession) -> dict[str, dict] | None:
    """Full FQDN groups: {name: {description, include: [{address}]}}."""
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
    """FQDN groups: {group_name: [subnet/domain, ...]}."""
    full = get_fqdn_groups_full(session)
    if full is None:
        return None
    return {name: [e["address"] for e in g["include"]] for name, g in full.items()}


def extract_subnets(addresses: list[str]) -> set[str]:
    """Canonicalizes a list of addresses/subnets (and drops 0.0.0.0)."""
    subnets: set[str] = set()
    for address in addresses:
        try:
            net = ipaddress.ip_network(address, strict=False)
        except ValueError:
            continue  # not an IP — a domain or junk, not part of the comparison
        if str(net) in ("0.0.0.0/32", "0.0.0.0/0"):
            continue  # service value
        subnets.add(str(net))
    return subnets


def get_router_subnets(session: KeeneticSession) -> tuple[set[str], int] | None:
    """Subnets from the router's DNS routes and the number of domain entries.

    Returns (subnets, number of domain entries). Domains don't participate
    in the subnet comparison, but the user should be told about them.
    """
    groups = get_fqdn_groups(session)
    if groups is None:
        return None

    if config.DEBUG:
        print(f"[DEBUG] DNS route groups: {len(groups)}")

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
# Filtering Google/YouTube subnets from WHOIS
# ---------------------------------------------------------------------------

def google_subnets_from_whois(whois_cache: dict[str, WhoisInfo]) -> dict[str, str]:
    """Google/YouTube subnets from WHOIS: {cidr: organization}."""
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
# Comparison and output
# ---------------------------------------------------------------------------

def _is_covered(cidr: str, router_subnets: set[str]) -> bool:
    """Whether the subnet is already covered by routes on the router.

    A subnet is considered covered if the router has the same subnet
    or a wider one that fully contains it.
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
    """Sorts subnets numerically (by network address and prefix)."""
    def _key(item: tuple[str, str]):
        net = ipaddress.ip_network(item[0], strict=False)
        return int(net.network_address), net.prefixlen

    return sorted(found.items(), key=_key)


def compare_google_subnets(session: KeeneticSession,
                           whois_cache: dict[str, WhoisInfo],
                           group_name: str | None = None) -> None:
    """Compares Google/YouTube subnets from WHOIS with the router's DNS routes.

    Prints the found subnets and separately the ones missing on the router.
    If a group name (group_name) is passed, automatically adds the missing
    subnets to that group.
    """
    found = google_subnets_from_whois(whois_cache)
    if not found:
        print("\n[!] No Google/YouTube subnets found among the hosts — comparison skipped.")
        return

    print(f"\n[*] Fetching router DNS static routes ({OBJECT_GROUP_FQDN_ENDPOINT})...")
    router_result = get_router_subnets(session)
    if router_result is None:
        return
    router_subnets, domain_count = router_result

    if domain_count:
        print(f"  [i] {domain_count} domain entries in route groups — they don't participate in the subnet comparison.")

    missing = {
        cidr: org for cidr, org in found.items()
        if not _is_covered(cidr, router_subnets)
    }
    _print_result(found, missing)

    if missing:
        if group_name:
            _add_missing_subnets(session, missing, group_name)
        else:
            print("  [i] Auto-add skipped (no group selected).")


# ---------------------------------------------------------------------------
# Group selection for adding and writing to the router
# ---------------------------------------------------------------------------

def select_fqdn_group(session: KeeneticSession,
                      last_group: str | None = None) -> str | None:
    """Interactive selection of the DNS route group for auto-adding subnets.

    The user picks a group by number, name or description.
    Enter — the last selected group (if any), otherwise the first in the list;
    '0' — don't add automatically (returns None).
    """
    full_groups = get_fqdn_groups_full(session)
    if full_groups is None:
        return None
    if not full_groups:
        print("  [!] No DNS route groups on the router — auto-add disabled.")
        return None

    # Groups with a description come first, the rest are sorted by name
    items = sorted(
        full_groups.items(),
        key=lambda kv: (not (kv[1].get("description") or ""), kv[0].lower()),
    )

    # Default: the last group, "don't add" or the first in the list
    default = 1
    if last_group:
        default = next((i for i, (n, _) in enumerate(items, 1) if n == last_group), 1)
    elif last_group == "":
        default = 0  # the user previously declined auto-add

    print(f"\n{'─' * 80}")
    print("  Select a DNS route group for auto-adding missing subnets:")
    for i, (name, group) in enumerate(items, 1):
        desc = group.get("description") or ""
        count = len(group.get("include") or [])
        marker = "  ◀ last" if name == last_group else ""
        print(f"    {i:<3} {name:<26} '{desc}' ({count} entries){marker}")
    print("    0    Don't add automatically")
    print(f"{'─' * 80}")

    while True:
        try:
            raw = input(f"  Group [{default}]: ").strip()
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
                print(f"  [!] Number from 1 to {len(items)} or 0")
                continue
            # Search by name or description (partial match)
            raw_lower = raw.lower()
            matches = [
                n for n, g in full_groups.items()
                if raw_lower in n.lower() or raw_lower in (g.get("description") or "").lower()
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print(f"  [!] Multiple matches: {', '.join(matches)}")
            else:
                print(f"  [!] Group '{raw}' not found")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)


def build_group_payload(group_name: str, description: str,
                        current_entries: list[dict],
                        new_addresses: list[str]) -> dict:
    """Payload for writing a group: existing entries + new ones, no duplicates."""
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
    """Looks for 'status': 'error' in the router response status tree."""
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str) and status.lower() == "error":
            return True
        return any(_status_has_errors(v) for v in value.values())
    if isinstance(value, list):
        return any(_status_has_errors(v) for v in value)
    return False


def write_fqdn_group(session: KeeneticSession, payload: dict) -> bool:
    """Writes an FQDN group to the router. True on success."""
    data, status = session.post_json(OBJECT_GROUP_FQDN_ENDPOINT, payload)
    if status != 200:
        return False
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return True  # response not parsed — rely on HTTP 200
    return not _status_has_errors(parsed)


def _add_missing_subnets(session: KeeneticSession, missing: dict[str, str],
                         group_name: str) -> None:
    """Automatically adds the missing subnets to the selected group."""
    full_groups = get_fqdn_groups_full(session)
    if full_groups is None:
        return
    if group_name not in full_groups:
        print(f"  [!] Group '{group_name}' not found on the router — add skipped.")
        return

    group = full_groups[group_name]
    payload = build_group_payload(
        group_name, group["description"], group["include"], list(missing.keys()),
    )
    print(f"  [i] Adding missing subnets ({len(missing)}) to group '{group['description']}' ({group_name})...")
    if not write_fqdn_group(session, payload):
        print("  [!] Failed to write the group to the router.")
        return

    print(f"  [✓] Subnets added to group {group_name} ('{group['description']}'):")
    for cidr in sorted(missing):
        print(f"      • {cidr}  ({missing[cidr] or '-'})")


def _print_result(found: dict[str, str], missing: dict[str, str]) -> None:
    """Prints the result of comparing subnets with the router's DNS routes."""
    present = len(found) - len(missing)

    print(f"\n{'═' * 100}")
    print("  🌐 Google/YouTube subnets: comparison with router DNS routes")
    print(f"  Found: {len(found)}  |  Already on router: {present}  |  Missing: {len(missing)}")
    print(f"{'═' * 100}")

    print(f"\n  {'#':<4} {'Subnet':<24} {'Organization':<32} {'Status'}")
    print(f"  {'─' * 96}")
    for i, (cidr, org) in enumerate(_sorted_subnets(found), 1):
        status = "✗ missing" if cidr in missing else "✓ on router"
        print(f"  {i:<4} {cidr:<24} {(org or '-'):<32} {status}")
    print(f"  {'─' * 96}")

    if missing:
        print(f"\n  ⚠️  Missing subnets ({len(missing)}) — not present in the router's DNS routes:")
        for cidr, org in _sorted_subnets(missing):
            print(f"    • {cidr}  ({org or '-'})")
    else:
        print("\n  ✅ All found Google/YouTube subnets are already on the router.")

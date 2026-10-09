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

There is also a standalone "DNS route audit" mode (menu item 3): it scans
all groups for duplicate and overlapping subnets — exact duplicates, subnets
fully covered by a wider one in the same group, cross-group coverage and
misaligned entries — and offers to fix the fixable ones (with confirmation).
The fix is applied via CLI commands through the /rci/ parse endpoint
("no object-group fqdn <group> include <address>" removes an entry), because
POSTing to /rci/object-group/fqdn can only ADD entries, not remove them.

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


# ---------------------------------------------------------------------------
# DNS route audit: duplicate and overlapping subnets
# ---------------------------------------------------------------------------

def _net_key(cidr: str) -> tuple[int, int]:
    """Sorting key for subnets: (network address, prefix length)."""
    net = ipaddress.ip_network(cidr, strict=False)
    return int(net.network_address), net.prefixlen


def find_subnet_conflicts(groups: dict[str, list[str]]) -> dict[str, list]:
    """Finds duplicate, covered and misaligned subnets in DNS route groups.

    Input: {group_name: [address, ...]} — addresses may be subnets or domains.
    All comparisons are done on canonical subnets (ipaddress, strict=False);
    the 0.0.0.0/0 and 0.0.0.0/32 service values are ignored.

    Returns a dict with the keys (empty lists when nothing is found):
      exact          — [(cidr, [(group, raw_address), ...]), ...]: the same
                       canonical subnet in 2+ entries (within a group or across groups)
      covered        — [(narrow_cidr, wide_cidr, group), ...]: a subnet fully
                       inside a wider subnet of the SAME group (redundant entry)
      cross_covered  — [(narrow_cidr, wide_cidr, narrow_group, wide_group), ...]:
                       coverage across different groups (routing conflict risk)
      misaligned     — [(group, raw_address, canonical_cidr), ...]: entries not
                       written in canonical form, e.g. 10.0.0.128/24
    """
    exact_occ: dict[str, list[tuple[str, str]]] = {}
    per_group: dict[str, set[str]] = {}
    misaligned: list[tuple[str, str, str]] = []

    for group, addresses in groups.items():
        nets: set[str] = set()
        for address in addresses:
            try:
                net = ipaddress.ip_network(address, strict=False)
            except ValueError:
                continue  # a domain or junk — not a subnet
            cidr = str(net)
            if cidr in ("0.0.0.0/32", "0.0.0.0/0"):
                continue
            nets.add(cidr)
            exact_occ.setdefault(cidr, []).append((group, address))
            try:
                ipaddress.ip_network(address, strict=True)
            except ValueError:
                misaligned.append((group, address, cidr))
        per_group[group] = nets

    exact = sorted(
        ((cidr, locs) for cidr, locs in exact_occ.items() if len(locs) >= 2),
        key=lambda item: _net_key(item[0]),
    )

    # A subnet fully inside a wider one of the same group — a redundant entry
    covered: list[tuple[str, str, str]] = []
    for group, nets in per_group.items():
        nets_list = sorted(nets, key=_net_key)
        for narrow in nets_list:
            narrow_net = ipaddress.ip_network(narrow)
            widest: tuple[int, str] | None = None
            for wide in nets_list:
                if wide == narrow:
                    continue
                wide_net = ipaddress.ip_network(wide)
                if narrow_net.subnet_of(wide_net) and (
                    widest is None or wide_net.prefixlen < widest[0]
                ):
                    widest = (wide_net.prefixlen, wide)
            if widest is not None:
                covered.append((narrow, widest[1], group))
    covered.sort(key=lambda item: (_net_key(item[0]), item[2]))

    # Coverage across different groups — both entries stay, but it's worth reporting
    cidr_groups = {
        cidr: sorted({g for g, _ in locs})
        for cidr, locs in exact_occ.items()
    }
    cross_covered: list[tuple[str, str, str, str]] = []
    for narrow, narrow_groups in cidr_groups.items():
        narrow_net = ipaddress.ip_network(narrow)
        for wide, wide_groups in cidr_groups.items():
            if wide == narrow:
                continue
            if not narrow_net.subnet_of(ipaddress.ip_network(wide)):
                continue
            for gn in narrow_groups:
                for gw in wide_groups:
                    if gn != gw:
                        cross_covered.append((narrow, wide, gn, gw))
    cross_covered.sort(key=lambda item: (_net_key(item[0]), _net_key(item[1])))

    misaligned.sort(key=lambda item: (_net_key(item[2]), item[0]))

    return {
        "exact": exact,
        "covered": covered,
        "cross_covered": cross_covered,
        "misaligned": misaligned,
    }


def print_subnet_audit(groups: dict[str, list[str]], conflicts: dict[str, list],
                       subnet_count: int, domain_count: int) -> None:
    """Prints the DNS route audit report: duplicates and overlapping subnets."""
    exact = conflicts["exact"]
    covered = conflicts["covered"]
    cross_covered = conflicts["cross_covered"]
    misaligned = conflicts["misaligned"]

    print(f"\n{'═' * 100}")
    print("  🔍 DNS route audit: duplicate and overlapping subnets")
    print(f"  Groups: {len(groups)}  |  Subnets: {subnet_count}  |  Domains: {domain_count}")
    print(f"{'═' * 100}")

    if not exact and not covered and not cross_covered and not misaligned:
        print("\n  ✅ No duplicate or overlapping subnets found.")
        return

    if exact:
        print(f"\n  ⚠️  Exact duplicates ({len(exact)}) — the same subnet in several entries:")
        for cidr, locs in exact:
            loc_str = ", ".join(f"'{g}' ({raw})" for g, raw in locs)
            print(f"    • {cidr:<24} {loc_str}")

    if covered:
        print(f"\n  ⚠️  Covered subnets ({len(covered)}) — fully inside a wider subnet of the same group:")
        for narrow, wide, group in covered:
            print(f"    • {narrow:<24} ⊂ {wide:<24}  group '{group}'")

    if cross_covered:
        print(f"\n  ⚠️  Cross-group coverage ({len(cross_covered)}) — one group's subnet covers another group's:")
        for narrow, wide, gn, gw in cross_covered:
            print(f"    • {narrow:<24} in '{gn}'  ⊂  {wide:<24} in '{gw}'")

    if misaligned:
        print(f"\n  [i] Misaligned entries ({len(misaligned)}) — not in canonical form:")
        for group, raw, cidr in misaligned:
            print(f"    • {raw:<24} → {cidr:<24}  group '{group}'")


def _canonicalize_entries(entries: list[dict]) -> list[dict]:
    """Rewrites subnets in non-canonical form (host bits set) canonically.

    The router already treats such entries as their canonical network, so this
    only changes the stored form, not the actual behavior. Domains and already
    canonical subnets are left untouched.
    """
    result: list[dict] = []
    for entry in entries:
        address = entry.get("address")
        if isinstance(address, str):
            try:
                ipaddress.ip_network(address, strict=True)
            except ValueError:
                try:
                    net = ipaddress.ip_network(address, strict=False)
                    if str(net) not in ("0.0.0.0/32", "0.0.0.0/0"):
                        entry = {"address": str(net)}
                except ValueError:
                    pass
        result.append(entry)
    return result


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """Keeps the first occurrence of each raw address and canonical subnet."""
    seen_raw: set[str] = set()
    seen_cidr: set[str] = set()
    result: list[dict] = []
    for entry in entries:
        address = entry.get("address")
        if not isinstance(address, str) or address in seen_raw:
            continue
        try:
            cidr = str(ipaddress.ip_network(address, strict=False))
        except ValueError:
            pass  # a domain — dedupe by the raw address only
        else:
            if cidr in seen_cidr:
                continue
            seen_cidr.add(cidr)
        seen_raw.add(address)
        result.append(entry)
    return result


def _remove_covered_entries(entries: list[dict]) -> list[dict]:
    """Removes subnets fully covered by a wider subnet of the same group."""
    nets: dict = {}
    for i, entry in enumerate(entries):
        address = entry.get("address")
        if not isinstance(address, str):
            continue
        try:
            net = ipaddress.ip_network(address, strict=False)
        except ValueError:
            continue
        if str(net) in ("0.0.0.0/32", "0.0.0.0/0"):
            continue
        nets[i] = net

    drop: set[int] = set()
    for i, net in nets.items():
        for j, other in nets.items():
            if i != j and net != other and net.subnet_of(other):
                drop.add(i)
                break
    return [e for i, e in enumerate(entries) if i not in drop]


def _ask_fix_variant() -> int:
    """Interactive fix variant: 0 — leave, 1 — dedupe, 2 — +remove covered, 3 — +canonicalize."""
    print(f"\n{'─' * 80}")
    print("  How to fix?")
    print("    1. Remove exact duplicate subnets (within each group)")
    print("    2. Variant 1 + remove subnets fully covered by a wider one in the same group")
    print("    3. Variant 2 + rewrite misaligned entries in canonical form")
    print("    0. Leave as is (report only)")
    print(f"{'─' * 80}")
    while True:
        try:
            raw = input("  Variant [0]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)
        if raw == "":
            return 0
        if raw in ("0", "1", "2", "3"):
            return int(raw)
        print("  [!] Enter 0, 1, 2 or 3")


def run_parse_commands(session: KeeneticSession, commands: list[str]) -> bool:
    """Executes CLI commands via the /rci/ parse endpoint. True on success."""
    if not commands:
        return True
    data, status = session.post_parse(commands)
    if status != 200:
        return False
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return True  # response not parsed — rely on HTTP 200
    return not _status_has_errors(parsed)


def _apply_audit_fix(session: KeeneticSession, full_groups: dict[str, dict],
                     variant: int) -> None:
    """Applies the chosen fix variant to the router (with confirmation).

    The changes are sent as CLI commands via /rci/ (the parse endpoint):
    "no object-group fqdn <group> include <address>" removes an entry and
    "object-group fqdn <group> include <address>" adds one; the config is
    saved at the end. (POSTing to /rci/object-group/fqdn can only ADD entries
    to a group — it cannot remove them.)
    """
    changed: dict[str, tuple[list[dict], list[dict]]] = {}  # group → (before, after)
    for name, group in full_groups.items():
        entries = [e for e in group.get("include") or [] if isinstance(e, dict)]
        new_entries = _canonicalize_entries(entries) if variant >= 3 else entries
        new_entries = _dedupe_entries(new_entries)
        if variant >= 2:
            new_entries = _remove_covered_entries(new_entries)
        if [e.get("address") for e in new_entries] != [e.get("address") for e in entries]:
            changed[name] = (entries, new_entries)

    if not changed:
        print("  [i] Nothing to change in the groups.")
        return

    commands: list[str] = []
    print("\n  The following groups will be rewritten on the router:")
    for name, (before, after) in changed.items():
        print(f"    • {name}: {len(before)} → {len(after)} entries")
        before_addrs = [e.get("address") for e in before]
        after_addrs = [e.get("address") for e in after]
        for address in before_addrs:
            if address not in after_addrs:
                commands.append(f"no object-group fqdn {name} include {address}")
        for address in after_addrs:
            if address not in before_addrs:
                commands.append(f"object-group fqdn {name} include {address}")

    try:
        confirm = input("\n  Apply changes to the router? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)
    if confirm not in ("y", "yes"):
        print("  [i] Cancelled — the router was not changed.")
        return

    commands.append("system configuration save")
    print(f"  [i] Executing {len(commands)} CLI commands via /rci/ ...")
    if not run_parse_commands(session, commands):
        print("  [!] One or more commands failed — check the router's web UI.")
        return
    print("  [✓] Changes applied and saved:")
    for name, (before, after) in changed.items():
        print(f"      • {name}: {len(before)} → {len(after)} entries")


def run_subnet_audit(session: KeeneticSession) -> None:
    """Fetches the router's DNS route groups, finds subnet conflicts and offers fixes.

    Exact duplicates, same-group coverage and misaligned entries can be fixed
    interactively (variants 1–3, with confirmation; the config is saved).
    Cross-group duplicates and cross-group coverage are only reported — they
    may be intentional and are never changed automatically.
    """
    print(f"\n[*] Fetching router DNS static routes ({OBJECT_GROUP_FQDN_ENDPOINT})...")
    full_groups = get_fqdn_groups_full(session)
    if full_groups is None:
        return
    if not full_groups:
        print("  [!] No DNS route groups on the router.")
        return

    groups = {name: [e["address"] for e in g["include"]] for name, g in full_groups.items()}
    all_addresses = [a for addresses in groups.values() for a in addresses]
    subnet_count = len(extract_subnets(all_addresses))
    domain_count = 0
    for address in all_addresses:
        try:
            ipaddress.ip_network(address, strict=False)
        except ValueError:
            domain_count += 1

    conflicts = find_subnet_conflicts(groups)
    print_subnet_audit(groups, conflicts, subnet_count, domain_count)

    if not conflicts["exact"] and not conflicts["covered"] and not conflicts["misaligned"]:
        return  # cross-group coverage is informational only

    variant = _ask_fix_variant()
    if variant == 0:
        print("  [i] Nothing changed.")
        return
    _apply_audit_fix(session, full_groups, variant)

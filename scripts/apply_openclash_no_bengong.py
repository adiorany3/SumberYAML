#!/usr/bin/env python3
"""Apply responsive/no-bengong optimizations to generated OpenClash YAML files.

Design goals:
- Keep trusted manual accounts from input/links.txt or input.txt included.
- Add best-link and fallback-link groups from manual accounts.
- Add BEST-STABLE and ANTI-BENGONG groups.
- Make PROXY prefer anti-bengong/stable/manual fallback groups.
- Add stable DNS and LAN DIRECT rules.
- Avoid destructive filtering of manual accounts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"PyYAML is required: {exc}", file=sys.stderr)
    sys.exit(2)

DEFAULT_FILES = [
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/general.yaml",
    "output/openclash-ready.yaml",
]

HEALTH_URL = "https://www.gstatic.com/generate_204"
SAFE_SPECIAL_TARGETS = {
    "DIRECT",
    "REJECT",
    "GLOBAL",
    "PASS",
}

LAN_DIRECT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
]

QUIC_REJECT_RULE = "AND,((NETWORK,UDP),(DST-PORT,443)),REJECT"

MANUAL_PREFIX_PATTERNS = [
    re.compile(r"^LINK\b", re.IGNORECASE),
    re.compile(r"^MANUAL\b", re.IGNORECASE),
    re.compile(r"^INPUT\b", re.IGNORECASE),
]


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root YAML must be a mapping/object")
    return data


def save_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def input_link_count(root: Path) -> int:
    lines: List[str] = []
    for rel in ("input/links.txt", "input.txt"):
        text = read_text(root / rel)
        for raw in text.splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                lines.append(line)
    return len(lines)


def ensure_list_mapping(data: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        value = []
        data[key] = value
    # Keep only mappings for proxy/proxy-groups arrays.
    cleaned: List[Dict[str, Any]] = []
    changed = False
    for item in value:
        if isinstance(item, dict):
            cleaned.append(item)
        else:
            changed = True
    if changed:
        data[key] = cleaned
    return cleaned


def proxy_names(data: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for item in ensure_list_mapping(data, "proxies"):
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return unique(names)


def group_names(data: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for item in ensure_list_mapping(data, "proxy-groups"):
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return unique(names)


def unique(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def is_manual_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    if any(pattern.search(text) for pattern in MANUAL_PREFIX_PATTERNS):
        return True
    # Compatibility with older generated names.
    return text.lower().startswith("link ") or " trusted" in text.lower()


def manual_proxy_names(data: Dict[str, Any]) -> List[str]:
    return [name for name in proxy_names(data) if is_manual_name(name)]


def read_csv_names(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return []
    names: List[str] = []
    for row in rows:
        name = str(row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
        if name:
            names.append(name)
    return unique(names)


def stable_candidates_from_outputs(root: Path, valid_proxy_names: Sequence[str], manual_names: Sequence[str], max_stable: int) -> List[str]:
    valid = set(valid_proxy_names)
    manual = set(manual_names)
    candidates: List[str] = []
    csv_paths = [
        root / "output/BestPing/top5_indonesia_ping.csv",
        root / "output/BestPing/top5_best_ping.csv",
        root / "output/Alive/alive.csv",
        root / "output/Alive/check_result.csv",
    ]
    for path in csv_paths:
        for name in read_csv_names(path):
            if name in valid and name not in candidates:
                candidates.append(name)

    # Prefer non-manual tested/stable nodes, then manual as backup, then any remaining proxy.
    non_manual = [name for name in candidates if name not in manual]
    manual_in_candidates = [name for name in candidates if name in manual]
    remaining_non_manual = [name for name in valid_proxy_names if name not in manual and name not in non_manual]
    remaining_manual = [name for name in manual_names if name in valid and name not in manual_in_candidates]

    final = unique(non_manual + manual_in_candidates + remaining_non_manual + remaining_manual)
    return final[: max(1, int(max_stable or 10))]


def find_group(data: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for group in ensure_list_mapping(data, "proxy-groups"):
        if str(group.get("name") or "").strip() == name:
            return group
    return None


def upsert_group(data: Dict[str, Any], name: str, group_type: str, proxies: Sequence[str], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    groups = ensure_list_mapping(data, "proxy-groups")
    group = find_group(data, name)
    if group is None:
        group = {"name": name}
        groups.append(group)
    group["name"] = name
    group["type"] = group_type
    group["proxies"] = unique(proxies)
    if extra:
        group.update(extra)
    return group


def set_group_health_defaults(group: Dict[str, Any]) -> None:
    gtype = str(group.get("type") or "").lower().strip()
    if gtype in {"url-test", "fallback", "load-balance"}:
        group.setdefault("url", HEALTH_URL)
        group.setdefault("interval", 300)
        group["lazy"] = True
    if gtype in {"url-test", "load-balance"}:
        group.setdefault("tolerance", 80)
    if gtype == "load-balance":
        # sticky-sessions is safer than random/round-robin for mobile apps, but do not override existing strategy.
        group.setdefault("strategy", "consistent-hashing")


def clean_group_references(data: Dict[str, Any]) -> int:
    changed = 0
    names_proxy = set(proxy_names(data))
    names_group = set(group_names(data))
    allowed = names_proxy | names_group | SAFE_SPECIAL_TARGETS
    for group in ensure_list_mapping(data, "proxy-groups"):
        proxies = group.get("proxies")
        if not isinstance(proxies, list):
            group["proxies"] = []
            changed += 1
            continue
        cleaned = []
        for item in proxies:
            text = str(item).strip()
            if not text:
                continue
            if text in allowed or is_manual_name(text):
                # Manual entries are kept if already present in proxies or group lists. If not, a later validator may still catch it.
                if text in allowed:
                    cleaned.append(text)
            else:
                changed += 1
        cleaned = unique(cleaned)
        if cleaned != proxies:
            group["proxies"] = cleaned
            changed += 1
    return changed


def ensure_dns(data: Dict[str, Any], fake_ip: bool) -> None:
    dns = data.get("dns")
    if not isinstance(dns, dict):
        dns = {}
        data["dns"] = dns
    dns["enable"] = True
    dns["ipv6"] = False
    dns["default-nameserver"] = ["1.1.1.1", "8.8.8.8"]
    dns["nameserver"] = ["1.1.1.1"]
    dns["fallback"] = ["8.8.8.8"]
    if fake_ip:
        dns["enhanced-mode"] = "fake-ip"
        dns.setdefault("fake-ip-range", "198.18.0.1/16")
        fake_filter = dns.get("fake-ip-filter")
        if not isinstance(fake_filter, list):
            fake_filter = []
        required = [
            "*.lan",
            "*.local",
            "localhost.ptlogin2.qq.com",
            "+.msftconnecttest.com",
            "+.msftncsi.com",
            "time.*.com",
            "time.*.gov",
            "time.*.edu.cn",
            "time.*.apple.com",
            "time-ios.apple.com",
            "+.pool.ntp.org",
            "+.ntp.org",
        ]
        dns["fake-ip-filter"] = unique([str(x) for x in fake_filter] + required)


def ensure_profile_and_general_options(data: Dict[str, Any]) -> None:
    data.setdefault("mode", "rule")
    data["log-level"] = "warning"
    # Mihomo/OpenClash Meta options. Older cores usually ignore unknown keys, but keep them conservative.
    data["unified-delay"] = True
    data["tcp-concurrent"] = True
    profile = data.get("profile")
    if not isinstance(profile, dict):
        profile = {}
        data["profile"] = profile
    profile["store-selected"] = True
    profile["store-fake-ip"] = True


def ensure_rules(data: Dict[str, Any], block_quic: bool) -> None:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
    rules_text = [str(rule).strip() for rule in rules if str(rule).strip()]

    # Remove duplicate final MATCH so we can re-add exactly once.
    non_match = [rule for rule in rules_text if not rule.upper().startswith("MATCH,")]

    ordered = []
    if block_quic:
        ordered.append(QUIC_REJECT_RULE)
    ordered.extend(LAN_DIRECT_RULES)
    ordered.extend(non_match)
    ordered.append("MATCH,PROXY")
    data["rules"] = unique(ordered)


def build_proxy_group_order(data: Dict[str, Any]) -> List[str]:
    gnames = set(group_names(data))
    desired = [
        "ANTI-BENGONG",
        "BEST-STABLE",
        "fallback-link",
        "best-link",
        "URL-TEST TOP 5 INDONESIA",
        "URL-TEST",
        "FALLBACK",
        "DIRECT",
    ]
    out = []
    for item in desired:
        if item == "DIRECT" or item in gnames:
            out.append(item)
    existing = []
    proxy_group = find_group(data, "PROXY")
    if proxy_group and isinstance(proxy_group.get("proxies"), list):
        existing = [str(x).strip() for x in proxy_group.get("proxies", []) if str(x).strip()]
    return unique(out + existing + ["DIRECT"])


def apply_to_file(path: Path, root: Path, max_stable: int, fake_ip: bool, block_quic: bool) -> Dict[str, Any]:
    data = load_yaml(path)
    all_proxies = proxy_names(data)
    manual = manual_proxy_names(data)
    stable = stable_candidates_from_outputs(root, all_proxies, manual, max_stable)

    stats = {
        "file": str(path),
        "proxy_count": len(all_proxies),
        "manual_proxy_count": len(manual),
        "stable_count": len(stable),
        "created_or_updated_groups": [],
        "status": "ok",
    }

    ensure_profile_and_general_options(data)
    ensure_dns(data, fake_ip=fake_ip)

    # Existing health groups get safer defaults.
    for group in ensure_list_mapping(data, "proxy-groups"):
        set_group_health_defaults(group)

    if stable:
        upsert_group(
            data,
            "BEST-STABLE",
            "url-test",
            stable,
            {
                "url": HEALTH_URL,
                "interval": 300,
                "tolerance": 80,
                "lazy": True,
            },
        )
        stats["created_or_updated_groups"].append("BEST-STABLE")

    if manual:
        upsert_group(
            data,
            "best-link",
            "url-test",
            manual,
            {
                "url": HEALTH_URL,
                "interval": 300,
                "tolerance": 80,
                "lazy": True,
            },
        )
        upsert_group(
            data,
            "fallback-link",
            "fallback",
            manual,
            {
                "url": HEALTH_URL,
                "interval": 300,
                "lazy": True,
            },
        )
        stats["created_or_updated_groups"].extend(["best-link", "fallback-link"])

    # ANTI-BENGONG is a fallback stack across healthy groups, not all raw nodes.
    available_groups = set(group_names(data))
    anti_targets = [
        name for name in [
            "BEST-STABLE",
            "fallback-link",
            "best-link",
            "URL-TEST TOP 5 INDONESIA",
            "URL-TEST",
            "FALLBACK",
        ]
        if name in available_groups
    ]
    if anti_targets:
        upsert_group(
            data,
            "ANTI-BENGONG",
            "fallback",
            anti_targets + ["DIRECT"],
            {
                "url": HEALTH_URL,
                "interval": 300,
                "lazy": True,
            },
        )
        stats["created_or_updated_groups"].append("ANTI-BENGONG")

    # PROXY should prefer anti-bengong. This is a select group so user can override.
    upsert_group(
        data,
        "PROXY",
        "select",
        build_proxy_group_order(data),
        {},
    )
    stats["created_or_updated_groups"].append("PROXY")

    # Ensure every health group has safe default fields after upserts.
    for group in ensure_list_mapping(data, "proxy-groups"):
        set_group_health_defaults(group)

    removed = clean_group_references(data)
    stats["removed_invalid_references"] = removed

    # If any group became empty, fill it with a safe target.
    safe_target = "DIRECT"
    if stable:
        safe_target = stable[0]
    elif manual:
        safe_target = manual[0]
    elif all_proxies:
        safe_target = all_proxies[0]

    for group in ensure_list_mapping(data, "proxy-groups"):
        proxies = group.get("proxies")
        if not isinstance(proxies, list) or not proxies:
            group["proxies"] = [safe_target]
            stats.setdefault("filled_empty_groups", []).append(str(group.get("name", "-")))

    ensure_rules(data, block_quic=block_quic)
    save_yaml(path, data)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply anti-bengong responsive stability settings to OpenClash YAML outputs.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--max-stable", type=int, default=10, help="Maximum nodes for BEST-STABLE")
    parser.add_argument("--fake-ip", action="store_true", default=True, help="Use fake-ip DNS mode")
    parser.add_argument("--no-fake-ip", action="store_false", dest="fake_ip", help="Do not force fake-ip DNS mode")
    parser.add_argument("--block-quic", action="store_true", help="Add Mihomo QUIC reject rule for UDP/443. Off by default for compatibility.")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES, help="YAML files to optimize")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = {
        "script": "apply_openclash_no_bengong.py",
        "manual_input_link_count": input_link_count(root),
        "settings": {
            "max_stable": args.max_stable,
            "fake_ip": args.fake_ip,
            "block_quic": args.block_quic,
            "health_url": HEALTH_URL,
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        },
        "files": [],
    }

    for rel in args.files:
        path = root / rel
        if not path.exists():
            report["files"].append({"file": rel, "status": "missing"})
            continue
        try:
            report["files"].append(apply_to_file(path, root, max(1, args.max_stable), args.fake_ip, args.block_quic))
        except Exception as exc:
            report["files"].append({"file": rel, "status": "error", "error": str(exc)})
            # Continue so other YAML files still get fixed.

    ok_count = sum(1 for item in report["files"] if item.get("status") == "ok")
    err_count = sum(1 for item in report["files"] if item.get("status") == "error")
    report["ok_count"] = ok_count
    report["error_count"] = err_count

    out_path = root / "output/Validation/summary_openclash_no_bengong.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if err_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

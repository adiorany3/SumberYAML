#!/usr/bin/env python3
"""
Apply Indonesia-best routing to OpenClash YAML outputs.

Purpose:
- Build/refresh proxy-group "INDONESIA-BEST" from the best Indonesian proxies.
- Route Indonesian domains/IPs to INDONESIA-BEST.
- Keep trusted manual input accounts untouched. This script only groups/rules existing
  proxy names; it does not test, filter, quarantine, or delete accounts.

Inputs used for candidate ranking:
1. output/BestPing/top5_indonesia_ping.csv
2. output/BestPing/top5_best_ping.csv where country is ID/Indonesia
3. output/Alive/alive.csv where country is ID/Indonesia
4. Proxy names in YAML that look Indonesian

Outputs:
- updates output/*.yaml files
- writes output/Validation/summary_indonesia_best_proxy.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("Missing PyYAML. Install with: pip install pyyaml") from exc


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

INDONESIA_GROUP = "INDONESIA-BEST"

INDONESIA_RULES = [
    # Indonesian ccTLD and common Indonesian services that do not always use .id.
    "DOMAIN-SUFFIX,id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,go.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,ac.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,co.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,or.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,my.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,web.id,INDONESIA-BEST",
    "DOMAIN-SUFFIX,detik.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,kompas.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,tribunnews.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,tokopedia.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,bukalapak.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,gojek.com,INDONESIA-BEST",
    "DOMAIN-SUFFIX,grab.com,INDONESIA-BEST",
    # GeoIP catches Indonesian IP destinations. no-resolve keeps the rule lightweight.
    "GEOIP,ID,INDONESIA-BEST,no-resolve",
]

LOCAL_DIRECT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
    "IP-CIDR,255.255.255.255/32,DIRECT,no-resolve",
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def load_yaml(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if not text.strip():
        return {}
    data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=4096,
        ),
        encoding="utf-8",
    )


def normalize_name(value: Any) -> str:
    return str(value or "").strip()


def proxy_name_set(data: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for proxy in data.get("proxies") or []:
        if isinstance(proxy, dict):
            name = normalize_name(proxy.get("name"))
            if name:
                names.add(name)
    return names


def group_name_set(data: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for group in data.get("proxy-groups") or []:
        if isinstance(group, dict):
            name = normalize_name(group.get("name"))
            if name:
                names.add(name)
    return names


def parse_delay_ms(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    text = read_text(path)
    if not text.strip():
        return []
    try:
        return list(csv.DictReader(io.StringIO(text)))
    except Exception:
        return []


def is_indonesia_country(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"id", "indonesia", "🇮🇩"} or "indonesia" in text


def looks_indonesian_name(name: str) -> bool:
    lowered = name.lower()
    tokens = [
        "🇮🇩",
        "indonesia",
        " indo ",
        " indo-",
        "-indo",
        "_indo",
        " id ",
        " id-",
        "-id",
        "_id",
        "jakarta",
        "jkt",
        "idn",
        "rumahweb",
        "biznet",
        "telkom",
        "telkomsel",
        "xl",
        "indosat",
        "tri",
        "three",
        "smartfren",
        "cbn",
        "myrepublic",
        "apjii",
    ]
    padded = f" {lowered} "
    return any(token in padded or token in lowered for token in tokens)


def add_unique_ordered(items: list[str], value: str) -> None:
    value = normalize_name(value)
    if value and value not in items:
        items.append(value)


def ranked_indonesia_candidates(root: Path, available_names: set[str], max_count: int) -> list[str]:
    ordered: list[str] = []
    rank_sources = [
        root / "output/BestPing/top5_indonesia_ping.csv",
        root / "output/BestPing/top5_best_ping.csv",
        root / "output/Alive/alive.csv",
        root / "output/Alive/check_result.csv",
    ]

    for path in rank_sources:
        rows = read_csv_rows(path)
        ranked_rows = []
        for row in rows:
            name = normalize_name(row.get("name"))
            if not name or name not in available_names:
                continue

            country = row.get("country") or row.get("country_code") or row.get("cc")
            if path.name == "top5_indonesia_ping.csv" or is_indonesia_country(country) or looks_indonesian_name(name):
                delay = parse_delay_ms(row.get("delay_ms") or row.get("delay") or row.get("latency"))
                ranked_rows.append((delay if delay is not None else 999999, name))

        for _delay, name in sorted(ranked_rows, key=lambda item: item[0]):
            add_unique_ordered(ordered, name)

    # Fallback heuristic from current YAML names.
    for name in sorted(available_names):
        if looks_indonesian_name(name):
            add_unique_ordered(ordered, name)

    return ordered[:max_count]


def remove_named_group(groups: list[Any], name: str) -> list[Any]:
    return [
        group for group in groups
        if not (isinstance(group, dict) and normalize_name(group.get("name")) == name)
    ]


def make_urltest_group(name: str, proxies: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": proxies,
        "url": "https://www.gstatic.com/generate_204",
        "interval": 300,
        "tolerance": 80,
        "lazy": True,
    }


def ensure_proxy_group_choice(data: dict[str, Any], parent_name: str, child_name: str, first: bool = True) -> bool:
    changed = False
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        data["proxy-groups"] = groups = []

    for group in groups:
        if not isinstance(group, dict) or normalize_name(group.get("name")) != parent_name:
            continue
        proxies = group.setdefault("proxies", [])
        if not isinstance(proxies, list):
            group["proxies"] = proxies = []
            changed = True

        proxies = [normalize_name(item) for item in proxies if normalize_name(item) and normalize_name(item) != child_name]
        if first:
            proxies.insert(0, child_name)
        else:
            proxies.append(child_name)
        group["proxies"] = proxies
        changed = True

        # If select group has default and client supports it, keep existing default untouched.
        # Compatibility scripts can remove default later if required.
        break

    return changed


def normalize_rule(rule: Any) -> str:
    return str(rule or "").strip()


def install_rules(data: dict[str, Any]) -> bool:
    changed = False
    existing = data.get("rules") or []
    if not isinstance(existing, list):
        existing = []
        changed = True

    # Remove previous Indonesia rules and local direct duplicates we manage.
    managed = set(INDONESIA_RULES + LOCAL_DIRECT_RULES)
    cleaned = [rule for rule in existing if normalize_rule(rule) and normalize_rule(rule) not in managed]

    # Keep local direct rules very high in the list, but do not duplicate.
    final_rules: list[str] = []
    for rule in LOCAL_DIRECT_RULES:
        add_unique_ordered(final_rules, rule)

    # Preserve non-managed rules before MATCH, but insert Indonesia rules just before MATCH.
    match_rules = []
    non_match_rules = []
    for rule in cleaned:
        text = normalize_rule(rule)
        if not text:
            continue
        if text.upper().startswith("MATCH,"):
            match_rules.append(text)
        else:
            non_match_rules.append(text)

    for rule in non_match_rules:
        add_unique_ordered(final_rules, rule)

    for rule in INDONESIA_RULES:
        add_unique_ordered(final_rules, rule)

    if match_rules:
        for rule in match_rules:
            add_unique_ordered(final_rules, rule)
    else:
        add_unique_ordered(final_rules, "MATCH,PROXY")

    if final_rules != [normalize_rule(x) for x in existing if normalize_rule(x)]:
        data["rules"] = final_rules
        changed = True

    return changed


def ensure_dns(data: dict[str, Any]) -> bool:
    changed = False
    dns = data.setdefault("dns", {})
    if not isinstance(dns, dict):
        data["dns"] = dns = {}
        changed = True

    desired = {
        "enable": True,
        "ipv6": False,
        "enhanced-mode": "fake-ip",
        "nameserver": ["1.1.1.1"],
        "fallback": ["8.8.8.8"],
    }
    for key, value in desired.items():
        if dns.get(key) != value:
            dns[key] = value
            changed = True

    return changed


def apply_to_file(path: Path, root: Path, max_indonesia: int) -> dict[str, Any]:
    data = load_yaml(path)
    if not data:
        return {"file": str(path), "exists": False, "changed": False, "reason": "empty_or_missing"}

    available = proxy_name_set(data)
    groups_before = group_name_set(data)
    candidates = ranked_indonesia_candidates(root, available, max_indonesia)

    changed = False

    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        data["proxy-groups"] = groups = []
        changed = True

    if candidates:
        groups = remove_named_group(groups, INDONESIA_GROUP)
        groups.insert(0, make_urltest_group(INDONESIA_GROUP, candidates))
        data["proxy-groups"] = groups
        changed = True

        # Make it visible/selectable in main groups.
        for parent in ["PROXY", "ANTI-BENGONG", "GLOBAL", "MANUAL", "SELECT"]:
            if parent in groups_before or parent in group_name_set(data):
                changed = ensure_proxy_group_choice(data, parent, INDONESIA_GROUP, first=True) or changed

        changed = install_rules(data) or changed
        changed = ensure_dns(data) or changed

    if changed:
        dump_yaml(path, data)

    return {
        "file": str(path),
        "exists": True,
        "changed": changed,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "group": INDONESIA_GROUP if candidates else None,
        "reason": None if candidates else "no_indonesia_candidates_found",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--max-indonesia", type=int, default=10, help="Max Indonesian proxies in INDONESIA-BEST")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES, help="YAML files to update")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = []
    for file_name in args.files:
        results.append(apply_to_file(root / file_name, root, max(1, args.max_indonesia)))

    report = {
        "group": INDONESIA_GROUP,
        "rules_added": INDONESIA_RULES,
        "local_direct_rules": LOCAL_DIRECT_RULES,
        "max_indonesia": max(1, args.max_indonesia),
        "files": results,
        "changed_files": [item["file"] for item in results if item.get("changed")],
        "note": (
            "Trusted manual accounts from input.txt/input/links.txt are not filtered or deleted. "
            "This script only adds Indonesia routing and groups around existing proxies."
        ),
    }

    report_path = root / "output/Validation/summary_indonesia_best_proxy.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

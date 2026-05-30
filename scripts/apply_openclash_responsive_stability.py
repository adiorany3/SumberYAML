#!/usr/bin/env python3
"""
Apply responsive/stable OpenClash YAML structure for SumberYAML.

Goals:
- Keep trusted/manual accounts from input/links.txt or input.txt untouched.
- Build best-link and fallback-link groups from trusted/manual accounts.
- Build BEST-STABLE from Health/BestPing/Alive data when available.
- Put stable groups near the top of PROXY-like selectors.
- Add conservative DNS fallback and LAN DIRECT rules.

This script does not perform alive/dead validation and does not remove trusted
manual accounts. It only organizes generated YAML for better responsiveness.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import yaml

DEFAULT_OUTPUT_FILES = [
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
]

CHECK_URL = "https://www.gstatic.com/generate_204"
MANUAL_NAME_PREFIXES = (
    "LINK ",
    "LINK-",
    "LINK_",
    "INPUT ",
    "INPUT-",
    "INPUT_",
    "MANUAL ",
    "MANUAL-",
    "MANUAL_",
    "TRUSTED ",
    "TRUSTED-",
    "TRUSTED_",
)

MAIN_GROUP_CANDIDATES = [
    "PROXY",
    "GLOBAL",
    "MANUAL",
    "SELECT",
    "🚀 PROXY",
    "Proxy",
    "proxy",
]

SECONDARY_SELECTOR_CANDIDATES = [
    "FALLBACK",
    "FALLBACK CEPAT",
    "URL-TEST",
    "URL TEST",
    "AUTO",
    "AUTO-BEST-PING",
]

LAN_DIRECT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
]


def load_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )


def unique_keep_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def get_proxy_names(data: Dict[str, Any]) -> List[str]:
    proxies = data.get("proxies") or []
    names: List[str] = []
    if isinstance(proxies, list):
        for proxy in proxies:
            if isinstance(proxy, dict) and proxy.get("name"):
                names.append(str(proxy["name"]).strip())
    return unique_keep_order(names)


def get_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        groups = []
        data["proxy-groups"] = groups
    return groups


def get_group_names(data: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for group in get_groups(data):
        if isinstance(group, dict) and group.get("name"):
            names.append(str(group["name"]).strip())
    return unique_keep_order(names)


def is_manual_name(name: str) -> bool:
    upper = str(name or "").strip().upper()
    if upper.startswith(MANUAL_NAME_PREFIXES):
        return True
    # Common names created by link importers usually include a clear manual marker.
    return bool(re.search(r"(^|[\s_\-\[])(LINK|INPUT|MANUAL|TRUSTED)([\s_\-\]]|$)", upper))


def read_csv_names(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            out: List[str] = []
            for row in reader:
                name = (row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
                if name:
                    out.append(name)
            return unique_keep_order(out)
    except Exception:
        return []


def stable_candidates_from_outputs(root: Path, existing_names: Set[str], manual_names: Set[str], max_count: int) -> List[str]:
    candidate_paths = [
        root / "output/Health/healthy.csv",
        root / "output/BestPing/top5_indonesia_ping.csv",
        root / "output/BestPing/top5_best_ping.csv",
        root / "output/Alive/alive.csv",
        root / "output/Alive/check_result.csv",
    ]
    names: List[str] = []
    for path in candidate_paths:
        for name in read_csv_names(path):
            if name in existing_names and name not in manual_names:
                names.append(name)
    return unique_keep_order(names)[:max_count]


def build_group(name: str, group_type: str, proxies: Sequence[str], *, tolerance: Optional[int] = None) -> Dict[str, Any]:
    group: Dict[str, Any] = {
        "name": name,
        "type": group_type,
        "proxies": unique_keep_order(proxies),
        "url": CHECK_URL,
        "interval": 300,
        "lazy": True,
    }
    if tolerance is not None:
        group["tolerance"] = int(tolerance)
    return group


def upsert_group(data: Dict[str, Any], new_group: Dict[str, Any]) -> Tuple[str, int]:
    groups = get_groups(data)
    target_name = str(new_group.get("name") or "")
    for index, group in enumerate(groups):
        if isinstance(group, dict) and str(group.get("name") or "") == target_name:
            groups[index] = new_group
            return "updated", len(new_group.get("proxies") or [])
    groups.append(new_group)
    return "created", len(new_group.get("proxies") or [])


def find_or_create_main_group(data: Dict[str, Any], proxy_names: List[str]) -> Dict[str, Any]:
    groups = get_groups(data)
    for candidate in MAIN_GROUP_CANDIDATES:
        for group in groups:
            if isinstance(group, dict) and str(group.get("name") or "") == candidate:
                return group

    # Fallback: first selector-like group.
    for group in groups:
        if isinstance(group, dict) and str(group.get("type") or "").lower() in {"select", "selector"}:
            return group

    # Create PROXY when no suitable group exists.
    main = {
        "name": "PROXY",
        "type": "select",
        "proxies": unique_keep_order(proxy_names[:10] + ["DIRECT"]),
    }
    groups.insert(0, main)
    return main


def ensure_group_refs(group: Dict[str, Any], refs_to_front: Sequence[str]) -> int:
    existing = group.get("proxies") or []
    if not isinstance(existing, list):
        existing = []
    before = list(existing)
    merged = unique_keep_order(list(refs_to_front) + [str(x).strip() for x in existing if str(x).strip()])
    group["proxies"] = merged
    return 1 if merged != before else 0


def ensure_responsive_main_order(data: Dict[str, Any], proxy_names: List[str]) -> Dict[str, Any]:
    group_names = set(get_group_names(data))
    main = find_or_create_main_group(data, proxy_names)
    desired = []
    for item in ["BEST-STABLE", "fallback-link", "best-link", "URL-TEST", "FALLBACK", "DIRECT"]:
        if item == "DIRECT" or item in group_names or item in proxy_names:
            desired.append(item)
    changed = ensure_group_refs(main, desired)

    # Also expose manual fallback groups in common selectors/fallback selectors when present.
    secondary_updates = 0
    for group in get_groups(data):
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "")
        if name in SECONDARY_SELECTOR_CANDIDATES and name != main.get("name"):
            refs = [x for x in ["fallback-link", "best-link"] if x in group_names]
            secondary_updates += ensure_group_refs(group, refs)

    return {
        "main_group": str(main.get("name") or "-"),
        "main_group_changed": bool(changed),
        "secondary_groups_changed": secondary_updates,
    }


def apply_dns(data: Dict[str, Any]) -> bool:
    dns = data.get("dns")
    if not isinstance(dns, dict):
        dns = {}
        data["dns"] = dns

    before = json.dumps(dns, sort_keys=True, ensure_ascii=False)
    dns["enable"] = True
    dns["ipv6"] = False
    dns["enhanced-mode"] = dns.get("enhanced-mode") or "fake-ip"
    dns["nameserver"] = ["1.1.1.1"]
    dns["fallback"] = ["8.8.8.8"]
    dns["default-nameserver"] = unique_keep_order((dns.get("default-nameserver") or []) + ["1.1.1.1", "8.8.8.8"])
    dns.setdefault("fake-ip-filter", ["*.lan", "*.local", "localhost.ptlogin2.qq.com"])
    after = json.dumps(dns, sort_keys=True, ensure_ascii=False)
    return before != after


def apply_lan_direct_rules(data: Dict[str, Any]) -> bool:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []

    before = list(rules)
    clean_rules = [str(rule).strip() for rule in rules if str(rule).strip()]
    clean_rules = [rule for rule in clean_rules if rule not in LAN_DIRECT_RULES]

    match_rules = [rule for rule in clean_rules if rule.upper().startswith("MATCH,")]
    non_match_rules = [rule for rule in clean_rules if not rule.upper().startswith("MATCH,")]

    new_rules = unique_keep_order(LAN_DIRECT_RULES + non_match_rules)
    if match_rules:
        new_rules += unique_keep_order(match_rules)
    else:
        new_rules.append("MATCH,PROXY")

    data["rules"] = new_rules
    return before != new_rules


def apply_to_file(path: Path, root: Path, max_stable: int) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    data = load_yaml(path)
    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"file": str(path), "ok": False, "reason": "no proxies found"}

    proxy_set = set(proxy_names)
    manual_names = [name for name in proxy_names if is_manual_name(name)]
    manual_set = set(manual_names)
    non_manual_names = [name for name in proxy_names if name not in manual_set]

    stable_names = stable_candidates_from_outputs(root, proxy_set, manual_set, max_stable=max_stable)
    if not stable_names:
        stable_names = non_manual_names[:max_stable]
    if not stable_names:
        stable_names = proxy_names[:max_stable]

    actions: List[str] = []
    counts: Dict[str, int] = {}

    if stable_names:
        action, count = upsert_group(data, build_group("BEST-STABLE", "url-test", stable_names, tolerance=80))
        actions.append(f"{action}:BEST-STABLE")
        counts["best_stable"] = count

    if manual_names:
        action, count = upsert_group(data, build_group("best-link", "url-test", manual_names, tolerance=80))
        actions.append(f"{action}:best-link")
        counts["best_link"] = count

        action, count = upsert_group(data, build_group("fallback-link", "fallback", manual_names))
        actions.append(f"{action}:fallback-link")
        counts["fallback_link"] = count

    main_info = ensure_responsive_main_order(data, proxy_names)
    dns_changed = apply_dns(data)
    rules_changed = apply_lan_direct_rules(data)

    dump_yaml(path, data)
    return {
        "file": str(path),
        "ok": True,
        "proxy_count": len(proxy_names),
        "manual_count": len(manual_names),
        "stable_count": len(stable_names),
        "actions": actions,
        "counts": counts,
        "main": main_info,
        "dns_changed": dns_changed,
        "rules_changed": rules_changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply responsive/stable OpenClash group layout.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--max-stable", type=int, default=10, help="Max proxies in BEST-STABLE")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default="output/Validation/summary_openclash_responsive_stability.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for file_name in args.files:
        result = apply_to_file(root / file_name, root, max(1, args.max_stable))
        if result is not None:
            results.append(result)

    summary = {
        "ok": True,
        "generated_by": "apply_openclash_responsive_stability.py",
        "files_processed": len(results),
        "max_stable": max(1, args.max_stable),
        "trusted_manual_policy": "input/links.txt and input.txt accounts are not filtered; script only groups existing manual proxy entries.",
        "groups": {
            "BEST-STABLE": "url-test for stable non-manual nodes",
            "best-link": "url-test containing trusted manual links",
            "fallback-link": "fallback containing trusted manual links",
        },
        "results": results,
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OpenClash responsive stability report: {report_path}")
    for item in results:
        print(f"[{ 'OK' if item.get('ok') else 'SKIP' }] {item.get('file')} manual={item.get('manual_count', 0)} stable={item.get('stable_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

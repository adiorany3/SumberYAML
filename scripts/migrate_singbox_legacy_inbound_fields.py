#!/usr/bin/env python3
"""Migrate sing-box legacy inbound fields to route rule actions.

Fixes errors like:
  decode config: inbounds[1]: legacy inbound fields are deprecated in sing-box 1.11.0 and removed in sing-box 1.13.0

Deprecated inbound/listen fields such as sniff, sniff_timeout, domain_strategy,
sniff_override_destination, and udp_disable_domain_unmapping are removed from
inbounds and represented as route rule actions where possible.

Manual/trusted proxy accounts from input.txt / input/links.txt are not filtered,
removed, or renamed by this script.
"""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

LEGACY_INBOUND_FIELDS = {
    "sniff",
    "sniff_timeout",
    "sniff_override_destination",
    "domain_strategy",
    "udp_disable_domain_unmapping",
}

VALID_DOMAIN_STRATEGIES = {"prefer_ipv4", "prefer_ipv6", "ipv4_only", "ipv6_only"}


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return value or fallback


def ensure_unique_tag(base: str, used: set[str]) -> str:
    tag = base
    idx = 2
    while tag in used:
        tag = f"{base}-{idx}"
        idx += 1
    used.add(tag)
    return tag


def normalize_rule(rule: Dict[str, Any]) -> str:
    return json.dumps(rule, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prepend_unique_rules(existing: List[Any], new_rules: List[Dict[str, Any]]) -> Tuple[List[Any], int]:
    seen = set()
    result: List[Any] = []
    added = 0

    for rule in existing:
        if isinstance(rule, dict):
            seen.add(normalize_rule(rule))

    for rule in new_rules:
        key = normalize_rule(rule)
        if key not in seen:
            result.append(rule)
            seen.add(key)
            added += 1

    result.extend(existing)
    return result, added


def migrate_file(path: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "path": str(path),
        "changed": False,
        "inbounds_scanned": 0,
        "inbounds_migrated": 0,
        "tags_added": 0,
        "legacy_fields_removed": 0,
        "route_rules_added": 0,
        "notes": [],
    }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        summary["notes"].append(f"skip: invalid json: {exc}")
        return summary

    if not isinstance(data, dict):
        summary["notes"].append("skip: root is not object")
        return summary

    inbounds = data.get("inbounds")
    if not isinstance(inbounds, list):
        return summary

    summary["inbounds_scanned"] = len(inbounds)
    route = data.setdefault("route", {})
    if not isinstance(route, dict):
        route = {}
        data["route"] = route
    rules = route.setdefault("rules", [])
    if not isinstance(rules, list):
        rules = []
        route["rules"] = rules

    used_tags = {str(item.get("tag")) for item in inbounds if isinstance(item, dict) and item.get("tag")}
    new_rules: List[Dict[str, Any]] = []

    for idx, inbound in enumerate(inbounds):
        if not isinstance(inbound, dict):
            continue

        legacy_present = [key for key in LEGACY_INBOUND_FIELDS if key in inbound]
        if not legacy_present:
            continue

        summary["inbounds_migrated"] += 1

        tag = inbound.get("tag")
        if not tag:
            base = slugify(f"{inbound.get('type', 'inbound')}-in-{idx}", f"inbound-{idx}")
            tag = ensure_unique_tag(base, used_tags)
            inbound["tag"] = tag
            summary["tags_added"] += 1
        else:
            tag = str(tag)

        sniff_value = inbound.pop("sniff", None)
        sniff_timeout = inbound.pop("sniff_timeout", None)
        sniff_override = inbound.pop("sniff_override_destination", None)
        domain_strategy = inbound.pop("domain_strategy", None)
        udp_unmap = inbound.pop("udp_disable_domain_unmapping", None)
        summary["legacy_fields_removed"] += len(legacy_present)

        # domain_strategy became resolve rule action in sing-box 1.11 migration.
        if isinstance(domain_strategy, str) and domain_strategy in VALID_DOMAIN_STRATEGIES:
            new_rules.append({
                "inbound": tag,
                "action": "resolve",
                "strategy": domain_strategy,
            })

        # udp_disable_domain_unmapping moved to route-options action.
        if bool(udp_unmap):
            new_rules.append({
                "inbound": tag,
                "action": "route-options",
                "udp_disable_domain_unmapping": True,
            })

        # sniff and sniff_timeout became sniff rule action. In sing-box 1.13+
        # sniff action itself is the supported replacement; the old
        # sniff_override_destination field has no direct field in the new sniff
        # action, so it is intentionally removed to keep the profile importable.
        if bool(sniff_value) or sniff_timeout is not None or sniff_override is not None:
            sniff_rule: Dict[str, Any] = {
                "inbound": tag,
                "action": "sniff",
            }
            if sniff_timeout:
                sniff_rule["timeout"] = str(sniff_timeout)
            new_rules.append(sniff_rule)
            if sniff_override is not None:
                summary["notes"].append(
                    f"{tag}: removed sniff_override_destination; new sniff action has no direct equivalent field"
                )

    if new_rules:
        updated_rules, added = prepend_unique_rules(rules, new_rules)
        route["rules"] = updated_rules
        summary["route_rules_added"] = added

    changed = summary["legacy_fields_removed"] > 0 or summary["route_rules_added"] > 0 or summary["tags_added"] > 0
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["changed"] = True

    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON files")
    parser.add_argument("--glob", default="*.json", help="Glob pattern")
    parser.add_argument("--report", default="output/SingBox/summary_legacy_inbound_migration.json")
    args = parser.parse_args()

    root = Path(args.dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(root.glob(args.glob)) if root.exists() else []
    results = [migrate_file(path) for path in files if path.is_file()]

    report = {
        "ok": True,
        "scanned": len(results),
        "changed": sum(1 for item in results if item.get("changed")),
        "route_rules_added": sum(int(item.get("route_rules_added", 0) or 0) for item in results),
        "legacy_fields_removed": sum(int(item.get("legacy_fields_removed", 0) or 0) for item in results),
        "files": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

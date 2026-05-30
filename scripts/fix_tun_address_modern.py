#!/usr/bin/env python3
"""Fix sing-box TUN inbound address fields for sing-box >= 1.12.

Converts deprecated legacy TUN fields:
- inet4_address + inet6_address -> address
- inet4_route_address + inet6_route_address -> route_address
- inet4_route_exclude_address + inet6_route_exclude_address -> route_exclude_address

This script does NOT filter, remove, test, or quarantine proxy accounts.
It only changes TUN inbound compatibility fields and writes a summary report.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def merge_field(obj: dict, old_keys: list[str], new_key: str) -> int:
    """Merge values from old_keys into new_key and remove old_keys.

    Returns number of old fields removed.
    """
    removed = 0
    values: list[Any] = []

    existing = obj.get(new_key)
    values.extend(as_list(existing))

    for key in old_keys:
        if key in obj:
            values.extend(as_list(obj.get(key)))
            obj.pop(key, None)
            removed += 1

    # Keep stable order and remove duplicates by JSON representation.
    deduped = []
    seen = set()
    for item in values:
        if item in (None, "", []):
            continue
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(item)

    if deduped:
        obj[new_key] = deduped

    return removed


def fix_inbound(inbound: dict) -> dict:
    result = {
        "tag": inbound.get("tag", "-"),
        "changed": False,
        "removed_fields": [],
    }

    if inbound.get("type") != "tun":
        return result

    field_groups = [
        (["inet4_address", "inet6_address"], "address"),
        (["inet4_route_address", "inet6_route_address"], "route_address"),
        (["inet4_route_exclude_address", "inet6_route_exclude_address"], "route_exclude_address"),
    ]

    for old_keys, new_key in field_groups:
        before = set(inbound.keys())
        removed = merge_field(inbound, old_keys, new_key)
        after = set(inbound.keys())
        if removed:
            result["changed"] = True
            result["removed_fields"].extend(sorted(before - after))

    # For modern sing-box, address must be a list. If a previous generator wrote string, normalize it.
    if "address" in inbound and not isinstance(inbound["address"], list):
        inbound["address"] = as_list(inbound["address"])
        result["changed"] = True

    if "route_address" in inbound and not isinstance(inbound["route_address"], list):
        inbound["route_address"] = as_list(inbound["route_address"])
        result["changed"] = True

    if "route_exclude_address" in inbound and not isinstance(inbound["route_exclude_address"], list):
        inbound["route_exclude_address"] = as_list(inbound["route_exclude_address"])
        result["changed"] = True

    return result


def fix_file(path: Path) -> dict:
    report = {
        "file": str(path),
        "ok": False,
        "changed": False,
        "tun_inbounds_changed": 0,
        "details": [],
        "error": "",
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Top-level JSON is not an object")

        inbounds = data.get("inbounds")
        if not isinstance(inbounds, list):
            report["ok"] = True
            return report

        for inbound in inbounds:
            if not isinstance(inbound, dict):
                continue
            item = fix_inbound(inbound)
            if item.get("changed"):
                report["changed"] = True
                report["tun_inbounds_changed"] += 1
                report["details"].append(item)

        if report["changed"]:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        report["ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert legacy sing-box TUN address fields to modern address fields.")
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON profiles")
    parser.add_argument("--report", default="output/SingBox/summary_tun_modern_fix.json")
    args = parser.parse_args()

    root = Path(args.dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(root.glob("*.json")) if root.exists() else []
    summary = {
        "ok": True,
        "profile_dir": str(root),
        "files_scanned": len(files),
        "files_changed": 0,
        "tun_inbounds_changed": 0,
        "note": "Trusted manual accounts from input/links.txt or input.txt are not filtered or removed by this script.",
        "files": [],
    }

    for path in files:
        # Skip summary/report files.
        if path.name.startswith("summary_"):
            continue
        item = fix_file(path)
        summary["files"].append(item)
        if not item.get("ok"):
            summary["ok"] = False
        if item.get("changed"):
            summary["files_changed"] += 1
            summary["tun_inbounds_changed"] += int(item.get("tun_inbounds_changed") or 0)

    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

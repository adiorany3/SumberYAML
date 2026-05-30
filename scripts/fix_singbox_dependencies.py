#!/usr/bin/env python3
"""Fix sing-box outbound dependency errors.

Typical import error handled by this script:
  dependency AUTO-BEST-PING not found for outbound PROXY

The script is deliberately conservative:
- it never removes real proxy outbounds, including trusted/manual accounts from input/links.txt;
- it creates missing AUTO-BEST-PING / AUTO-BEST-STABLE urltest groups when selectors reference them;
- it removes only broken group references that point to tags not present in the same JSON;
- it fixes route.final when it points to a missing tag;
- it writes a summary to output/SingBox/summary_dependency_fix.json.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

REGULAR_TYPES = {
    "vless",
    "vmess",
    "trojan",
    "shadowsocks",
    "hysteria",
    "hysteria2",
    "tuic",
    "ssh",
    "wireguard",
}
GROUP_TYPES = {"selector", "urltest"}
SPECIAL_TYPES = {"direct"}
AUTO_GROUPS = {"AUTO-BEST-PING", "AUTO-BEST-STABLE"}
SKIP_PREFIXES = ("summary_",)
SKIP_NAMES = {
    "summary.json",
    "health_state.json",
}
DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"


def read_json(path: Path) -> Dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_tag(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ensure_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def unique_order(items: List[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = clean_tag(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def collect_tags(outbounds: List[Dict[str, Any]]) -> Tuple[set[str], List[str], set[str]]:
    all_tags: set[str] = set()
    regular_tags: List[str] = []
    group_tags: set[str] = set()
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        tag = clean_tag(outbound.get("tag"))
        typ = str(outbound.get("type") or "").strip().lower()
        if not tag:
            continue
        all_tags.add(tag)
        if typ in REGULAR_TYPES:
            regular_tags.append(tag)
        elif typ in GROUP_TYPES:
            group_tags.add(tag)
    return all_tags, regular_tags, group_tags


def ensure_direct(outbounds: List[Dict[str, Any]]) -> bool:
    for outbound in outbounds:
        if isinstance(outbound, dict) and outbound.get("type") == "direct" and outbound.get("tag") == "DIRECT":
            return False
    outbounds.append({"type": "direct", "tag": "DIRECT"})
    return True


def find_group(outbounds: List[Dict[str, Any]], tag: str) -> Dict[str, Any] | None:
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        if outbound.get("tag") == tag and str(outbound.get("type") or "").lower() in GROUP_TYPES:
            return outbound
    return None


def ensure_auto_group(
    outbounds: List[Dict[str, Any]],
    tag: str,
    regular_tags: List[str],
    *,
    interval: str,
    tolerance: int,
    idle_timeout: str,
    safe_file: bool,
) -> int:
    """Create or repair an AUTO-BEST-* urltest group."""
    if not regular_tags:
        return 0

    changes = 0
    group = find_group(outbounds, tag)
    if group is None:
        group = {"type": "urltest", "tag": tag}
        # Put group near the beginning. Order is not required by sing-box, but this
        # makes the file easier to inspect.
        insert_at = 0
        if outbounds and outbounds[0].get("tag") == "DIRECT":
            insert_at = 1
        outbounds.insert(insert_at, group)
        changes += 1

    desired = {
        "type": "urltest",
        "tag": tag,
        "outbounds": unique_order(list(group.get("outbounds", [])) + regular_tags),
        "url": group.get("url") or DEFAULT_TEST_URL,
        "interval": group.get("interval") or interval,
        "tolerance": group.get("tolerance") if isinstance(group.get("tolerance"), int) else tolerance,
    }
    if not safe_file:
        desired["idle_timeout"] = group.get("idle_timeout") or idle_timeout
        desired["interrupt_exist_connections"] = False

    for key, value in desired.items():
        if group.get(key) != value:
            group[key] = value
            changes += 1
    return changes


def fix_group_members(
    group: Dict[str, Any],
    *,
    all_tags: set[str],
    regular_tags: List[str],
    group_tags: set[str],
    auto_ping_exists: bool,
    auto_stable_exists: bool,
) -> Tuple[int, List[str]]:
    changes = 0
    missing: List[str] = []
    own_tag = clean_tag(group.get("tag"))
    typ = str(group.get("type") or "").strip().lower()
    original = ensure_list(group.get("outbounds"))

    valid_members: List[str] = []
    for member in original:
        tag = clean_tag(member)
        if not tag or tag == own_tag:
            continue
        if tag in all_tags:
            # urltest should contain real outbound tags. Keeping nested groups in
            # urltest can work in some versions, but it is a common source of
            # mobile import/runtime issues. selector can contain group or real tags.
            if typ == "urltest" and tag not in regular_tags:
                continue
            valid_members.append(tag)
        else:
            missing.append(tag)

    if own_tag in AUTO_GROUPS and regular_tags:
        # AUTO groups should always have real proxies.
        valid_members = unique_order(valid_members + regular_tags)

    if own_tag == "PROXY":
        preferred: List[str] = []
        if auto_stable_exists:
            preferred.append("AUTO-BEST-STABLE")
        if auto_ping_exists:
            preferred.append("AUTO-BEST-PING")
        preferred.extend(valid_members)
        preferred.append("DIRECT")
        preferred.extend(regular_tags)
        valid_members = unique_order([x for x in preferred if x in all_tags and x != own_tag])
    else:
        valid_members = unique_order(valid_members)

    if not valid_members:
        if typ == "urltest" and regular_tags:
            valid_members = regular_tags[:]
        elif typ == "selector":
            fallback: List[str] = []
            if auto_stable_exists:
                fallback.append("AUTO-BEST-STABLE")
            if auto_ping_exists:
                fallback.append("AUTO-BEST-PING")
            fallback.extend(regular_tags)
            fallback.append("DIRECT")
            valid_members = unique_order([x for x in fallback if x in all_tags and x != own_tag])
        else:
            valid_members = []

    if group.get("outbounds") != valid_members:
        group["outbounds"] = valid_members
        changes += 1

    if typ == "selector":
        default = clean_tag(group.get("default"))
        if default not in valid_members:
            new_default = valid_members[0] if valid_members else "DIRECT"
            if group.get("default") != new_default:
                group["default"] = new_default
                changes += 1

    return changes, missing


def fix_route(data: Dict[str, Any], all_tags: set[str]) -> int:
    changes = 0
    route = data.get("route")
    if not isinstance(route, dict):
        data["route"] = {"final": "PROXY" if "PROXY" in all_tags else "DIRECT"}
        return 1
    final = clean_tag(route.get("final"))
    if final not in all_tags:
        new_final = "PROXY" if "PROXY" in all_tags else ("AUTO-BEST-STABLE" if "AUTO-BEST-STABLE" in all_tags else ("AUTO-BEST-PING" if "AUTO-BEST-PING" in all_tags else "DIRECT"))
        route["final"] = new_final
        changes += 1
    return changes


def fix_config(data: Dict[str, Any], *, interval: str, tolerance: int, idle_timeout: str, safe_file: bool) -> Dict[str, Any]:
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        data["outbounds"] = [{"type": "direct", "tag": "DIRECT"}]
        data["route"] = {"final": "DIRECT"}
        return {"changed": True, "created_auto_groups": [], "removed_missing_refs": [], "reason": "missing_outbounds"}

    changes = 0
    removed_missing_refs: List[Dict[str, Any]] = []
    created_auto_groups: List[str] = []

    if ensure_direct(outbounds):
        changes += 1

    all_tags, regular_tags, group_tags = collect_tags(outbounds)

    # If a selector/route references AUTO-BEST-PING or AUTO-BEST-STABLE but the group
    # is missing, create it from existing real proxies. This directly fixes:
    # dependency AUTO-BEST-PING not found for outbound PROXY.
    referenced: set[str] = set()
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        typ = str(outbound.get("type") or "").strip().lower()
        if typ in GROUP_TYPES:
            referenced.update(clean_tag(x) for x in ensure_list(outbound.get("outbounds")))
            default = clean_tag(outbound.get("default"))
            if default:
                referenced.add(default)
    route = data.get("route")
    if isinstance(route, dict):
        final = clean_tag(route.get("final"))
        if final:
            referenced.add(final)

    for auto_tag in sorted(AUTO_GROUPS):
        if auto_tag in referenced and auto_tag not in group_tags and regular_tags:
            delta = ensure_auto_group(
                outbounds,
                auto_tag,
                regular_tags,
                interval=interval,
                tolerance=tolerance,
                idle_timeout=idle_timeout,
                safe_file=safe_file,
            )
            if delta:
                changes += delta
                created_auto_groups.append(auto_tag)

    # If PROXY exists but no AUTO-BEST-PING and real proxies exist, always create
    # AUTO-BEST-PING because Streamlit/previous profiles may expect it.
    all_tags, regular_tags, group_tags = collect_tags(outbounds)
    if "PROXY" in group_tags and "AUTO-BEST-PING" not in group_tags and regular_tags:
        delta = ensure_auto_group(
            outbounds,
            "AUTO-BEST-PING",
            regular_tags,
            interval=interval,
            tolerance=tolerance,
            idle_timeout=idle_timeout,
            safe_file=safe_file,
        )
        if delta:
            changes += delta
            created_auto_groups.append("AUTO-BEST-PING")

    all_tags, regular_tags, group_tags = collect_tags(outbounds)
    auto_ping_exists = "AUTO-BEST-PING" in group_tags
    auto_stable_exists = "AUTO-BEST-STABLE" in group_tags

    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        typ = str(outbound.get("type") or "").strip().lower()
        if typ not in GROUP_TYPES:
            continue
        delta, missing = fix_group_members(
            outbound,
            all_tags=all_tags,
            regular_tags=regular_tags,
            group_tags=group_tags,
            auto_ping_exists=auto_ping_exists,
            auto_stable_exists=auto_stable_exists,
        )
        changes += delta
        if missing:
            removed_missing_refs.append({"group": outbound.get("tag"), "missing": unique_order(missing)})

    all_tags, _, _ = collect_tags(outbounds)
    changes += fix_route(data, all_tags | {"DIRECT"})

    return {
        "changed": bool(changes),
        "changes": changes,
        "created_auto_groups": unique_order(created_auto_groups),
        "removed_missing_refs": removed_missing_refs,
        "regular_count": len(regular_tags),
        "outbound_count": len(outbounds),
    }


def should_skip(path: Path) -> bool:
    name = path.name
    if name in SKIP_NAMES:
        return True
    if any(name.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix sing-box outbound dependency references.")
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON profiles.")
    parser.add_argument("--interval", default="3m")
    parser.add_argument("--tolerance", type=int, default=80)
    parser.add_argument("--idle-timeout", default="2h")
    parser.add_argument("--summary", default="output/SingBox/summary_dependency_fix.json")
    args = parser.parse_args()

    target_dir = Path(args.dir)
    summary_path = Path(args.summary)
    target_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    if not target_dir.exists():
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(summary_path, {"ok": True, "files": [], "note": "directory_not_found"})
        return 0

    for path in sorted(target_dir.glob("*.json")):
        if should_skip(path):
            continue
        data = read_json(path)
        if data is None:
            results.append({"file": str(path), "ok": False, "reason": "invalid_json"})
            continue
        safe_file = path.name.endswith("-safe.json")
        report = fix_config(
            data,
            interval=args.interval,
            tolerance=args.tolerance,
            idle_timeout=args.idle_timeout,
            safe_file=safe_file,
        )
        if report.get("changed"):
            write_json(path, data)
        results.append({"file": str(path), "ok": True, **report})

    summary = {
        "ok": True,
        "processed": len(results),
        "changed": sum(1 for item in results if item.get("changed")),
        "files": results,
    }
    write_json(summary_path, summary)
    print(f"Dependency fix summary: {summary_path}")
    for item in results:
        status = "CHANGED" if item.get("changed") else "OK"
        print(f"[{status}] {item.get('file')} created={item.get('created_auto_groups', [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

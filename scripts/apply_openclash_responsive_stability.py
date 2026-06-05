#!/usr/bin/env python3
"""
OpenClash-compatible responsive post-processor for SumberYAML.

This version is intentionally conservative. It does not force Meta/Mihomo-only
root options and it removes group-level fields that often make OpenClash reject
YAML on older Clash/OpenClash cores.

What it does:
- keeps every existing proxy account intact, including manual/trusted links;
- never tests, filters, quarantines, deletes, or removes proxies;
- builds safe SAT-SET / ANTI-BENGONG / BEST-STABLE groups;
- uses only broadly compatible proxy-group keys;
- repairs risky keys from the previous turbo/no-delay patch.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import yaml

CHECK_URL = "http://www.gstatic.com/generate_204"
SPECIAL_REFS = {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}

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
    "output/openclash-ready.yaml",
    "output/openclash-lite-ready.yaml",
    "output/Performance/performance-lite.yaml",
]

CANDIDATE_SCORE_FILES = [
    "output/Health/healthy.csv",
    "output/BestPing/top5_indonesia_ping.csv",
    "output/BestPing/top10_indonesia_ping.csv",
    "output/BestPing/top5_best_ping.csv",
    "output/BestPing/top10_best_ping.csv",
    "output/Alive/alive.csv",
    "output/Alive/check_result.csv",
]

MANUAL_NAME_PREFIXES = (
    "LINK ", "LINK-", "LINK_",
    "INPUT ", "INPUT-", "INPUT_",
    "MANUAL ", "MANUAL-", "MANUAL_",
    "TRUSTED ", "TRUSTED-", "TRUSTED_",
)

MAIN_GROUP_CANDIDATES = [
    "PROXY",
    "GLOBAL",
    "SELECT",
    "AUTO",
    "Manual",
    "MANUAL",
    "proxy",
    "Proxy",
]

FAST_PROFILE_TOKENS = (
    "fast",
    "lite",
    "ready",
    "performance",
    "gaming",
)

# Keys that were too aggressive in the previous no-delay patch and can fail
# OpenClash validation on older cores.
RISKY_ROOT_KEYS = [
    "unified-delay",
    "tcp-concurrent",
]

RISKY_GROUP_KEYS = [
    "lazy",
    "timeout",
]

GROUP_RUNTIME_KEYS = [
    "url",
    "interval",
    "tolerance",
    "lazy",
    "timeout",
]

LAN_DIRECT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
]


@dataclass(frozen=True)
class Tuning:
    interval: int
    fallback_interval: int
    tolerance: int


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


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


def read_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    data = yaml.safe_load(text) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
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


def get_proxy_names(data: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    proxies = data.get("proxies") or []
    if isinstance(proxies, list):
        for item in proxies:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]).strip())
    return unique_keep_order(names)


def get_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = data.get("proxy-groups")
    if not isinstance(groups, list):
        groups = []
    cleaned: List[Dict[str, Any]] = []
    for item in groups:
        if isinstance(item, dict):
            cleaned.append(item)
    # Always assign the cleaned list back, then return the actual list stored
    # in data so callers can append/update it in-place.
    data["proxy-groups"] = cleaned
    return data["proxy-groups"]


def get_group_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(
        str(group.get("name") or "").strip()
        for group in get_groups(data)
        if isinstance(group, dict) and str(group.get("name") or "").strip()
    )


def is_manual_name(name: str) -> bool:
    upper = str(name or "").strip().upper()
    if upper.startswith(MANUAL_NAME_PREFIXES):
        return True
    return bool(re.search(r"(^|[\s_\-\[])(LINK|INPUT|MANUAL|TRUSTED)([\s_\-\]]|$)", upper))


def parse_delay_ms(row: Dict[str, str]) -> Optional[float]:
    keys = (
        "delay",
        "delay_ms",
        "avg_delay",
        "avg_delay_ms",
        "latency",
        "latency_ms",
        "ping",
        "ping_ms",
    )
    for key in keys:
        raw = str(row.get(key) or "").strip().lower().replace("ms", "")
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def read_csv_ranked_names(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            rows: List[Tuple[float, int, str]] = []
            for order, row in enumerate(reader):
                name = str(row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
                if not name:
                    continue
                delay = parse_delay_ms(row)
                rows.append((delay if delay is not None else 999999.0, order, name))
            rows.sort(key=lambda item: (item[0], item[1]))
            return unique_keep_order(name for _, _, name in rows)
    except Exception:
        return []


def stable_candidates(root: Path, proxy_set: Set[str], manual_set: Set[str], limit: int) -> List[str]:
    names: List[str] = []
    for rel in CANDIDATE_SCORE_FILES:
        for name in read_csv_ranked_names(root / rel):
            if name in proxy_set and name not in manual_set:
                names.append(name)
    return unique_keep_order(names)[: max(1, limit)]


def profile_tuning(path: Path, args: argparse.Namespace) -> Tuning:
    lower = str(path).replace("\\", "/").lower()
    if any(token in lower for token in FAST_PROFILE_TOKENS):
        return Tuning(
            interval=max(30, args.fast_interval),
            fallback_interval=max(30, args.fast_fallback_interval),
            tolerance=max(0, args.fast_tolerance),
        )
    return Tuning(
        interval=max(60, args.stable_interval),
        fallback_interval=max(60, args.stable_fallback_interval),
        tolerance=max(0, args.stable_tolerance),
    )


def clean_root_options(data: Dict[str, Any], keep_meta_options: bool) -> List[str]:
    removed: List[str] = []
    if keep_meta_options:
        return removed
    for key in RISKY_ROOT_KEYS:
        if key in data:
            removed.append(key)
            data.pop(key, None)
    return removed


def sanitize_group_keys(group: Dict[str, Any], tuning: Tuning) -> List[str]:
    removed: List[str] = []
    group_type = str(group.get("type") or "").strip().lower()

    for key in RISKY_GROUP_KEYS:
        if key in group:
            removed.append(key)
            group.pop(key, None)

    if group_type in {"select", "selector"}:
        for key in GROUP_RUNTIME_KEYS:
            if key in group:
                removed.append(key)
                group.pop(key, None)
        group["type"] = "select"
        return removed

    if group_type in {"url-test", "fallback", "load-balance"}:
        group["url"] = str(group.get("url") or CHECK_URL)
        group["interval"] = int(tuning.fallback_interval if group_type == "fallback" else tuning.interval)
        if group_type == "url-test":
            group["tolerance"] = int(tuning.tolerance)
        elif "tolerance" in group:
            removed.append("tolerance")
            group.pop("tolerance", None)

    return removed


def allowed_refs(data: Dict[str, Any], proxy_names: Sequence[str]) -> Set[str]:
    return set(proxy_names) | set(get_group_names(data)) | SPECIAL_REFS


def sanitize_group_proxies(data: Dict[str, Any], proxy_names: Sequence[str]) -> Dict[str, int]:
    allowed = allowed_refs(data, proxy_names)
    proxy_fallback = list(proxy_names[:20]) or ["DIRECT"]
    stats = {"unknown_removed": 0, "empty_repaired": 0, "self_removed": 0}

    for group in get_groups(data):
        name = str(group.get("name") or "").strip()
        refs_raw = group.get("proxies") or []
        refs = refs_raw if isinstance(refs_raw, list) else []
        fixed: List[str] = []
        for ref in refs:
            value = str(ref).strip()
            if not value:
                continue
            if value == name:
                stats["self_removed"] += 1
                continue
            if value not in allowed:
                stats["unknown_removed"] += 1
                continue
            fixed.append(value)
        fixed = unique_keep_order(fixed)
        if not fixed:
            stats["empty_repaired"] += 1
            fixed = proxy_fallback[:]
        group["proxies"] = fixed
    return stats


def build_select_group(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "select",
        "proxies": unique_keep_order(refs),
    }


def build_urltest_group(name: str, refs: Sequence[str], tuning: Tuning) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": int(tuning.interval),
        "tolerance": int(tuning.tolerance),
    }


def build_fallback_group(name: str, refs: Sequence[str], tuning: Tuning) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "fallback",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": int(tuning.fallback_interval),
    }


def upsert_group(data: Dict[str, Any], new_group: Dict[str, Any]) -> Tuple[str, int]:
    groups = get_groups(data)
    target = str(new_group.get("name") or "")
    for idx, group in enumerate(groups):
        if isinstance(group, dict) and str(group.get("name") or "") == target:
            groups[idx] = new_group
            return "updated", len(new_group.get("proxies") or [])
    groups.append(new_group)
    return "created", len(new_group.get("proxies") or [])


def find_or_create_main_group(data: Dict[str, Any], proxy_names: Sequence[str]) -> Dict[str, Any]:
    groups = get_groups(data)
    for candidate in MAIN_GROUP_CANDIDATES:
        for group in groups:
            if isinstance(group, dict) and str(group.get("name") or "").strip() == candidate:
                group["type"] = "select"
                return group
    for group in groups:
        if isinstance(group, dict) and str(group.get("type") or "").lower() in {"select", "selector"}:
            group["type"] = "select"
            return group
    group = build_select_group("PROXY", list(proxy_names[:10]) + ["DIRECT"])
    groups.insert(0, group)
    return group


def put_refs_front(group: Dict[str, Any], refs: Sequence[str], data: Dict[str, Any], proxy_names: Sequence[str]) -> bool:
    allowed = allowed_refs(data, proxy_names)
    name = str(group.get("name") or "")
    existing_raw = group.get("proxies") or []
    existing = [str(x).strip() for x in existing_raw if str(x).strip()] if isinstance(existing_raw, list) else []
    desired = [x for x in refs if x and x != name and x in allowed]
    merged = unique_keep_order(desired + existing)
    if not merged:
        merged = list(proxy_names[:10]) or ["DIRECT"]
    group["proxies"] = merged
    return merged != existing


def add_responsive_groups(data: Dict[str, Any], root: Path, path: Path, args: argparse.Namespace, tuning: Tuning) -> Dict[str, Any]:
    proxy_names = get_proxy_names(data)
    proxy_set = set(proxy_names)
    manual_names = [name for name in proxy_names if is_manual_name(name)]
    manual_set = set(manual_names)
    non_manual = [name for name in proxy_names if name not in manual_set]

    stable = stable_candidates(root, proxy_set, manual_set, args.max_stable)
    if not stable:
        stable = non_manual[: args.max_stable]
    if not stable:
        stable = proxy_names[: args.max_stable]

    combined = unique_keep_order(stable + manual_names + non_manual[: args.max_combined] + proxy_names[: args.max_combined])
    actions: List[str] = []
    counts: Dict[str, int] = {}

    if combined:
        action, count = upsert_group(data, build_fallback_group("SAT-SET", combined, tuning))
        actions.append(f"{action}:SAT-SET")
        counts["SAT-SET"] = count

        action, count = upsert_group(data, build_fallback_group("ANTI-BENGONG", combined, tuning))
        actions.append(f"{action}:ANTI-BENGONG")
        counts["ANTI-BENGONG"] = count

    if stable:
        action, count = upsert_group(data, build_urltest_group("BEST-STABLE", stable, tuning))
        actions.append(f"{action}:BEST-STABLE")
        counts["BEST-STABLE"] = count

    # Manual links stay trusted. These groups are only created when generated proxy
    # names clearly identify manual/input links. Otherwise, all proxies still remain
    # present through SAT-SET/ANTI-BENGONG/main groups.
    if manual_names:
        action, count = upsert_group(data, build_urltest_group("best-link", manual_names, tuning))
        actions.append(f"{action}:best-link")
        counts["best-link"] = count
        action, count = upsert_group(data, build_fallback_group("fallback-link", manual_names, tuning))
        actions.append(f"{action}:fallback-link")
        counts["fallback-link"] = count

    main = find_or_create_main_group(data, proxy_names)
    main_name = str(main.get("name") or "PROXY")
    preferred = [
        "SAT-SET",
        "ANTI-BENGONG",
        "BEST-STABLE",
        "fallback-link",
        "best-link",
        "FALLBACK CEPAT",
        "FALLBACK",
        "URL-TEST TOP 5 INDONESIA",
        "URL-TEST TOP 10 INDONESIA",
        "URL-TEST",
        "AUTO",
        "DIRECT",
    ]
    main_changed = put_refs_front(main, preferred, data, proxy_names)

    # Put the same safe failover groups near the front of existing selector groups.
    selector_changed = 0
    for group in get_groups(data):
        if not isinstance(group, dict):
            continue
        if str(group.get("name") or "") == main_name:
            continue
        if str(group.get("type") or "").lower() in {"select", "selector"}:
            if put_refs_front(group, ["SAT-SET", "ANTI-BENGONG", "BEST-STABLE", "DIRECT"], data, proxy_names):
                selector_changed += 1

    return {
        "actions": actions,
        "counts": counts,
        "main_group": main_name,
        "main_changed": main_changed,
        "selector_changed": selector_changed,
        "proxy_count": len(proxy_names),
        "manual_count": len(manual_names),
        "stable_count": len(stable),
    }


def ensure_safe_rules(data: Dict[str, Any], main_group: str, add_lan_direct: bool) -> Dict[str, int]:
    stats = {"lan_added": 0, "match_repaired": 0}
    rules = data.get("rules")
    if not isinstance(rules, list):
        return stats

    before = [str(rule).strip() for rule in rules if str(rule).strip()]
    fixed = before[:]

    if add_lan_direct:
        without_lan = [rule for rule in fixed if rule not in LAN_DIRECT_RULES]
        fixed = unique_keep_order(LAN_DIRECT_RULES + without_lan)
        stats["lan_added"] = len(fixed) - len(without_lan)

    group_names = set(get_group_names(data)) | SPECIAL_REFS
    repaired: List[str] = []
    for rule in fixed:
        if rule.upper().startswith("MATCH,"):
            parts = rule.split(",", 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target and target not in group_names:
                repaired.append(f"MATCH,{main_group}")
                stats["match_repaired"] += 1
            else:
                repaired.append(rule)
        else:
            repaired.append(rule)
    data["rules"] = unique_keep_order(repaired)
    return stats


def backup_file(path: Path, root: Path, backup_dir: Path) -> Optional[str]:
    if not path.exists():
        return None
    rel = path.relative_to(root)
    target = backup_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return str(target.relative_to(root))


def apply_to_file(path: Path, root: Path, args: argparse.Namespace, backup_dir: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None

    try:
        data = read_yaml(path)
    except Exception as exc:
        return {"file": str(path.relative_to(root)), "ok": False, "reason": f"YAML read failed: {exc}"}

    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"file": str(path.relative_to(root)), "ok": False, "reason": "no proxies found"}

    backup_rel = backup_file(path, root, backup_dir)
    tuning = profile_tuning(path, args)

    root_removed = clean_root_options(data, keep_meta_options=args.keep_meta_options)

    group_removed_keys: Dict[str, List[str]] = {}
    for group in get_groups(data):
        removed = sanitize_group_keys(group, tuning)
        if removed:
            group_removed_keys[str(group.get("name") or "<unnamed>")] = removed

    info = add_responsive_groups(data, root, path, args, tuning)

    # Re-sanitize after upsert so newly created groups are clean too.
    for group in get_groups(data):
        sanitize_group_keys(group, tuning)

    ref_stats = sanitize_group_proxies(data, proxy_names)
    rule_stats = ensure_safe_rules(data, str(info.get("main_group") or "PROXY"), args.add_lan_direct)

    try:
        write_yaml(path, data)
        # Read once more to catch serialization mistakes.
        read_yaml(path)
    except Exception as exc:
        if backup_rel:
            shutil.copy2(root / backup_rel, path)
        return {"file": str(path.relative_to(root)), "ok": False, "reason": f"write/verify failed, restored backup: {exc}"}

    return {
        "file": str(path.relative_to(root)),
        "ok": True,
        "backup": backup_rel,
        "tuning": {
            "interval": tuning.interval,
            "fallback_interval": tuning.fallback_interval,
            "tolerance": tuning.tolerance,
        },
        "removed_root_keys": root_removed,
        "removed_group_keys": group_removed_keys,
        "reference_repair": ref_stats,
        "rules": rule_stats,
        **info,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply safe responsive OpenClash groups without breaking older OpenClash cores.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default="output/Validation/summary_openclash_safe_satset.json")
    parser.add_argument("--max-stable", type=int, default=env_int("RESPONSIVE_TOP_N", 15))
    parser.add_argument("--max-combined", type=int, default=env_int("RESPONSIVE_COMBINED_MAX", 30))
    parser.add_argument("--fast-interval", type=int, default=env_int("RESPONSIVE_INTERVAL_FAST", env_int("URL_TEST_INTERVAL", 60)))
    parser.add_argument("--fast-fallback-interval", type=int, default=env_int("RESPONSIVE_FALLBACK_INTERVAL", 60))
    parser.add_argument("--fast-tolerance", type=int, default=env_int("RESPONSIVE_TOLERANCE_FAST", env_int("URL_TEST_TOLERANCE", 20)))
    parser.add_argument("--stable-interval", type=int, default=env_int("RESPONSIVE_INTERVAL_STABLE", 180))
    parser.add_argument("--stable-fallback-interval", type=int, default=env_int("RESPONSIVE_STABLE_FALLBACK_INTERVAL", 180))
    parser.add_argument("--stable-tolerance", type=int, default=env_int("RESPONSIVE_TOLERANCE_STABLE", 50))
    parser.add_argument("--keep-meta-options", action="store_true", default=env_bool("OPENCLASH_KEEP_META_OPTIONS", False), help="Keep unified-delay/tcp-concurrent if your OpenClash core supports them")
    parser.add_argument("--add-lan-direct", action=argparse.BooleanOptionalAction, default=env_bool("OPENCLASH_ADD_LAN_DIRECT", False), help="Add LAN/private IP direct rules")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    args.max_stable = max(1, int(args.max_stable))
    args.max_combined = max(args.max_stable, int(args.max_combined))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = root / "output" / "Backup" / f"openclash-safe-satset-{stamp}"
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for rel in args.files:
        result = apply_to_file(root / rel, root, args, backup_dir)
        if result is not None:
            results.append(result)

    summary = {
        "ok": all(item.get("ok") for item in results) if results else False,
        "generated_by": "apply_openclash_responsive_stability.py",
        "mode": "safe-satset-openclash-compatible",
        "files_processed": len(results),
        "backup_dir": str(backup_dir.relative_to(root)) if backup_dir.exists() else None,
        "trusted_manual_policy": "Existing proxies are never tested, filtered, quarantined, deleted, or removed by this post-processor.",
        "compatibility_policy": {
            "root_meta_options_removed_by_default": RISKY_ROOT_KEYS,
            "group_fields_removed_by_default": RISKY_GROUP_KEYS,
            "dns_not_forced": True,
            "zero_delay_not_possible": "OpenClash still needs health-check and fallback intervals; this patch uses safer fast intervals instead of invalid zero-delay settings.",
        },
        "results": results,
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OpenClash safe sat-set report: {report_path}")
    for item in results:
        status = "OK" if item.get("ok") else "SKIP"
        tuning = item.get("tuning") or {}
        print(
            f"[{status}] {item.get('file')} "
            f"proxy={item.get('proxy_count', 0)} "
            f"manual={item.get('manual_count', 0)} "
            f"stable={item.get('stable_count', 0)} "
            f"interval={tuning.get('interval', '-')} "
            f"fallback={tuning.get('fallback_interval', '-')}"
        )
        if not item.get("ok"):
            print(f"  reason: {item.get('reason')}")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

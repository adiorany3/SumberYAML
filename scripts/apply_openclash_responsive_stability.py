#!/usr/bin/env python3
"""
Apply a more responsive OpenClash YAML structure for SumberYAML.

Design goals:
- Do not test, filter, quarantine, remove, or rewrite trusted/manual accounts.
- Keep existing proxies intact; only organize proxy-groups, DNS fallback, and LAN DIRECT rules.
- Make fast/lite/ready profiles fail over as quickly as practical by using short intervals, lazy=false, and short timeout.
- Enable low-latency Mihomo/OpenClash options such as unified-delay and tcp-concurrent.
- Keep trusted/manual accounts intact; never test, filter, quarantine, or remove them.
- Build/refresh SAT-SET, BEST-STABLE, ANTI-BENGONG, best-link, and fallback-link groups when data exists.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
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
    "output/openclash-ready.yaml",
    "output/openclash-lite-ready.yaml",
    "output/Performance/performance-lite.yaml",
]

CHECK_URL = "https://www.gstatic.com/generate_204"
SPECIAL_DIRECT_REJECT = {"DIRECT", "REJECT", "PASS"}

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
    "AUTO",
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
    "INDONESIA-BEST",
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

CANDIDATE_SCORE_FILES = [
    "output/Health/healthy.csv",
    "output/BestPing/top5_indonesia_ping.csv",
    "output/BestPing/top10_indonesia_ping.csv",
    "output/BestPing/top5_best_ping.csv",
    "output/BestPing/top10_best_ping.csv",
    "output/Alive/alive.csv",
    "output/Alive/check_result.csv",
]

RESPONSIVE_FRONT_ORDER = [
    "SAT-SET",
    "ANTI-BENGONG",
    "BEST-STABLE",
    "fallback-link",
    "best-link",
    "INDONESIA-BEST",
    "URL-TEST TOP 10 INDONESIA",
    "URL-TEST",
    "FALLBACK",
    "DIRECT",
]


@dataclass(frozen=True)
class HealthcheckTuning:
    interval: int
    fallback_interval: int
    tolerance: int
    timeout: int
    lazy: bool


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


def bool_text(value: bool) -> str:
    return "true" if value else "false"


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
    return bool(re.search(r"(^|[\s_\-\[])(LINK|INPUT|MANUAL|TRUSTED)([\s_\-\]]|$)", upper))


def parse_delay_ms(row: Dict[str, str]) -> Optional[float]:
    delay_keys = (
        "delay",
        "delay_ms",
        "avg_delay",
        "avg_delay_ms",
        "latency",
        "latency_ms",
        "ping",
        "ping_ms",
    )
    for key in delay_keys:
        raw = str(row.get(key) or "").strip().lower().replace("ms", "")
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def read_csv_names(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            rows: List[Tuple[float, int, str]] = []
            for order, row in enumerate(reader):
                name = (row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
                if not name:
                    continue
                delay = parse_delay_ms(row)
                score = delay if delay is not None else 999999.0
                rows.append((score, order, name))
            rows.sort(key=lambda item: (item[0], item[1]))
            return unique_keep_order(name for _, _, name in rows)
    except Exception:
        return []


def stable_candidates_from_outputs(
    root: Path,
    existing_names: Set[str],
    manual_names: Set[str],
    max_stable: int,
) -> List[str]:
    names: List[str] = []
    for relative in CANDIDATE_SCORE_FILES:
        path = root / relative
        for name in read_csv_names(path):
            if name in existing_names and name not in manual_names:
                names.append(name)
    return unique_keep_order(names)[: max(1, max_stable)]


def profile_tuning(path: Path, args: argparse.Namespace) -> HealthcheckTuning:
    lower = str(path).replace("\\", "/").lower()
    is_fast_profile = any(
        token in lower
        for token in (
            "fast",
            "lite",
            "ready",
            "performance",
            "gaming",
        )
    )
    if is_fast_profile:
        return HealthcheckTuning(
            interval=max(10, args.fast_interval),
            fallback_interval=max(10, args.fallback_interval),
            tolerance=max(0, args.fast_tolerance),
            timeout=max(500, args.timeout),
            lazy=args.fast_lazy,
        )
    return HealthcheckTuning(
        interval=max(30, args.stable_interval),
        fallback_interval=max(30, args.stable_fallback_interval),
        tolerance=max(0, args.stable_tolerance),
        timeout=max(500, args.timeout),
        lazy=args.stable_lazy,
    )


def build_group(
    name: str,
    group_type: str,
    proxies: Sequence[str],
    tuning: HealthcheckTuning,
    *,
    tolerance: Optional[int] = None,
) -> Dict[str, Any]:
    interval = tuning.fallback_interval if group_type == "fallback" else tuning.interval
    group: Dict[str, Any] = {
        "name": name,
        "type": group_type,
        "proxies": unique_keep_order(proxies),
        "url": CHECK_URL,
        "interval": int(interval),
        "lazy": bool(tuning.lazy),
        "timeout": int(tuning.timeout),
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
    for group in groups:
        if isinstance(group, dict) and str(group.get("type") or "").lower() in {"select", "selector"}:
            return group
    main = {
        "name": "PROXY",
        "type": "select",
        "proxies": unique_keep_order(proxy_names[:10] + ["DIRECT"]),
    }
    groups.insert(0, main)
    return main


def valid_refs(
    refs: Sequence[str],
    group_names: Set[str],
    proxy_names: Set[str],
    current_group_name: str,
) -> List[str]:
    out: List[str] = []
    for ref in refs:
        value = str(ref).strip()
        if not value or value == current_group_name:
            continue
        if value in SPECIAL_DIRECT_REJECT or value in group_names or value in proxy_names:
            out.append(value)
    return unique_keep_order(out)


def ensure_group_refs(group: Dict[str, Any], refs_to_front: Sequence[str]) -> int:
    existing = group.get("proxies") or []
    if not isinstance(existing, list):
        existing = []
    before = [str(x).strip() for x in existing if str(x).strip()]
    merged = unique_keep_order(list(refs_to_front) + before)
    group["proxies"] = merged
    return 1 if merged != before else 0


def ensure_responsive_main_order(data: Dict[str, Any], proxy_names: List[str]) -> Dict[str, Any]:
    group_name_set = set(get_group_names(data))
    proxy_name_set = set(proxy_names)
    main = find_or_create_main_group(data, proxy_names)
    main_name = str(main.get("name") or "PROXY")
    desired = valid_refs(RESPONSIVE_FRONT_ORDER, group_name_set, proxy_name_set, main_name)
    changed = ensure_group_refs(main, desired)

    secondary_updates = 0
    for group in get_groups(data):
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "")
        if name == main_name:
            continue
        if name in SECONDARY_SELECTOR_CANDIDATES or str(group.get("type") or "").lower() in {"select", "selector"}:
            refs = valid_refs(
                ["BEST-STABLE", "ANTI-BENGONG", "fallback-link", "best-link"],
                group_name_set,
                proxy_name_set,
                name,
            )
            secondary_updates += ensure_group_refs(group, refs)

    return {
        "main_group": main_name,
        "main_group_changed": bool(changed),
        "secondary_groups_changed": secondary_updates,
    }


def tune_existing_groups(data: Dict[str, Any], tuning: HealthcheckTuning) -> int:
    changed = 0
    for group in get_groups(data):
        if not isinstance(group, dict):
            continue
        group_type = str(group.get("type") or "").lower().strip()
        if group_type not in {"url-test", "fallback", "load-balance"}:
            continue

        before = json.dumps(group, sort_keys=True, ensure_ascii=False)
        group["url"] = group.get("url") or CHECK_URL
        group["interval"] = int(tuning.fallback_interval if group_type == "fallback" else tuning.interval)
        group["lazy"] = bool(tuning.lazy)
        group["timeout"] = int(tuning.timeout)
        if group_type == "url-test":
            group["tolerance"] = int(tuning.tolerance)
        after = json.dumps(group, sort_keys=True, ensure_ascii=False)
        if before != after:
            changed += 1
    return changed


def apply_low_latency_core(data: Dict[str, Any]) -> bool:
    before = json.dumps(
        {
            "unified-delay": data.get("unified-delay"),
            "tcp-concurrent": data.get("tcp-concurrent"),
            "profile": data.get("profile"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )

    # Supported by modern Clash.Meta/Mihomo cores used by OpenClash. Older cores generally ignore unknown keys.
    data["unified-delay"] = True
    data["tcp-concurrent"] = True

    profile = data.get("profile")
    if not isinstance(profile, dict):
        profile = {}
        data["profile"] = profile

    # Sat-set mode should not stick to a stale selected node after config reload.
    profile["store-selected"] = False
    profile.setdefault("store-fake-ip", True)

    after = json.dumps(
        {
            "unified-delay": data.get("unified-delay"),
            "tcp-concurrent": data.get("tcp-concurrent"),
            "profile": data.get("profile"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return before != after


def apply_dns(data: Dict[str, Any]) -> bool:
    dns = data.get("dns")
    if not isinstance(dns, dict):
        dns = {}
        data["dns"] = dns

    before = json.dumps(dns, sort_keys=True, ensure_ascii=False)
    dns["enable"] = True
    dns["ipv6"] = False
    dns.setdefault("enhanced-mode", "fake-ip")
    existing_default = [str(x) for x in dns.get("default-nameserver", []) if str(x).strip()]
    existing_nameserver = [str(x) for x in dns.get("nameserver", []) if str(x).strip()]
    existing_fallback = [str(x) for x in dns.get("fallback", []) if str(x).strip()]

    dns["default-nameserver"] = unique_keep_order(["1.1.1.1", "8.8.8.8", "9.9.9.9"] + existing_default)
    dns["nameserver"] = unique_keep_order(
        ["https://dns.cloudflare.com/dns-query", "https://dns.google/dns-query", "1.1.1.1"]
        + existing_nameserver
    )
    dns["fallback"] = unique_keep_order(
        ["https://dns.google/dns-query", "https://dns.cloudflare.com/dns-query", "8.8.8.8", "1.0.0.1"]
        + existing_fallback
    )
    dns["fake-ip-filter"] = unique_keep_order(
        [str(x) for x in dns.get("fake-ip-filter", []) if str(x).strip()]
        + ["*.lan", "*.local", "localhost", "localhost.*"]
    )
    after = json.dumps(dns, sort_keys=True, ensure_ascii=False)
    return before != after


def apply_lan_direct_rules(data: Dict[str, Any], match_group: str = "PROXY") -> bool:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
    before = [str(rule).strip() for rule in rules if str(rule).strip()]

    clean_rules = [rule for rule in before if rule not in LAN_DIRECT_RULES]
    match_rules = [rule for rule in clean_rules if rule.upper().startswith("MATCH,")]
    non_match_rules = [rule for rule in clean_rules if not rule.upper().startswith("MATCH,")]
    new_rules = unique_keep_order(LAN_DIRECT_RULES + non_match_rules)
    if match_rules:
        new_rules += unique_keep_order(match_rules)
    else:
        new_rules.append(f"MATCH,{match_group or 'PROXY'}")

    data["rules"] = new_rules
    return before != new_rules


def apply_to_file(path: Path, root: Path, args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None

    data = load_yaml(path)
    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"file": str(path.relative_to(root)), "ok": False, "reason": "no proxies found"}

    tuning = profile_tuning(path, args)
    proxy_set = set(proxy_names)
    manual_names = [name for name in proxy_names if is_manual_name(name)]
    manual_set = set(manual_names)
    non_manual_names = [name for name in proxy_names if name not in manual_set]

    stable_names = stable_candidates_from_outputs(root, proxy_set, manual_set, max_stable=args.max_stable)
    if not stable_names:
        stable_names = non_manual_names[: args.max_stable]
    if not stable_names:
        stable_names = proxy_names[: args.max_stable]

    actions: List[str] = []
    counts: Dict[str, int] = {}

    if stable_names:
        satset_candidates = unique_keep_order(stable_names + manual_names + non_manual_names[: args.max_combined])
        action, count = upsert_group(
            data,
            build_group("SAT-SET", "fallback", satset_candidates, tuning),
        )
        actions.append(f"{action}:SAT-SET")
        counts["sat_set"] = count

        action, count = upsert_group(
            data,
            build_group("BEST-STABLE", "url-test", stable_names, tuning, tolerance=tuning.tolerance),
        )
        actions.append(f"{action}:BEST-STABLE")
        counts["best_stable"] = count

        anti_bengong_candidates = unique_keep_order(stable_names + manual_names + non_manual_names[: args.max_combined])
        action, count = upsert_group(
            data,
            build_group("ANTI-BENGONG", "fallback", anti_bengong_candidates, tuning),
        )
        actions.append(f"{action}:ANTI-BENGONG")
        counts["anti_bengong"] = count

    if manual_names:
        action, count = upsert_group(
            data,
            build_group("best-link", "url-test", manual_names, tuning, tolerance=tuning.tolerance),
        )
        actions.append(f"{action}:best-link")
        counts["best_link"] = count

        action, count = upsert_group(
            data,
            build_group("fallback-link", "fallback", manual_names, tuning),
        )
        actions.append(f"{action}:fallback-link")
        counts["fallback_link"] = count

    tuned_existing_groups = tune_existing_groups(data, tuning)
    main_info = ensure_responsive_main_order(data, proxy_names)
    low_latency_core_changed = apply_low_latency_core(data)
    dns_changed = apply_dns(data)
    rules_changed = apply_lan_direct_rules(data, str(main_info.get("main_group") or "PROXY"))
    dump_yaml(path, data)

    return {
        "file": str(path.relative_to(root)),
        "ok": True,
        "proxy_count": len(proxy_names),
        "manual_count": len(manual_names),
        "stable_count": len(stable_names),
        "actions": actions,
        "counts": counts,
        "tuning": {
            "interval": tuning.interval,
            "fallback_interval": tuning.fallback_interval,
            "tolerance": tuning.tolerance,
            "timeout": tuning.timeout,
            "lazy": tuning.lazy,
        },
        "main": main_info,
        "tuned_existing_groups": tuned_existing_groups,
        "low_latency_core_changed": low_latency_core_changed,
        "dns_changed": dns_changed,
        "rules_changed": rules_changed,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply responsive/stable OpenClash group layout.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--max-stable", type=int, default=env_int("RESPONSIVE_TOP_N", 20))
    parser.add_argument("--max-combined", type=int, default=env_int("RESPONSIVE_COMBINED_MAX", 40))
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default="output/Validation/summary_openclash_responsive_stability.json")
    parser.add_argument("--fast-interval", type=int, default=env_int("RESPONSIVE_INTERVAL_FAST", env_int("URL_TEST_INTERVAL", 30)))
    parser.add_argument("--stable-interval", type=int, default=env_int("RESPONSIVE_INTERVAL_STABLE", 180))
    parser.add_argument("--fallback-interval", type=int, default=env_int("RESPONSIVE_FALLBACK_INTERVAL", 30))
    parser.add_argument("--stable-fallback-interval", type=int, default=env_int("RESPONSIVE_STABLE_FALLBACK_INTERVAL", 120))
    parser.add_argument("--fast-tolerance", type=int, default=env_int("RESPONSIVE_TOLERANCE_FAST", env_int("URL_TEST_TOLERANCE", 10)))
    parser.add_argument("--stable-tolerance", type=int, default=env_int("RESPONSIVE_TOLERANCE_STABLE", 50))
    parser.add_argument("--timeout", type=int, default=env_int("RESPONSIVE_TIMEOUT_MS", 1500))
    parser.add_argument("--fast-lazy", action=argparse.BooleanOptionalAction, default=env_bool("RESPONSIVE_FAST_LAZY", env_bool("URL_TEST_LAZY", False)))
    parser.add_argument("--stable-lazy", action=argparse.BooleanOptionalAction, default=env_bool("RESPONSIVE_STABLE_LAZY", False))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    args.max_stable = max(1, int(args.max_stable))
    args.max_combined = max(args.max_stable, int(args.max_combined))
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for file_name in args.files:
        result = apply_to_file(root / file_name, root, args)
        if result is not None:
            results.append(result)

    summary = {
        "ok": True,
        "generated_by": "apply_openclash_responsive_stability.py",
        "files_processed": len(results),
        "max_stable": args.max_stable,
        "max_combined": args.max_combined,
        "trusted_manual_policy": (
            "input/links.txt and input.txt accounts are trusted/manual. "
            "This script does not test, filter, quarantine, delete, or remove them; it only groups existing proxies."
        ),
        "responsive_policy": {
            "fast_profiles": {
                "interval": args.fast_interval,
                "fallback_interval": args.fallback_interval,
                "tolerance": args.fast_tolerance,
                "timeout": args.timeout,
                "lazy": bool_text(args.fast_lazy),
            },
            "stable_profiles": {
                "interval": args.stable_interval,
                "fallback_interval": args.stable_fallback_interval,
                "tolerance": args.stable_tolerance,
                "timeout": args.timeout,
                "lazy": bool_text(args.stable_lazy),
            },
        },
        "groups": {
            "SAT-SET": "fallback group placed first for the fastest practical failover path",
            "BEST-STABLE": "url-test for best stable non-manual nodes",
            "ANTI-BENGONG": "fallback group combining stable nodes and manual nodes for quicker failover",
            "best-link": "url-test containing trusted manual links when their generated names are identifiable",
            "fallback-link": "fallback containing trusted manual links when their generated names are identifiable",
        },
        "results": results,
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OpenClash responsive stability report: {report_path}")
    for item in results:
        status = "OK" if item.get("ok") else "SKIP"
        tuning = item.get("tuning") or {}
        print(
            f"[{status}] {item.get('file')} "
            f"manual={item.get('manual_count', 0)} "
            f"stable={item.get('stable_count', 0)} "
            f"interval={tuning.get('interval', '-')} "
            f"fallback={tuning.get('fallback_interval', '-')} "
            f"lazy={tuning.get('lazy', '-')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Route selected website/app categories through a load-balance group built only
from vmess nodes injected from input/links.txt / input.txt / links.txt.

Policy:
- INPUT-VMESS-LB is type: load-balance and contains only vmess proxies whose
  names indicate they came from trusted manual input links.
- Marketplace, social-media (including LinkedIn), and banking rules target
  selector groups, never DIRECT/REJECT directly.
- Category selector groups put INPUT-VMESS-LB first, so the user can still
  manually switch to fallback/DIRECT from the selector if needed.
- DIRECT/REJECT remain allowed only inside select groups.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

import yaml

CHECK_URL = "http://www.gstatic.com/generate_204"
REPORT_PATH = "output/Validation/input_vmess_loadbalance_report.json"
VMESS_LB_GROUP = "INPUT-VMESS-LB"
SPECIAL_REFS = {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
DIRECT_REJECT_REFS = {"DIRECT", "REJECT"}

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
    "output/manual_only.yaml",
    "output/Performance/performance-lite.yaml",
]

# Groups that should route through input/links.txt vmess load-balance first.
TARGET_SELECTOR_GROUPS = [
    "QOS-MARKETPLACE",
    "QOS-SOCIAL",
    "QOS-BANKING",
    "WEB-MARKETPLACE",
    "WEB-SOCIAL",
    "WEB-BANKING",
]

# Extra fallback choices after INPUT-VMESS-LB. These are only used if they already exist.
TARGET_GROUP_FALLBACKS = [
    "MANUAL-FALLBACK",
    "MANUAL-BEST",
    "MANUAL-LINK",
    "SMART-BEST",
    "SAT-SET",
    "ANTI-BENGONG",
    "BEST-STABLE",
    "fallback-link",
    "best-link",
    "QOS-DEFAULT",
    "WEB-DEFAULT",
    "PROXY",
    "DIRECT",
]

# Priority rules; these are inserted before broader WEB/QOS/MATCH rules.
# Rules target selector groups, not DIRECT/REJECT.
PRIORITY_DOMAIN_RULES: List[Tuple[str, str]] = [
    # Marketplace / transport / e-commerce.
    ("tokopedia.com", "QOS-MARKETPLACE"),
    ("shopee.co.id", "QOS-MARKETPLACE"),
    ("shopee.com", "QOS-MARKETPLACE"),
    ("lazada.co.id", "QOS-MARKETPLACE"),
    ("bukalapak.com", "QOS-MARKETPLACE"),
    ("blibli.com", "QOS-MARKETPLACE"),
    ("tiket.com", "QOS-MARKETPLACE"),
    ("traveloka.com", "QOS-MARKETPLACE"),
    ("gojek.com", "QOS-MARKETPLACE"),
    ("grab.com", "QOS-MARKETPLACE"),
    ("maxim.com", "QOS-MARKETPLACE"),
    # Social media, including LinkedIn.
    ("linkedin.com", "QOS-SOCIAL"),
    ("licdn.com", "QOS-SOCIAL"),
    ("lnkd.in", "QOS-SOCIAL"),
    ("linkedin.cn", "QOS-SOCIAL"),
    ("facebook.com", "QOS-SOCIAL"),
    ("fbcdn.net", "QOS-SOCIAL"),
    ("messenger.com", "QOS-SOCIAL"),
    ("instagram.com", "QOS-SOCIAL"),
    ("cdninstagram.com", "QOS-SOCIAL"),
    ("threads.net", "QOS-SOCIAL"),
    ("x.com", "QOS-SOCIAL"),
    ("twitter.com", "QOS-SOCIAL"),
    ("twimg.com", "QOS-SOCIAL"),
    ("tiktok.com", "QOS-SOCIAL"),
    ("tiktokcdn.com", "QOS-SOCIAL"),
    ("whatsapp.com", "QOS-SOCIAL"),
    ("whatsapp.net", "QOS-SOCIAL"),
    ("telegram.org", "QOS-SOCIAL"),
    ("t.me", "QOS-SOCIAL"),
    # Indonesian banking and e-wallet apps/domains.
    ("bca.co.id", "QOS-BANKING"),
    ("klikbca.com", "QOS-BANKING"),
    ("mybca.bca.co.id", "QOS-BANKING"),
    ("bankmandiri.co.id", "QOS-BANKING"),
    ("livin.mandiri.co.id", "QOS-BANKING"),
    ("bri.co.id", "QOS-BANKING"),
    ("brimo.bri.co.id", "QOS-BANKING"),
    ("bni.co.id", "QOS-BANKING"),
    ("btn.co.id", "QOS-BANKING"),
    ("cimbniaga.co.id", "QOS-BANKING"),
    ("danamon.co.id", "QOS-BANKING"),
    ("permatabank.com", "QOS-BANKING"),
    ("ocbc.id", "QOS-BANKING"),
    ("jenius.com", "QOS-BANKING"),
    ("blu.id", "QOS-BANKING"),
    ("seabank.co.id", "QOS-BANKING"),
    ("bankjago.com", "QOS-BANKING"),
    ("ovo.id", "QOS-BANKING"),
    ("gopay.co.id", "QOS-BANKING"),
    ("dana.id", "QOS-BANKING"),
    ("linkaja.id", "QOS-BANKING"),
    ("shopeepay.co.id", "QOS-BANKING"),
]

MANUAL_NAME_PREFIXES = (
    "MANUAL-LINK-",
    "MANUAL ", "MANUAL-", "MANUAL_",
    "INPUT ", "INPUT-", "INPUT_",
    "LINK ", "LINK-", "LINK_",
    "TRUSTED ", "TRUSTED-", "TRUSTED_",
)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
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
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120),
        encoding="utf-8",
    )


def get_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = data.get("proxy-groups")
    if not isinstance(groups, list):
        data["proxy-groups"] = []
        return data["proxy-groups"]
    cleaned = [g for g in groups if isinstance(g, dict) and str(g.get("name") or "").strip()]
    data["proxy-groups"] = cleaned
    return cleaned


def get_group(data: Dict[str, Any], name: str) -> Dict[str, Any] | None:
    for group in get_groups(data):
        if str(group.get("name") or "") == name:
            return group
    return None


def upsert_group(data: Dict[str, Any], group: Dict[str, Any]) -> str:
    groups = get_groups(data)
    name = str(group.get("name") or "")
    for idx, existing in enumerate(groups):
        if str(existing.get("name") or "") == name:
            groups[idx] = group
            return "updated"
    groups.append(group)
    return "created"


def get_proxy_map(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in proxies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out[name] = item
    return out


def get_group_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(str(g.get("name") or "").strip() for g in get_groups(data) if g.get("name"))


def allowed_refs(data: Dict[str, Any]) -> Set[str]:
    return set(get_proxy_map(data).keys()) | set(get_group_names(data)) | SPECIAL_REFS


def is_manual_input_name(name: str) -> bool:
    upper = str(name or "").strip().upper()
    if upper.startswith(MANUAL_NAME_PREFIXES):
        return True
    return bool(re.search(r"(^|[\s_\-\[])(INPUT|MANUAL|LINK|TRUSTED)([\s_\-\]]|$)", upper))


def manual_vmess_names(data: Dict[str, Any]) -> List[str]:
    proxy_map = get_proxy_map(data)
    manual_refs: List[str] = []
    manual_group = get_group(data, "MANUAL-LINK")
    if manual_group and isinstance(manual_group.get("proxies"), list):
        manual_refs = [str(ref).strip() for ref in manual_group.get("proxies") or []]

    candidates: List[str] = []
    for name in manual_refs:
        item = proxy_map.get(name)
        if item and str(item.get("type") or "").strip().lower() == "vmess":
            candidates.append(name)

    if not candidates:
        for name, item in proxy_map.items():
            if str(item.get("type") or "").strip().lower() == "vmess" and is_manual_input_name(name):
                candidates.append(name)
    return unique_keep_order(candidates)


def build_loadbalance_group(name: str, refs: Sequence[str], interval: int, strategy: str = "") -> Dict[str, Any]:
    group: Dict[str, Any] = {
        "name": name,
        "type": "load-balance",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": int(interval),
    }
    # Keep strategy optional for older OpenClash compatibility. Set explicitly by env only.
    if strategy:
        group["strategy"] = strategy
    return group


def build_select_group(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": unique_keep_order(refs)}


def group_refs_existing(data: Dict[str, Any], refs: Sequence[str]) -> List[str]:
    allowed = allowed_refs(data)
    return [ref for ref in unique_keep_order(refs) if ref in allowed]


def target_pos(parts: Sequence[str]) -> int | None:
    if not parts:
        return None
    if parts[0].strip().upper() == "MATCH" and len(parts) >= 2:
        return 1
    if len(parts) >= 3:
        return 2
    return None


def retarget_direct_reject(rule: str) -> str:
    text = str(rule or "").strip()
    if not text or text.startswith("#"):
        return text
    parts = [p.strip() for p in text.split(",")]
    pos = target_pos(parts)
    if pos is None or pos >= len(parts):
        return text
    target = parts[pos].upper()
    if target == "DIRECT":
        parts[pos] = "QOS-BYPASS" if "QOS-BYPASS" else "WEB-BYPASS"
    elif target == "REJECT":
        parts[pos] = "QOS-BLOCK" if "QOS-BLOCK" else "WEB-BLOCK"
    return ",".join(parts)


def rule_domain(rule: str) -> str | None:
    parts = [p.strip() for p in str(rule or "").split(",")]
    if len(parts) >= 3 and parts[0].upper() == "DOMAIN-SUFFIX":
        return parts[1].lower()
    return None


def insert_priority_rules(data: Dict[str, Any]) -> Dict[str, int]:
    existing_raw = data.get("rules") or []
    existing = [retarget_direct_reject(str(r).strip()) for r in existing_raw if str(r).strip()]
    important_domains = {domain.lower() for domain, _target in PRIORITY_DOMAIN_RULES}
    # Remove old rule variants for these domains, then reinsert deterministic priority rules.
    kept = [rule for rule in existing if rule_domain(rule) not in important_domains]
    new_rules = [f"DOMAIN-SUFFIX,{domain},{target}" for domain, target in PRIORITY_DOMAIN_RULES]

    insert_at = len(kept)
    for idx, rule in enumerate(kept):
        parts = [p.strip() for p in rule.split(",")]
        pos = target_pos(parts)
        target = parts[pos] if pos is not None and pos < len(parts) else ""
        if target.startswith("QOS-") or target.startswith("WEB-") or rule.upper().startswith("MATCH,"):
            insert_at = idx
            break
    data["rules"] = unique_keep_order(kept[:insert_at] + new_rules + kept[insert_at:])
    return {"priority_rules_inserted": len(new_rules), "total_rules": len(data["rules"])}


def sanitize_group_refs(data: Dict[str, Any]) -> Dict[str, int]:
    stats = {"unknown_removed": 0, "self_removed": 0, "direct_reject_removed_from_non_select": 0, "empty_repaired": 0}
    allowed = allowed_refs(data)
    proxy_fallback = list(get_proxy_map(data).keys())[:10]
    for group in get_groups(data):
        name = str(group.get("name") or "")
        gtype = str(group.get("type") or "").strip().lower()
        refs = group.get("proxies") or []
        if not isinstance(refs, list):
            refs = []
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
            if value in DIRECT_REJECT_REFS and gtype != "select":
                stats["direct_reject_removed_from_non_select"] += 1
                continue
            fixed.append(value)
        fixed = unique_keep_order(fixed)
        if not fixed:
            stats["empty_repaired"] += 1
            if gtype == "select":
                fixed = proxy_fallback + ["DIRECT"] if proxy_fallback else ["DIRECT"]
            else:
                fixed = proxy_fallback[:]
        group["proxies"] = fixed
    return stats


def apply_policy(data: Dict[str, Any], interval: int, strategy: str) -> Dict[str, Any]:
    vmess_names = manual_vmess_names(data)
    if not vmess_names:
        # Still ensure LinkedIn/social/banking/marketplace rules target selector groups already present.
        rule_stats = insert_priority_rules(data)
        ref_stats = sanitize_group_refs(data)
        return {
            "ok": True,
            "vmess_count": 0,
            "lb_action": "skipped-no-input-vmess",
            "target_group_actions": {},
            "rule_stats": rule_stats,
            "reference_repair": ref_stats,
            "warning": "No vmess node from MANUAL-LINK/input links was found; category groups were not forced to INPUT-VMESS-LB.",
        }

    actions: Dict[str, str] = {}
    actions[VMESS_LB_GROUP] = upsert_group(data, build_loadbalance_group(VMESS_LB_GROUP, vmess_names, interval, strategy))

    target_group_actions: Dict[str, str] = {}
    for group_name in TARGET_SELECTOR_GROUPS:
        existing = get_group(data, group_name)
        existing_refs: List[str] = []
        if existing and isinstance(existing.get("proxies"), list):
            existing_refs = [str(ref).strip() for ref in existing.get("proxies") or []]
        desired = [VMESS_LB_GROUP] + existing_refs + TARGET_GROUP_FALLBACKS
        desired = group_refs_existing(data, desired)
        if not desired:
            desired = [VMESS_LB_GROUP]
        target_group_actions[group_name] = upsert_group(data, build_select_group(group_name, desired))

    rule_stats = insert_priority_rules(data)
    ref_stats = sanitize_group_refs(data)

    return {
        "ok": True,
        "vmess_count": len(vmess_names),
        "vmess_names": vmess_names,
        "lb_action": actions[VMESS_LB_GROUP],
        "target_group_actions": target_group_actions,
        "rule_stats": rule_stats,
        "reference_repair": ref_stats,
    }


def validate_data(data: Dict[str, Any], require_lb: bool) -> Dict[str, Any]:
    errors: List[str] = []
    proxies = get_proxy_map(data)
    groups = get_groups(data)
    group_map = {str(g.get("name") or ""): g for g in groups}
    allowed = set(proxies.keys()) | set(group_map.keys()) | SPECIAL_REFS

    if require_lb and VMESS_LB_GROUP not in group_map:
        errors.append(f"missing group {VMESS_LB_GROUP}")
    if VMESS_LB_GROUP in group_map:
        lb = group_map[VMESS_LB_GROUP]
        if str(lb.get("type") or "").strip().lower() != "load-balance":
            errors.append(f"{VMESS_LB_GROUP} must be type load-balance")
        refs = lb.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"{VMESS_LB_GROUP} has empty proxies")
        for ref in refs if isinstance(refs, list) else []:
            value = str(ref).strip()
            item = proxies.get(value)
            if not item:
                errors.append(f"{VMESS_LB_GROUP} ref not found: {value}")
            elif str(item.get("type") or "").strip().lower() != "vmess":
                errors.append(f"{VMESS_LB_GROUP} must contain only vmess, got {value} type={item.get('type')}")
            elif not is_manual_input_name(value):
                errors.append(f"{VMESS_LB_GROUP} must contain input/manual vmess only, got {value}")

    for group in groups:
        name = str(group.get("name") or "")
        gtype = str(group.get("type") or "").strip().lower()
        refs = group.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"group has empty proxies: {name}")
            continue
        for ref in refs:
            value = str(ref).strip()
            if value == name:
                errors.append(f"self reference: {name}")
            if value not in allowed:
                errors.append(f"unknown group reference: {name} -> {value}")
            if value in DIRECT_REJECT_REFS and gtype != "select":
                errors.append(f"DIRECT/REJECT outside selector group: {name} -> {value}")

    for rule in data.get("rules") or []:
        text = str(rule).strip()
        if not text or text.startswith("#"):
            continue
        parts = [p.strip() for p in text.split(",")]
        pos = target_pos(parts)
        if pos is not None and pos < len(parts) and parts[pos] in DIRECT_REJECT_REFS:
            errors.append(f"DIRECT/REJECT used as direct rule target: {text}")
    return {"ok": not errors, "errors": errors[:100]}


def process_file(path: Path, root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    rel = str(path.relative_to(root)) if path.exists() else str(path)
    if not path.exists():
        return {"file": rel, "ok": False, "skipped": True, "reason": "file not found"}
    try:
        data = read_yaml(path)
    except Exception as exc:
        return {"file": rel, "ok": False, "reason": f"read failed: {exc}"}
    if not data:
        return {"file": rel, "ok": False, "reason": "empty yaml"}
    try:
        info = apply_policy(data, interval=max(30, int(args.interval)), strategy=str(args.strategy or "").strip())
        validation = validate_data(data, require_lb=bool(args.require_input_vmess))
        if not validation.get("ok"):
            return {"file": rel, "ok": False, "reason": "validation failed before write", "validation": validation, **info}
        write_yaml(path, data)
        read_yaml(path)
    except Exception as exc:
        return {"file": rel, "ok": False, "reason": f"write failed: {exc}"}
    return {"file": rel, "ok": True, "validation": validation, **info}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Force selected app categories to input/links.txt vmess load-balance group.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES)
    parser.add_argument("--report", default=os.getenv("INPUT_VMESS_LB_REPORT", REPORT_PATH))
    parser.add_argument("--interval", type=int, default=env_int("INPUT_VMESS_LB_INTERVAL", 60))
    parser.add_argument("--strategy", default=os.getenv("INPUT_VMESS_LB_STRATEGY", "").strip(), help="Optional load-balance strategy; empty keeps older OpenClash compatibility.")
    parser.add_argument("--require-input-vmess", action=argparse.BooleanOptionalAction, default=env_bool("INPUT_VMESS_LB_REQUIRE_INPUT", False), help="Fail if a YAML has no vmess nodes from input links.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    results = [process_file(root / rel, root, args) for rel in args.files]
    processed = [item for item in results if not item.get("skipped")]
    summary = {
        "ok": all(item.get("ok") for item in processed) if processed else False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "apply_openclash_input_vmess_loadbalance.py",
        "policy": {
            "loadbalance_group": VMESS_LB_GROUP,
            "loadbalance_members": "only vmess proxies from trusted manual input links / MANUAL-LINK group",
            "forced_categories": TARGET_SELECTOR_GROUPS,
            "linkedin_included": True,
            "direct_reject_policy": "DIRECT/REJECT remain only inside select groups; rules target selectors.",
        },
        "settings": {
            "interval": max(30, int(args.interval)),
            "strategy": str(args.strategy or ""),
            "require_input_vmess": bool(args.require_input_vmess),
        },
        "results": results,
    }
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Input-vmess load-balance report: {report_path}")
    for item in results:
        if item.get("skipped"):
            continue
        status = "OK" if item.get("ok") else "FAIL"
        print(f"[{status}] {item.get('file')} vmess={item.get('vmess_count', 0)} lb={item.get('lb_action')}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

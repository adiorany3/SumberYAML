#!/usr/bin/env python3
"""
Add OpenClash-safe domain/category rules and category-focused proxy groups.

This script is intentionally conservative:
- only uses normal Clash/OpenClash-compatible DOMAIN-SUFFIX and GEOIP rules;
- does not add rule-providers or Meta-only options;
- does not add ss/ssr nodes;
- keeps existing MATCH rule and inserts category rules before it;
- creates select/url-test groups per website category so routing can focus on
  nodes suitable for each accessed website category;
- keeps DIRECT and REJECT only inside select-group proxy lists, never as
  direct rule targets such as MATCH,DIRECT or DOMAIN-SUFFIX,...,REJECT.
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

REPORT_PATH = "output/Validation/rule_focus_report.json"
RULE_FOCUS_MARKER_PREFIX = "# RULE-FOCUS:"
MAX_CANDIDATES_PER_CATEGORY = 24

CATEGORY_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "WEB-AI": {
        "auto": True,
        "direct_first": False,
        "keywords": [
            "openai", "chatgpt", "claude", "gemini", "copilot", "perplexity",
            "ai", "premium", "global", "sg", "singapore", "us", "usa", "jp", "japan", "hk", "hongkong",
        ],
        "domains": [
            "openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com",
            "auth0.openai.com", "anthropic.com", "claude.ai", "perplexity.ai",
            "gemini.google.com", "ai.google.dev", "makersuite.google.com",
            "copilot.microsoft.com", "huggingface.co",
        ],
    },
    "WEB-STREAMING": {
        "auto": True,
        "direct_first": False,
        "keywords": [
            "stream", "streaming", "netflix", "nf", "youtube", "media", "video",
            "premium", "global", "sg", "singapore", "us", "usa", "jp", "japan", "hk", "hongkong",
        ],
        "domains": [
            "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
            "netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com",
            "disneyplus.com", "hotstar.com", "max.com", "hbomax.com",
            "spotify.com", "scdn.co", "vidio.com", "viu.com", "iq.com",
            "primevideo.com", "amazonvideo.com",
        ],
    },
    "WEB-SOCIAL": {
        "auto": True,
        "direct_first": False,
        "keywords": [
            "social", "whatsapp", "telegram", "facebook", "instagram", "twitter", "discord",
            "tiktok", "global", "sg", "singapore", "id", "indo", "indonesia",
        ],
        "domains": [
            "whatsapp.com", "whatsapp.net", "telegram.org", "t.me",
            "facebook.com", "fbcdn.net", "messenger.com", "instagram.com",
            "cdninstagram.com", "threads.net", "twitter.com", "x.com",
            "twimg.com", "discord.com", "discord.gg", "discordapp.com",
            "tiktok.com", "tiktokv.com", "tiktokcdn.com", "byteoversea.com",
        ],
    },
    "WEB-GAMING": {
        "auto": True,
        "direct_first": False,
        "keywords": [
            "game", "gaming", "ml", "mobilelegend", "mobile legends", "steam", "riot", "valorant",
            "id", "indo", "indonesia", "sg", "singapore", "low", "ping", "stable",
        ],
        "domains": [
            "steampowered.com", "steamcommunity.com", "steamstatic.com",
            "epicgames.com", "unrealengine.com", "riotgames.com", "valorant.com",
            "roblox.com", "garena.com", "mobilelegends.com", "m.mobilelegends.com",
            "moonton.com", "pubgmobile.com", "krafton.com", "hoyoverse.com",
            "genshinimpact.com", "zenlesszonezero.com", "battle.net", "blizzard.com",
        ],
    },
    "WEB-BANKING": {
        "auto": False,
        "direct_first": True,
        "keywords": ["bank", "banking", "payment", "wallet", "id", "indo", "indonesia"],
        "domains": [
            "bca.co.id", "klikbca.com", "mybca.bca.co.id",
            "bankmandiri.co.id", "livin.mandiri.co.id", "bri.co.id", "brimo.bri.co.id",
            "bni.co.id", "btn.co.id", "cimbniaga.co.id", "danamon.co.id",
            "permatabank.com", "ocbc.id", "jenius.com", "blu.id",
            "seabank.co.id", "bankjago.com", "ovo.id", "gopay.co.id",
            "dana.id", "linkaja.id", "shopeepay.co.id",
        ],
    },
    "WEB-MARKETPLACE": {
        "auto": True,
        "direct_first": True,
        "keywords": ["shop", "market", "id", "indo", "indonesia", "sg", "singapore"],
        "domains": [
            "tokopedia.com", "shopee.co.id", "shopee.com", "lazada.co.id",
            "bukalapak.com", "blibli.com", "tiket.com", "traveloka.com",
            "gojek.com", "grab.com", "maxim.com",
        ],
    },
    "WEB-DEV": {
        "auto": True,
        "direct_first": False,
        "keywords": [
            "dev", "github", "gitlab", "docker", "npm", "api", "cloud", "global",
            "sg", "singapore", "us", "usa", "jp", "japan",
        ],
        "domains": [
            "github.com", "githubusercontent.com", "githubassets.com", "github.io",
            "gitlab.com", "npmjs.com", "nodejs.org", "pypi.org", "pythonhosted.org",
            "docker.com", "docker.io", "ghcr.io", "cloudflare.com", "vercel.com",
            "netlify.app", "stackoverflow.com", "stackexchange.com",
        ],
    },
    "WEB-GOOGLE": {
        "auto": True,
        "direct_first": False,
        "keywords": ["google", "youtube", "global", "sg", "singapore", "us", "usa", "jp", "japan"],
        "domains": [
            "google.com", "google.co.id", "gstatic.com", "googleapis.com",
            "googleusercontent.com", "ggpht.com", "google-analytics.com",
            "googlevideo.com", "ytimg.com",
        ],
    },
}

CATEGORY_ORDER = [
    "WEB-AI",
    "WEB-STREAMING",
    "WEB-SOCIAL",
    "WEB-GAMING",
    "WEB-BANKING",
    "WEB-MARKETPLACE",
    "WEB-DEV",
    "WEB-GOOGLE",
]

FALLBACK_GROUP_REFS = [
    "MANUAL-FALLBACK",
    "MANUAL-LINK",
    "MANUAL-BEST",
    "SMART-BEST",
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

# These rules intentionally target WEB-BYPASS, not DIRECT.
# The built-in DIRECT/REJECT actions are kept only inside select groups.
LAN_BYPASS_RULES = [
    "DOMAIN-SUFFIX,local,WEB-BYPASS",
    "DOMAIN-SUFFIX,lan,WEB-BYPASS",
    "IP-CIDR,127.0.0.0/8,WEB-BYPASS,no-resolve",
    "IP-CIDR,10.0.0.0/8,WEB-BYPASS,no-resolve",
    "IP-CIDR,172.16.0.0/12,WEB-BYPASS,no-resolve",
    "IP-CIDR,192.168.0.0/16,WEB-BYPASS,no-resolve",
    "IP-CIDR,169.254.0.0/16,WEB-BYPASS,no-resolve",
]

LEGACY_LAN_DIRECT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
]


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
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
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
    for proxy in data.get("proxies") or []:
        if isinstance(proxy, dict) and proxy.get("name"):
            names.append(str(proxy.get("name")).strip())
    return unique_keep_order(names)


def get_groups(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups = data.get("proxy-groups")
    if not isinstance(groups, list):
        data["proxy-groups"] = []
        return data["proxy-groups"]
    cleaned: List[Dict[str, Any]] = []
    for group in groups:
        if isinstance(group, dict) and group.get("name"):
            cleaned.append(group)
    data["proxy-groups"] = cleaned
    return cleaned


def get_group_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(str(group.get("name")).strip() for group in get_groups(data) if group.get("name"))


def allowed_refs(data: Dict[str, Any]) -> Set[str]:
    return set(get_proxy_names(data)) | set(get_group_names(data)) | SPECIAL_REFS


def upsert_group(data: Dict[str, Any], group: Dict[str, Any]) -> str:
    groups = get_groups(data)
    name = str(group.get("name") or "")
    for idx, existing in enumerate(groups):
        if str(existing.get("name") or "") == name:
            groups[idx] = group
            return "updated"
    groups.append(group)
    return "created"


def clean_name_for_keyword(name: str) -> str:
    text = str(name or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text} "


def name_matches_keywords(name: str, keywords: Sequence[str]) -> bool:
    cleaned = clean_name_for_keyword(name)
    raw = str(name or "").lower()
    for keyword in keywords:
        key = str(keyword).strip().lower()
        if not key:
            continue
        if " " in key:
            if key in raw:
                return True
        elif f" {key} " in cleaned or key in raw:
            return True
    return False


def select_category_candidates(proxy_names: Sequence[str], category_name: str, limit: int) -> List[str]:
    definition = CATEGORY_DEFINITIONS[category_name]
    keywords = definition.get("keywords") or []
    matched = [name for name in proxy_names if name_matches_keywords(name, keywords)]

    # Manual/trusted links are kept near the front if present because they are the
    # user's preferred nodes, but they do not have to match category keywords.
    manual = [name for name in proxy_names if str(name).upper().startswith(("MANUAL", "LINK", "INPUT", "TRUSTED"))]
    combined = unique_keep_order(manual[:8] + matched + list(proxy_names[:limit]))
    return combined[: max(1, limit)]


def group_refs_existing(data: Dict[str, Any], refs: Sequence[str]) -> List[str]:
    allowed = allowed_refs(data)
    return [ref for ref in unique_keep_order(refs) if ref in allowed]


def build_urltest_group(name: str, refs: Sequence[str], interval: int, tolerance: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": int(interval),
        "tolerance": int(tolerance),
    }


def build_select_group(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "select",
        "proxies": unique_keep_order(refs),
    }


def normalize_rule(rule: str) -> str:
    return str(rule or "").strip()


def is_rule_focus_rule(rule: str) -> bool:
    text = normalize_rule(rule)
    if not text:
        return False
    if text.startswith(RULE_FOCUS_MARKER_PREFIX):
        return True
    parts = [part.strip() for part in text.split(",")]
    if len(parts) >= 3 and parts[0].upper() in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "GEOIP"}:
        return parts[2] in CATEGORY_DEFINITIONS or parts[2] in {"WEB-DEFAULT", "WEB-BYPASS", "WEB-BLOCK"}
    return False


def build_category_rules(add_geoip_id_direct: bool) -> List[str]:
    rules: List[str] = []
    for category in CATEGORY_ORDER:
        domains = CATEGORY_DEFINITIONS[category].get("domains") or []
        for domain in domains:
            rules.append(f"DOMAIN-SUFFIX,{domain},{category}")
    if add_geoip_id_direct:
        rules.extend([
            "GEOIP,LAN,WEB-BYPASS,no-resolve",
            "GEOIP,ID,WEB-BANKING,no-resolve",
        ])
    return unique_keep_order(rules)


def get_rule_target_position(parts: Sequence[str]) -> int | None:
    if not parts:
        return None
    rule_type = parts[0].strip().upper()
    if rule_type == "MATCH" and len(parts) >= 2:
        return 1
    if len(parts) >= 3:
        return 2
    return None


def retarget_direct_reject_rule(rule: str) -> Tuple[str, str | None]:
    """Move DIRECT/REJECT rule targets into selector groups.

    Clash allows rules like MATCH,DIRECT, but this project keeps built-in
    DIRECT/REJECT only as options inside select groups to avoid scattered
    hard-routing targets.
    """
    text = normalize_rule(rule)
    if not text or text.startswith("#"):
        return text, None
    parts = [part.strip() for part in text.split(",")]
    pos = get_rule_target_position(parts)
    if pos is None or pos >= len(parts):
        return text, None
    target = parts[pos].strip().upper()
    if target == "DIRECT":
        parts[pos] = "WEB-BYPASS"
        return ",".join(parts), "DIRECT"
    if target == "REJECT":
        parts[pos] = "WEB-BLOCK"
        return ",".join(parts), "REJECT"
    return text, None


def insert_rules_before_match(existing_rules: Sequence[Any], new_rules: Sequence[str], add_lan_direct: bool) -> Tuple[List[str], Dict[str, int]]:
    cleaned_existing = [normalize_rule(rule) for rule in existing_rules if normalize_rule(rule)]
    cleaned_existing = [rule for rule in cleaned_existing if not is_rule_focus_rule(rule)]

    # Remove old LAN rules from earlier patch versions, then optionally add the
    # selector-targeted LAN bypass rules.
    legacy_lan = set(LAN_BYPASS_RULES + LEGACY_LAN_DIRECT_RULES)
    cleaned_existing = [rule for rule in cleaned_existing if rule not in legacy_lan]

    if add_lan_direct:
        cleaned_existing = LAN_BYPASS_RULES + cleaned_existing

    retargeted_counts = {"DIRECT": 0, "REJECT": 0}
    retargeted_existing: List[str] = []
    for rule in cleaned_existing:
        fixed, action = retarget_direct_reject_rule(rule)
        if action in retargeted_counts:
            retargeted_counts[action] += 1
        retargeted_existing.append(fixed)

    insert_at = len(retargeted_existing)
    for idx, rule in enumerate(retargeted_existing):
        if rule.upper().startswith("MATCH,"):
            insert_at = idx
            break

    merged = retargeted_existing[:insert_at] + list(new_rules) + retargeted_existing[insert_at:]
    # Retarget once more after merge, protecting against any future rule source
    # that accidentally adds DIRECT/REJECT targets.
    final_rules: List[str] = []
    for rule in merged:
        fixed, action = retarget_direct_reject_rule(rule)
        if action in retargeted_counts:
            retargeted_counts[action] += 1
        final_rules.append(fixed)
    final_rules = unique_keep_order(final_rules)
    return final_rules, {
        "category_rules_inserted": len([rule for rule in new_rules if rule.startswith("DOMAIN-SUFFIX,") or rule.startswith("GEOIP,")]),
        "total_rules": len(final_rules),
        "lan_bypass_added": len(LAN_BYPASS_RULES) if add_lan_direct else 0,
        "direct_rule_targets_retargeted": retargeted_counts["DIRECT"],
        "reject_rule_targets_retargeted": retargeted_counts["REJECT"],
    }


def sanitize_group_references(data: Dict[str, Any]) -> Dict[str, int]:
    allowed = allowed_refs(data)
    proxy_fallback = get_proxy_names(data)[:10]
    stats = {
        "unknown_removed": 0,
        "empty_repaired": 0,
        "self_removed": 0,
        "direct_reject_removed_from_non_select": 0,
    }
    for group in get_groups(data):
        name = str(group.get("name") or "")
        gtype = str(group.get("type") or "").strip().lower()
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
            # DIRECT/REJECT are allowed only as user-selectable options, not as
            # candidates in url-test/fallback/load-balance groups.
            if value in DIRECT_REJECT_REFS and gtype != "select":
                stats["direct_reject_removed_from_non_select"] += 1
                continue
            fixed.append(value)
        fixed = unique_keep_order(fixed)
        if not fixed:
            stats["empty_repaired"] += 1
            if gtype == "select":
                fixed = proxy_fallback[:] + ["DIRECT"] if proxy_fallback else ["DIRECT"]
            else:
                fixed = proxy_fallback[:] if proxy_fallback else []
        group["proxies"] = unique_keep_order(fixed)
    return stats


def add_rule_focus_to_data(data: Dict[str, Any], interval: int, tolerance: int, max_candidates: int, add_lan_direct: bool, add_geoip_id_direct: bool) -> Dict[str, Any]:
    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"ok": False, "reason": "no proxies"}

    actions: Dict[str, str] = {}
    category_counts: Dict[str, int] = {}

    # Base default group for rules or manual selection.
    default_refs = group_refs_existing(data, [
        "MANUAL-FALLBACK", "MANUAL-LINK", "MANUAL-BEST",
        "SMART-BEST", "SAT-SET", "ANTI-BENGONG", "BEST-STABLE",
        "fallback-link", "best-link", "DIRECT",
    ])
    if not default_refs:
        default_refs = proxy_names[:max_candidates] + ["DIRECT"]
    actions["WEB-DEFAULT"] = upsert_group(data, build_select_group("WEB-DEFAULT", default_refs))
    category_counts["WEB-DEFAULT"] = len(default_refs)

    # Selector-only built-in actions. Rules must target these groups rather than
    # targeting DIRECT/REJECT directly.
    bypass_refs = group_refs_existing(data, ["DIRECT", "WEB-DEFAULT"] + FALLBACK_GROUP_REFS)
    if not bypass_refs:
        bypass_refs = ["DIRECT"]
    actions["WEB-BYPASS"] = upsert_group(data, build_select_group("WEB-BYPASS", bypass_refs))
    category_counts["WEB-BYPASS"] = len(bypass_refs)

    block_refs = group_refs_existing(data, ["REJECT", "DIRECT", "WEB-DEFAULT"] + FALLBACK_GROUP_REFS)
    if not block_refs:
        block_refs = ["REJECT", "DIRECT"]
    actions["WEB-BLOCK"] = upsert_group(data, build_select_group("WEB-BLOCK", block_refs))
    category_counts["WEB-BLOCK"] = len(block_refs)

    for category in CATEGORY_ORDER:
        definition = CATEGORY_DEFINITIONS[category]
        selector_refs: List[str] = []
        auto_name = f"{category}-AUTO"

        if bool(definition.get("auto")):
            candidates = select_category_candidates(proxy_names, category, max_candidates)
            actions[auto_name] = upsert_group(data, build_urltest_group(auto_name, candidates, interval, tolerance))
            category_counts[auto_name] = len(candidates)
            selector_refs.append(auto_name)

        if bool(definition.get("direct_first")):
            selector_refs.insert(0, "DIRECT")

        selector_refs.extend(FALLBACK_GROUP_REFS)
        selector_refs.append("WEB-DEFAULT")
        selector_refs = group_refs_existing(data, selector_refs)
        if not selector_refs:
            selector_refs = proxy_names[:max_candidates] + ["DIRECT"]
        actions[category] = upsert_group(data, build_select_group(category, selector_refs))
        category_counts[category] = len(selector_refs)

    existing_rules = data.get("rules") or []
    if not isinstance(existing_rules, list):
        existing_rules = []
    new_rules = build_category_rules(add_geoip_id_direct=add_geoip_id_direct)
    data["rules"], rule_stats = insert_rules_before_match(existing_rules, new_rules, add_lan_direct=add_lan_direct)

    ref_stats = sanitize_group_references(data)
    return {
        "ok": True,
        "actions": actions,
        "category_counts": category_counts,
        "rule_stats": rule_stats,
        "reference_repair": ref_stats,
    }


def validate_data(data: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    proxies = data.get("proxies") or []
    groups = data.get("proxy-groups") or []
    rules = data.get("rules") or []
    if not isinstance(proxies, list) or not proxies:
        errors.append("proxies missing/empty")
    if not isinstance(groups, list) or not groups:
        errors.append("proxy-groups missing/empty")
    if not isinstance(rules, list) or not rules:
        errors.append("rules missing/empty")

    proxy_names = {str(p.get("name")) for p in proxies if isinstance(p, dict) and p.get("name")}
    group_names = {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}
    allowed = proxy_names | group_names | SPECIAL_REFS

    for group in groups:
        if not isinstance(group, dict):
            errors.append("proxy-group is not mapping")
            continue
        name = str(group.get("name") or "")
        gtype = str(group.get("type") or "").lower()
        if gtype not in {"select", "url-test", "fallback", "load-balance"}:
            errors.append(f"unsupported/empty group type: {name} type={gtype}")
        refs = group.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"group empty proxies: {name}")
            continue
        for ref in refs:
            value = str(ref)
            if value == name or value not in allowed:
                errors.append(f"invalid group ref: {name} -> {value}")

    for group in groups:
        if not isinstance(group, dict):
            continue
        gtype = str(group.get("type") or "").strip().lower()
        gname = str(group.get("name") or "")
        for ref in group.get("proxies") or []:
            value = str(ref).strip()
            if value in DIRECT_REJECT_REFS and gtype != "select":
                errors.append(f"DIRECT/REJECT outside select group: {gname} -> {value}")

    for rule in rules:
        text = str(rule).strip()
        if not text or text.startswith("#"):
            continue
        parts = [part.strip() for part in text.split(",")]
        pos = get_rule_target_position(parts)
        if pos is not None and pos < len(parts):
            target = parts[pos]
            if target in DIRECT_REJECT_REFS:
                errors.append(f"DIRECT/REJECT rule target is not allowed: {text}")
            elif target and target not in allowed:
                errors.append(f"invalid rule target: {text}")
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
        info = add_rule_focus_to_data(
            data=data,
            interval=max(60, int(args.interval)),
            tolerance=max(0, int(args.tolerance)),
            max_candidates=max(1, int(args.max_candidates)),
            add_lan_direct=bool(args.add_lan_direct),
            add_geoip_id_direct=bool(args.add_geoip_id_direct),
        )
        validation = validate_data(data)
        if not validation.get("ok"):
            return {"file": rel, "ok": False, "reason": "validation failed before write", "validation": validation, **info}
        write_yaml(path, data)
        # Parse again after writing.
        read_yaml(path)
    except Exception as exc:
        return {"file": rel, "ok": False, "reason": f"write failed: {exc}"}
    return {"file": rel, "ok": True, "validation": validation, **info}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add website-category focused OpenClash rules and proxy groups.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default=os.getenv("RULE_FOCUS_REPORT", REPORT_PATH))
    parser.add_argument("--interval", type=int, default=env_int("RULE_FOCUS_INTERVAL", 120))
    parser.add_argument("--tolerance", type=int, default=env_int("RULE_FOCUS_TOLERANCE", 50))
    parser.add_argument("--max-candidates", type=int, default=env_int("RULE_FOCUS_MAX_CANDIDATES", MAX_CANDIDATES_PER_CATEGORY))
    parser.add_argument("--add-lan-direct", action=argparse.BooleanOptionalAction, default=env_bool("RULE_FOCUS_ADD_LAN_DIRECT", False))
    parser.add_argument("--add-geoip-id-direct", action=argparse.BooleanOptionalAction, default=env_bool("RULE_FOCUS_ADD_GEOIP_ID", False))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    results: List[Dict[str, Any]] = []
    for rel in args.files:
        results.append(process_file(root / rel, root, args))

    processed = [item for item in results if not item.get("skipped")]
    summary = {
        "ok": all(item.get("ok") for item in processed) if processed else False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "apply_openclash_rule_focus.py",
        "mode": "website-category-rule-focus",
        "policy": {
            "rule_type": "DOMAIN-SUFFIX based category routing inserted before MATCH",
            "groups_added": CATEGORY_ORDER + ["WEB-DEFAULT", "WEB-BYPASS", "WEB-BLOCK"],
            "auto_groups": [f"{name}-AUTO" for name in CATEGORY_ORDER if CATEGORY_DEFINITIONS[name].get("auto")],
            "banking_direct_first": True,
            "marketplace_direct_first": True,
            "direct_reject_policy": "DIRECT and REJECT are allowed only inside select-group proxies; rules target WEB-BYPASS/WEB-BLOCK instead.",
            "openclash_safe": "No rule-providers, no script rules, no Meta-only root options; only select/url-test groups and DOMAIN-SUFFIX/GEOIP rules.",
        },
        "settings": {
            "interval": max(60, int(args.interval)),
            "tolerance": max(0, int(args.tolerance)),
            "max_candidates": max(1, int(args.max_candidates)),
            "add_lan_direct": bool(args.add_lan_direct),
            "add_geoip_id_direct": bool(args.add_geoip_id_direct),
        },
        "results": results,
    }
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Rule-focus report: {report_path}")
    for item in results:
        if item.get("skipped"):
            continue
        status = "OK" if item.get("ok") else "FAIL"
        stats = item.get("rule_stats") or {}
        print(f"[{status}] {item.get('file')} category_rules={stats.get('category_rules_inserted', 0)} total_rules={stats.get('total_rules', 0)}")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

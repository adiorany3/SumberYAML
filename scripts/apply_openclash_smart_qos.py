#!/usr/bin/env python3
"""
Add OpenClash-safe Smart QoS routing groups and rules.

Important scope:
- This is not Linux/SQM traffic shaping. It is smart policy routing inside
  Clash/OpenClash YAML.
- DIRECT and REJECT are never used as rule targets. Rules target selector
  groups such as QOS-BYPASS or QOS-BLOCK.
- DIRECT/REJECT are only allowed as choices inside `type: select` groups.
- Only conservative Clash-compatible DOMAIN-SUFFIX/IP-CIDR/MATCH rules and
  select/url-test/fallback groups are used.
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
REPORT_PATH = "output/Validation/smart_qos_report.json"
MAX_CANDIDATES = 24

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

QOS_GROUPS = {
    "QOS-REALTIME",
    "QOS-STREAMING",
    "QOS-AI",
    "QOS-GAMING",
    "QOS-SOCIAL",
    "QOS-WORK",
    "QOS-BANKING",
    "QOS-MARKETPLACE",
    "QOS-DOWNLOAD",
    "QOS-BYPASS",
    "QOS-BLOCK",
    "QOS-DEFAULT",
    "QOS-REALTIME-AUTO",
    "QOS-STREAMING-AUTO",
    "QOS-AI-AUTO",
    "QOS-GAMING-AUTO",
    "QOS-WORK-AUTO",
    "QOS-DOWNLOAD-AUTO",
}

QOS_DOMAIN_RULES: Dict[str, List[str]] = {
    # Latency-sensitive: meeting, voice call, chat push, and game auth/session.
    "QOS-REALTIME": [
        "zoom.us", "zoom.com", "meet.google.com", "teams.microsoft.com",
        "skype.com", "lync.com", "discord.com", "discord.gg", "discordapp.com",
        "telegram.org", "t.me", "whatsapp.com", "whatsapp.net",
    ],
    "QOS-GAMING": [
        "steampowered.com", "steamcommunity.com", "steamstatic.com",
        "steamcontent.com", "epicgames.com", "unrealengine.com",
        "riotgames.com", "valorant.com", "garena.com", "roblox.com",
        "mobilelegends.com", "moonton.com", "pubgmobile.com", "krafton.com",
        "hoyoverse.com", "genshinimpact.com", "zenlesszonezero.com",
        "battle.net", "blizzard.com",
    ],
    # High throughput but still needs stability.
    "QOS-STREAMING": [
        "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
        "netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com",
        "disneyplus.com", "hotstar.com", "max.com", "hbomax.com",
        "spotify.com", "scdn.co", "vidio.com", "viu.com", "iq.com",
        "primevideo.com", "amazonvideo.com", "twitch.tv", "ttvnw.net",
    ],
    # Interactive web apps.
    "QOS-AI": [
        "openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com",
        "anthropic.com", "claude.ai", "perplexity.ai", "gemini.google.com",
        "ai.google.dev", "copilot.microsoft.com", "huggingface.co",
    ],
    "QOS-SOCIAL": [
        "facebook.com", "fbcdn.net", "messenger.com", "instagram.com",
        "cdninstagram.com", "threads.net", "x.com", "twitter.com", "twimg.com",
        "tiktok.com", "tiktokv.com", "tiktokcdn.com", "byteoversea.com",
    ],
    "QOS-WORK": [
        "github.com", "githubusercontent.com", "githubassets.com", "github.io",
        "gitlab.com", "npmjs.com", "nodejs.org", "pypi.org", "pythonhosted.org",
        "docker.com", "docker.io", "ghcr.io", "cloudflare.com", "vercel.com",
        "netlify.app", "stackoverflow.com", "stackexchange.com", "office.com",
        "microsoft.com", "windows.net", "azure.com", "slack.com", "notion.so",
    ],
    # Sensitive local financial traffic. Rules target selector group, not DIRECT.
    "QOS-BANKING": [
        "bca.co.id", "klikbca.com", "mybca.bca.co.id", "bankmandiri.co.id",
        "livin.mandiri.co.id", "bri.co.id", "brimo.bri.co.id", "bni.co.id",
        "btn.co.id", "cimbniaga.co.id", "danamon.co.id", "permatabank.com",
        "ocbc.id", "jenius.com", "blu.id", "seabank.co.id", "bankjago.com",
        "ovo.id", "gopay.co.id", "dana.id", "linkaja.id", "shopeepay.co.id",
    ],
    "QOS-MARKETPLACE": [
        "tokopedia.com", "shopee.co.id", "shopee.com", "lazada.co.id",
        "bukalapak.com", "blibli.com", "tiket.com", "traveloka.com",
        "gojek.com", "grab.com", "maxim.com",
    ],
    # Bulk/download traffic. This group is intentionally not the first fallback
    # target, so interactive traffic remains more responsive.
    "QOS-DOWNLOAD": [
        "ubuntu.com", "debian.org", "archlinux.org", "kernel.org",
        "sourceforge.net", "fosshub.com", "apkcombo.com", "apkpure.com",
        "mediafire.com", "mega.nz", "dropbox.com", "box.com", "onedrive.live.com",
        "download.windowsupdate.com", "windowsupdate.com", "updates.cdn-apple.com",
        "swcdn.apple.com", "steamcontent.com",
    ],
    # Optional ads/tracker block via selector group.
    "QOS-BLOCK": [
        "doubleclick.net", "googlesyndication.com", "googleadservices.com",
        "adservice.google.com", "adsrvr.org", "taboola.com", "outbrain.com",
        "scorecardresearch.com", "zedo.com", "adnxs.com",
    ],
}

QOS_KEYWORDS: Dict[str, List[str]] = {
    "QOS-REALTIME": ["manual", "trusted", "best", "stable", "game", "gaming", "sg", "singapore", "id", "indo", "low", "ping"],
    "QOS-GAMING": ["game", "gaming", "ml", "mobile", "valorant", "steam", "sg", "singapore", "id", "indo", "low", "ping"],
    "QOS-STREAMING": ["stream", "streaming", "youtube", "netflix", "video", "media", "premium", "global", "sg", "us", "jp"],
    "QOS-AI": ["ai", "openai", "chatgpt", "claude", "gemini", "global", "sg", "us", "jp"],
    "QOS-WORK": ["dev", "github", "work", "api", "cloud", "global", "sg", "us", "jp"],
    "QOS-DOWNLOAD": ["fallback", "stable", "bulk", "download", "global", "id", "sg", "us"],
}

EXISTING_GROUP_PRIORITY = [
    "MANUAL-FALLBACK", "MANUAL-LINK", "MANUAL-BEST", "SMART-BEST",
    "SAT-SET", "ANTI-BENGONG", "BEST-STABLE", "fallback-link", "best-link",
    "WEB-DEFAULT", "PROXY", "FALLBACK CEPAT", "FALLBACK", "URL-TEST", "AUTO",
]

LAN_BYPASS_RULES = [
    "DOMAIN-SUFFIX,local,QOS-BYPASS",
    "DOMAIN-SUFFIX,lan,QOS-BYPASS",
    "IP-CIDR,127.0.0.0/8,QOS-BYPASS,no-resolve",
    "IP-CIDR,10.0.0.0/8,QOS-BYPASS,no-resolve",
    "IP-CIDR,172.16.0.0/12,QOS-BYPASS,no-resolve",
    "IP-CIDR,192.168.0.0/16,QOS-BYPASS,no-resolve",
    "IP-CIDR,169.254.0.0/16,QOS-BYPASS,no-resolve",
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
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
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


def get_proxy_names(data: Dict[str, Any]) -> List[str]:
    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        return []
    return unique_keep_order(str(p.get("name") or "").strip() for p in proxies if isinstance(p, dict) and p.get("name"))


def get_group_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(str(g.get("name") or "").strip() for g in get_groups(data) if g.get("name"))


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


def clean_for_keyword(name: str) -> str:
    text = str(name or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text} "


def name_matches(name: str, keywords: Sequence[str]) -> bool:
    cleaned = clean_for_keyword(name)
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


def select_candidates(proxy_names: Sequence[str], qos_group: str, limit: int) -> List[str]:
    keywords = QOS_KEYWORDS.get(qos_group, [])
    manual = [n for n in proxy_names if str(n).upper().startswith(("MANUAL", "INPUT", "TRUSTED", "LINK"))]
    matched = [n for n in proxy_names if name_matches(n, keywords)]
    default = list(proxy_names[:limit])
    return unique_keep_order(manual[:8] + matched + default)[:max(1, limit)]


def group_refs_existing(data: Dict[str, Any], refs: Sequence[str]) -> List[str]:
    allowed = allowed_refs(data)
    return [ref for ref in unique_keep_order(refs) if ref in allowed]


def build_select_group(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": unique_keep_order(refs)}


def build_urltest_group(name: str, refs: Sequence[str], interval: int, tolerance: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": int(interval),
        "tolerance": int(tolerance),
    }


def build_qos_rules(add_lan: bool) -> List[str]:
    rules: List[str] = []
    if add_lan:
        rules.extend(LAN_BYPASS_RULES)
    for target, domains in QOS_DOMAIN_RULES.items():
        for domain in domains:
            rules.append(f"DOMAIN-SUFFIX,{domain},{target}")
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


def normalize_rule(rule: Any) -> str:
    return str(rule or "").strip()


def is_smart_qos_rule(rule: str) -> bool:
    text = normalize_rule(rule)
    if not text or text.startswith("#"):
        return False
    parts = [p.strip() for p in text.split(",")]
    pos = get_rule_target_position(parts)
    return pos is not None and pos < len(parts) and parts[pos] in QOS_GROUPS


def retarget_direct_reject_rule(rule: str) -> Tuple[str, str | None]:
    text = normalize_rule(rule)
    if not text or text.startswith("#"):
        return text, None
    parts = [p.strip() for p in text.split(",")]
    pos = get_rule_target_position(parts)
    if pos is None or pos >= len(parts):
        return text, None
    target = parts[pos].strip().upper()
    if target == "DIRECT":
        parts[pos] = "QOS-BYPASS"
        return ",".join(parts), "DIRECT"
    if target == "REJECT":
        parts[pos] = "QOS-BLOCK"
        return ",".join(parts), "REJECT"
    return text, None


def insert_rules(existing_rules: Sequence[Any], new_rules: Sequence[str], force_match_qos_default: bool) -> Tuple[List[str], Dict[str, int]]:
    existing = [normalize_rule(r) for r in existing_rules if normalize_rule(r)]
    existing = [r for r in existing if not is_smart_qos_rule(r)]

    retargeted = {"DIRECT": 0, "REJECT": 0, "MATCH": 0}
    fixed_existing: List[str] = []
    for rule in existing:
        fixed, action = retarget_direct_reject_rule(rule)
        if action in retargeted:
            retargeted[action] += 1
        fixed_existing.append(fixed)

    insert_at = len(fixed_existing)
    match_found = False
    for idx, rule in enumerate(fixed_existing):
        parts = [p.strip() for p in rule.split(",")]
        pos = get_rule_target_position(parts)
        target = parts[pos] if pos is not None and pos < len(parts) else ""
        # QoS rules must be evaluated before earlier WEB-* category rules,
        # otherwise rule-focus would match first and Smart QoS would never run
        # for duplicate domains.
        if target.startswith("WEB-") or rule.upper().startswith("MATCH,"):
            insert_at = idx
            if rule.upper().startswith("MATCH,"):
                match_found = True
                if force_match_qos_default and len(parts) >= 2 and parts[1] != "QOS-DEFAULT":
                    parts[1] = "QOS-DEFAULT"
                    fixed_existing[idx] = ",".join(parts)
                    retargeted["MATCH"] += 1
            break

    # Retarget every MATCH rule, even if one appears after existing category
    # rules, so default traffic lands in QOS-DEFAULT.
    if force_match_qos_default:
        for idx, rule in enumerate(fixed_existing):
            if rule.upper().startswith("MATCH,"):
                match_found = True
                parts = [p.strip() for p in rule.split(",")]
                if len(parts) >= 2 and parts[1] != "QOS-DEFAULT":
                    parts[1] = "QOS-DEFAULT"
                    fixed_existing[idx] = ",".join(parts)
                    retargeted["MATCH"] += 1

    merged = fixed_existing[:insert_at] + list(new_rules) + fixed_existing[insert_at:]
    if force_match_qos_default and not match_found:
        merged.append("MATCH,QOS-DEFAULT")
        retargeted["MATCH"] += 1

    final: List[str] = []
    for rule in merged:
        fixed, action = retarget_direct_reject_rule(rule)
        if action in retargeted:
            retargeted[action] += 1
        final.append(fixed)

    final = unique_keep_order(final)
    return final, {
        "smart_qos_rules_inserted": len(new_rules),
        "total_rules": len(final),
        "direct_rule_targets_retargeted": retargeted["DIRECT"],
        "reject_rule_targets_retargeted": retargeted["REJECT"],
        "match_rules_retargeted_to_qos_default": retargeted["MATCH"],
    }


def sanitize_group_references(data: Dict[str, Any]) -> Dict[str, int]:
    stats = {"unknown_removed": 0, "self_removed": 0, "empty_repaired": 0, "direct_reject_removed_from_non_select": 0}
    allowed = allowed_refs(data)
    proxy_fallback = get_proxy_names(data)[:10]
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
                fixed = proxy_fallback[:] + ["DIRECT"] if proxy_fallback else ["DIRECT"]
            else:
                fixed = proxy_fallback[:]
        group["proxies"] = fixed
    return stats


def add_smart_qos(data: Dict[str, Any], interval: int, tolerance: int, max_candidates: int, add_lan: bool, force_match: bool) -> Dict[str, Any]:
    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"ok": False, "reason": "no proxies"}

    actions: Dict[str, str] = {}
    counts: Dict[str, int] = {}

    # Auto groups for categories where latency/throughput selection helps.
    for qos in ["QOS-REALTIME", "QOS-GAMING", "QOS-STREAMING", "QOS-AI", "QOS-WORK", "QOS-DOWNLOAD"]:
        auto_name = f"{qos}-AUTO"
        candidates = select_candidates(proxy_names, qos, max_candidates)
        actions[auto_name] = upsert_group(data, build_urltest_group(auto_name, candidates, interval, tolerance))
        counts[auto_name] = len(candidates)

    base_refs = group_refs_existing(data, EXISTING_GROUP_PRIORITY + ["DIRECT"])
    if not base_refs:
        base_refs = proxy_names[:max_candidates] + ["DIRECT"]

    actions["QOS-DEFAULT"] = upsert_group(data, build_select_group("QOS-DEFAULT", base_refs))
    counts["QOS-DEFAULT"] = len(base_refs)

    # Selector-only builtin actions. Rules target these, not DIRECT/REJECT.
    bypass_refs = group_refs_existing(data, ["WEB-BYPASS", "DIRECT", "QOS-DEFAULT", "WEB-DEFAULT", "PROXY"] + EXISTING_GROUP_PRIORITY)
    if not bypass_refs:
        bypass_refs = ["DIRECT"]
    actions["QOS-BYPASS"] = upsert_group(data, build_select_group("QOS-BYPASS", bypass_refs))
    counts["QOS-BYPASS"] = len(bypass_refs)

    block_refs = group_refs_existing(data, ["WEB-BLOCK", "REJECT", "QOS-BYPASS", "QOS-DEFAULT", "WEB-DEFAULT"])
    if not block_refs:
        block_refs = ["REJECT", "DIRECT"]
    actions["QOS-BLOCK"] = upsert_group(data, build_select_group("QOS-BLOCK", block_refs))
    counts["QOS-BLOCK"] = len(block_refs)

    group_layout: Dict[str, List[str]] = {
        "QOS-REALTIME": ["QOS-REALTIME-AUTO", "QOS-GAMING-AUTO", "WEB-GAMING", "WEB-SOCIAL", "MANUAL-BEST", "MANUAL-FALLBACK", "SAT-SET", "ANTI-BENGONG", "QOS-DEFAULT"],
        "QOS-GAMING": ["QOS-GAMING-AUTO", "QOS-REALTIME-AUTO", "WEB-GAMING", "MANUAL-BEST", "MANUAL-FALLBACK", "SAT-SET", "QOS-DEFAULT"],
        "QOS-STREAMING": ["QOS-STREAMING-AUTO", "WEB-STREAMING", "MANUAL-FALLBACK", "BEST-STABLE", "fallback-link", "best-link", "QOS-DEFAULT"],
        "QOS-AI": ["QOS-AI-AUTO", "WEB-AI", "QOS-REALTIME-AUTO", "MANUAL-FALLBACK", "QOS-DEFAULT"],
        "QOS-SOCIAL": ["WEB-SOCIAL", "QOS-REALTIME-AUTO", "MANUAL-FALLBACK", "QOS-DEFAULT"],
        "QOS-WORK": ["QOS-WORK-AUTO", "WEB-DEV", "WEB-GOOGLE", "MANUAL-FALLBACK", "QOS-DEFAULT"],
        "QOS-BANKING": ["QOS-BYPASS", "WEB-BANKING", "QOS-DEFAULT"],
        "QOS-MARKETPLACE": ["WEB-MARKETPLACE", "QOS-BYPASS", "QOS-DEFAULT"],
        "QOS-DOWNLOAD": ["QOS-DOWNLOAD-AUTO", "WEB-DEFAULT", "fallback-link", "best-link", "MANUAL-FALLBACK", "QOS-DEFAULT"],
    }

    for group_name, refs in group_layout.items():
        fixed_refs = group_refs_existing(data, refs)
        if not fixed_refs:
            fixed_refs = base_refs[:]
        actions[group_name] = upsert_group(data, build_select_group(group_name, fixed_refs))
        counts[group_name] = len(fixed_refs)

    rules = data.get("rules") or []
    if not isinstance(rules, list):
        rules = []
    new_rules = build_qos_rules(add_lan=add_lan)
    data["rules"], rule_stats = insert_rules(rules, new_rules, force_match_qos_default=force_match)

    ref_stats = sanitize_group_references(data)
    return {
        "ok": True,
        "actions": actions,
        "group_counts": counts,
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
            errors.append("proxy-group not mapping")
            continue
        name = str(group.get("name") or "")
        gtype = str(group.get("type") or "").strip().lower()
        if gtype not in {"select", "url-test", "fallback", "load-balance"}:
            errors.append(f"unsupported group type: {name} type={gtype}")
        refs = group.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"group empty proxies: {name}")
            continue
        for ref in refs:
            value = str(ref).strip()
            if value == name:
                errors.append(f"self reference: {name}")
            if value not in allowed:
                errors.append(f"unknown group ref: {name} -> {value}")
            if value in DIRECT_REJECT_REFS and gtype != "select":
                errors.append(f"DIRECT/REJECT outside select group: {name} -> {value}")

    for rule in rules:
        text = str(rule).strip()
        if not text or text.startswith("#"):
            continue
        parts = [p.strip() for p in text.split(",")]
        pos = get_rule_target_position(parts)
        if pos is None or pos >= len(parts):
            continue
        target = parts[pos]
        if target in DIRECT_REJECT_REFS:
            errors.append(f"DIRECT/REJECT used as rule target: {text}")
        elif target and target not in allowed:
            errors.append(f"unknown rule target: {text}")
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
        info = add_smart_qos(
            data=data,
            interval=max(60, int(args.interval)),
            tolerance=max(0, int(args.tolerance)),
            max_candidates=max(1, int(args.max_candidates)),
            add_lan=bool(args.add_lan_bypass),
            force_match=bool(args.force_match_qos_default),
        )
        validation = validate_data(data)
        if not validation.get("ok"):
            return {"file": rel, "ok": False, "reason": "validation failed before write", "validation": validation, **info}
        write_yaml(path, data)
        read_yaml(path)
    except Exception as exc:
        return {"file": rel, "ok": False, "reason": f"write failed: {exc}"}
    return {"file": rel, "ok": True, "validation": validation, **info}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add OpenClash-safe Smart QoS policy-routing groups and rules.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default=os.getenv("SMART_QOS_REPORT", REPORT_PATH))
    parser.add_argument("--interval", type=int, default=env_int("SMART_QOS_INTERVAL", 90))
    parser.add_argument("--tolerance", type=int, default=env_int("SMART_QOS_TOLERANCE", 30))
    parser.add_argument("--max-candidates", type=int, default=env_int("SMART_QOS_MAX_CANDIDATES", MAX_CANDIDATES))
    parser.add_argument("--add-lan-bypass", action=argparse.BooleanOptionalAction, default=env_bool("SMART_QOS_ADD_LAN_BYPASS", True))
    parser.add_argument("--force-match-qos-default", action=argparse.BooleanOptionalAction, default=env_bool("SMART_QOS_FORCE_MATCH_DEFAULT", True))
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
        "generated_by": "apply_openclash_smart_qos.py",
        "mode": "smart-qos-policy-routing",
        "scope_note": "OpenClash YAML cannot perform true Linux SQM/CAKE shaping; this patch implements smart policy routing by traffic priority/category.",
        "policy": {
            "direct_reject_policy": "DIRECT/REJECT only inside select proxy-groups; rules target QOS-BYPASS/QOS-BLOCK instead.",
            "qos_groups": sorted(QOS_GROUPS),
            "rule_types": ["DOMAIN-SUFFIX", "IP-CIDR", "MATCH"],
            "openclash_safe": "No rule-providers, no script rules, no Meta-only root options; only select/url-test groups and domain/ip rules.",
            "force_match_to_qos_default": bool(args.force_match_qos_default),
        },
        "settings": {
            "interval": max(60, int(args.interval)),
            "tolerance": max(0, int(args.tolerance)),
            "max_candidates": max(1, int(args.max_candidates)),
            "add_lan_bypass": bool(args.add_lan_bypass),
            "force_match_qos_default": bool(args.force_match_qos_default),
        },
        "results": results,
    }
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Smart-QoS report: {report_path}")
    for item in results:
        if item.get("skipped"):
            continue
        status = "OK" if item.get("ok") else "FAIL"
        stats = item.get("rule_stats") or {}
        print(f"[{status}] {item.get('file')} smart_qos_rules={stats.get('smart_qos_rules_inserted', 0)} total_rules={stats.get('total_rules', 0)}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

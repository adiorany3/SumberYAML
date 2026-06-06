#!/usr/bin/env python3
"""
Apply strict-safe app-aware OpenClash groups and rules.

Purpose:
- Select nodes using app/category-specific health-check URLs instead of one generic ping URL.
- Keep compatibility with older OpenClash/Clash cores: only select/url-test/fallback groups.
- Keep DIRECT/REJECT only inside selector groups, never as direct rule targets.
- Route Google/YouTube/Reddit/LinkedIn/Blibli to special input-link nodes when names match.
- Avoid load-balance, rule-providers, sub-rules, script rules, lazy, timeout, tcp-concurrent, unified-delay.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML is required: {exc}", file=sys.stderr)
    sys.exit(2)

SUPPORTED_PROXY_TYPES = {"vmess", "vless", "trojan"}
DROP_PROXY_TYPES = {"ss", "ssr"}
RISKY_TOP_LEVEL_KEYS = {"tcp-concurrent", "unified-delay"}
RISKY_GROUP_KEYS = {"lazy", "timeout", "strategy"}

DEFAULT_INPUT_FILES = ["input/links.txt", "input.txt", "links.txt"]
DEFAULT_YAML_FILES = [
    "output/fast.yaml",
    "output/lite.yaml",
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/openclash-ready.yaml",
    "output/openclash-lite-ready.yaml",
    "output/manual_only.yaml",
]

APP_KEYWORDS: Mapping[str, Sequence[str]] = {
    "UTAMA": ("utama", "main", "primary", "prioritas", "default"),
    "GOOGLE": ("google", "gmail", "gstatic", "googlevideo", "ytimg"),
    "YOUTUBE": ("youtube", "youtu", "yt", "googlevideo", "ytimg"),
    "REDDIT": ("reddit", "redd.it"),
    "LINKEDIN": ("linkedin", "licdn", "lnkd"),
    "BLIBLI": ("blibli",),
    "BANK": ("bank", "bca", "bri", "bni", "mandiri", "jago", "seabank", "blu", "livin", "brimo"),
    "MARKETPLACE": ("market", "tokopedia", "shopee", "lazada", "bukalapak", "blibli", "olshop"),
    "SOCIAL": ("social", "sosmed", "whatsapp", "telegram", "facebook", "instagram", "twitter", "x.com", "linkedin"),
    "STREAMING": ("stream", "netflix", "disney", "spotify", "twitch", "video"),
    "GAME": ("game", "gaming", "steam", "riot", "pubg", "ml", "roblox"),
    "AI": ("ai", "openai", "chatgpt", "claude", "gemini", "copilot"),
    "WORK": ("work", "github", "gitlab", "docker", "npm", "pypi", "dev"),
}

CHECK_URLS = {
    "AUTO": "https://www.gstatic.com/generate_204",
    "FALLBACK": "https://www.gstatic.com/generate_204",
    "UTAMA": "https://www.gstatic.com/generate_204",
    "GOOGLE": "https://www.gstatic.com/generate_204",
    "YOUTUBE": "https://www.youtube.com/generate_204",
    "REDDIT": "https://www.reddit.com/",
    "LINKEDIN": "https://www.linkedin.com/",
    "BLIBLI": "https://www.blibli.com/",
    "BANK": "https://www.google.com/generate_204",
    "MARKETPLACE": "https://www.tokopedia.com/",
    "SOCIAL": "https://www.linkedin.com/",
    "STREAMING": "https://www.youtube.com/generate_204",
    "GAME": "https://store.steampowered.com/",
    "AI": "https://chatgpt.com/",
    "WORK": "https://github.com/",
    "DOWNLOAD": "https://github.com/",
}

# Rules are intentionally DOMAIN-SUFFIX / IP-CIDR / MATCH only for broad OpenClash compatibility.
APP_RULES: Sequence[str] = [
    # Bypass rules go to BYPASS selector, not DIRECT.
    "IP-CIDR,10.0.0.0/8,BYPASS,no-resolve",
    "IP-CIDR,172.16.0.0/12,BYPASS,no-resolve",
    "IP-CIDR,192.168.0.0/16,BYPASS,no-resolve",
    "IP-CIDR,127.0.0.0/8,BYPASS,no-resolve",
    "IP-CIDR,224.0.0.0/4,BYPASS,no-resolve",
    # Google core.
    "DOMAIN-SUFFIX,google.com,GOOGLE",
    "DOMAIN-SUFFIX,google.co.id,GOOGLE",
    "DOMAIN-SUFFIX,googleapis.com,GOOGLE",
    "DOMAIN-SUFFIX,gstatic.com,GOOGLE",
    "DOMAIN-SUFFIX,googleusercontent.com,GOOGLE",
    "DOMAIN-SUFFIX,ggpht.com,GOOGLE",
    "DOMAIN-SUFFIX,gmail.com,GOOGLE",
    "DOMAIN-SUFFIX,googlemail.com,GOOGLE",
    "DOMAIN-SUFFIX,google-analytics.com,GOOGLE",
    "DOMAIN-SUFFIX,googletagmanager.com,GOOGLE",
    "DOMAIN-SUFFIX,googlesyndication.com,GOOGLE",
    "DOMAIN-SUFFIX,doubleclick.net,GOOGLE",
    "DOMAIN-SUFFIX,googleadservices.com,GOOGLE",
    "DOMAIN-SUFFIX,meet.google.com,GOOGLE",
    # YouTube/video traffic is split so it can use a more relevant URL test.
    "DOMAIN-SUFFIX,youtube.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtu.be,YOUTUBE",
    "DOMAIN-SUFFIX,ytimg.com,YOUTUBE",
    "DOMAIN-SUFFIX,googlevideo.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtubei.googleapis.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtubekids.com,YOUTUBE",
    # App-specific special nodes.
    "DOMAIN-SUFFIX,reddit.com,REDDIT",
    "DOMAIN-SUFFIX,redd.it,REDDIT",
    "DOMAIN-SUFFIX,redditmedia.com,REDDIT",
    "DOMAIN-SUFFIX,redditstatic.com,REDDIT",
    "DOMAIN-SUFFIX,redditinc.com,REDDIT",
    "DOMAIN-SUFFIX,linkedin.com,LINKEDIN",
    "DOMAIN-SUFFIX,linkedin.cn,LINKEDIN",
    "DOMAIN-SUFFIX,licdn.com,LINKEDIN",
    "DOMAIN-SUFFIX,lnkd.in,LINKEDIN",
    "DOMAIN-SUFFIX,blibli.com,BLIBLI",
    "DOMAIN-SUFFIX,blibli.co.id,BLIBLI",
    # Bank/e-wallet: selector group, not direct rule target.
    "DOMAIN-SUFFIX,bca.co.id,BANK",
    "DOMAIN-SUFFIX,klikbca.com,BANK",
    "DOMAIN-SUFFIX,bankmandiri.co.id,BANK",
    "DOMAIN-SUFFIX,livin.mandiri.co.id,BANK",
    "DOMAIN-SUFFIX,bri.co.id,BANK",
    "DOMAIN-SUFFIX,bni.co.id,BANK",
    "DOMAIN-SUFFIX,jenius.com,BANK",
    "DOMAIN-SUFFIX,jago.com,BANK",
    "DOMAIN-SUFFIX,seabank.co.id,BANK",
    "DOMAIN-SUFFIX,blu.id,BANK",
    "DOMAIN-SUFFIX,dana.id,BANK",
    "DOMAIN-SUFFIX,ovo.id,BANK",
    "DOMAIN-SUFFIX,gopay.co.id,BANK",
    "DOMAIN-SUFFIX,linkaja.id,BANK",
    # Marketplace.
    "DOMAIN-SUFFIX,tokopedia.com,MARKETPLACE",
    "DOMAIN-SUFFIX,shopee.co.id,MARKETPLACE",
    "DOMAIN-SUFFIX,shopee.com,MARKETPLACE",
    "DOMAIN-SUFFIX,lazada.co.id,MARKETPLACE",
    "DOMAIN-SUFFIX,bukalapak.com,MARKETPLACE",
    "DOMAIN-SUFFIX,olx.co.id,MARKETPLACE",
    # Social.
    "DOMAIN-SUFFIX,whatsapp.com,SOCIAL",
    "DOMAIN-SUFFIX,whatsapp.net,SOCIAL",
    "DOMAIN-SUFFIX,telegram.org,SOCIAL",
    "DOMAIN-SUFFIX,t.me,SOCIAL",
    "DOMAIN-SUFFIX,facebook.com,SOCIAL",
    "DOMAIN-SUFFIX,fbcdn.net,SOCIAL",
    "DOMAIN-SUFFIX,instagram.com,SOCIAL",
    "DOMAIN-SUFFIX,cdninstagram.com,SOCIAL",
    "DOMAIN-SUFFIX,twitter.com,SOCIAL",
    "DOMAIN-SUFFIX,x.com,SOCIAL",
    "DOMAIN-SUFFIX,t.co,SOCIAL",
    # Streaming.
    "DOMAIN-SUFFIX,netflix.com,STREAMING",
    "DOMAIN-SUFFIX,nflxvideo.net,STREAMING",
    "DOMAIN-SUFFIX,spotify.com,STREAMING",
    "DOMAIN-SUFFIX,twitch.tv,STREAMING",
    "DOMAIN-SUFFIX,disneyplus.com,STREAMING",
    # Game.
    "DOMAIN-SUFFIX,steampowered.com,GAME",
    "DOMAIN-SUFFIX,steamcommunity.com,GAME",
    "DOMAIN-SUFFIX,steamstatic.com,GAME",
    "DOMAIN-SUFFIX,riotgames.com,GAME",
    "DOMAIN-SUFFIX,roblox.com,GAME",
    "DOMAIN-SUFFIX,pubgmobile.com,GAME",
    # AI/work/download.
    "DOMAIN-SUFFIX,openai.com,AI",
    "DOMAIN-SUFFIX,chatgpt.com,AI",
    "DOMAIN-SUFFIX,anthropic.com,AI",
    "DOMAIN-SUFFIX,claude.ai,AI",
    "DOMAIN-SUFFIX,gemini.google.com,AI",
    "DOMAIN-SUFFIX,github.com,WORK",
    "DOMAIN-SUFFIX,githubusercontent.com,WORK",
    "DOMAIN-SUFFIX,gitlab.com,WORK",
    "DOMAIN-SUFFIX,docker.com,WORK",
    "DOMAIN-SUFFIX,npmjs.com,WORK",
    "DOMAIN-SUFFIX,pypi.org,WORK",
    "DOMAIN-SUFFIX,pythonhosted.org,WORK",
    "DOMAIN-SUFFIX,ubuntu.com,DOWNLOAD",
    "DOMAIN-SUFFIX,debian.org,DOWNLOAD",
    "DOMAIN-SUFFIX,microsoft.com,DOWNLOAD",
    "DOMAIN-SUFFIX,windowsupdate.com,DOWNLOAD",
    "DOMAIN-SUFFIX,apple.com,DOWNLOAD",
    # Default must be selector group, not DIRECT.
    "MATCH,PROXY",
]


def b64decode_maybe(value: str) -> str:
    raw = value.strip()
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw.encode()).decode("utf-8", "ignore")
    except Exception:
        try:
            return base64.b64decode(raw.encode()).decode("utf-8", "ignore")
        except Exception:
            return ""


def parse_input_link_name(line: str) -> Tuple[str | None, str | None]:
    line = line.strip()
    if not line or line.startswith("#"):
        return None, None
    if line.startswith("vmess://"):
        payload = line[len("vmess://") :].split("#", 1)[0]
        decoded = b64decode_maybe(payload)
        try:
            obj = json.loads(decoded)
            name = obj.get("ps") or obj.get("name")
            return "vmess", str(name).strip() if name else None
        except Exception:
            frag = line.split("#", 1)[1] if "#" in line else None
            return "vmess", unquote(frag) if frag else None
    if line.startswith("vless://") or line.startswith("trojan://"):
        proto = line.split("://", 1)[0]
        frag = line.split("#", 1)[1] if "#" in line else None
        return proto, unquote(frag).strip() if frag else None
    # Inline YAML object may include name/type.
    if "type:" in line or line.startswith("{"):
        try:
            obj = yaml.safe_load(line)
            if isinstance(obj, dict):
                typ = str(obj.get("type") or "").strip().lower() or None
                name = obj.get("name")
                return typ, str(name).strip() if name else None
        except Exception:
            return None, None
    return None, None


def load_manual_names(root: Path, input_files: Sequence[str]) -> Dict[str, Set[str]]:
    names: Dict[str, Set[str]] = {"all": set(), "vmess": set(), "vless": set(), "trojan": set()}
    for rel in input_files:
        path = root / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            typ, name = parse_input_link_name(line)
            if typ in DROP_PROXY_TYPES:
                continue
            if typ not in SUPPORTED_PROXY_TYPES or not name:
                continue
            names.setdefault(typ, set()).add(name)
            names["all"].add(name)
    return names


def clean_name(value: Any) -> str:
    return str(value or "").strip()


def normalize_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def name_has_keyword(name: str, keywords: Sequence[str]) -> bool:
    hay = normalize_text(name)
    raw = str(name or "").lower()
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if k in raw or k in hay.split():
            return True
    return False


def dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        name = clean_name(item)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def valid_proxy(prox: Any) -> bool:
    if not isinstance(prox, dict):
        return False
    name = clean_name(prox.get("name"))
    typ = clean_name(prox.get("type")).lower()
    server = clean_name(prox.get("server"))
    return bool(name and server and typ in SUPPORTED_PROXY_TYPES)


def clean_proxy(prox: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(prox)
    for key in list(item.keys()):
        if key in {"skip-cert-verify"}:
            continue
        # Keep most proxy keys untouched; only remove keys known to be group/core options, not proxy options.
    return item


def build_candidates(proxies: Sequence[Dict[str, Any]], manual_names: Mapping[str, Set[str]], max_candidates: int) -> Dict[str, List[str]]:
    all_names = [clean_name(p.get("name")) for p in proxies]
    type_by_name = {clean_name(p.get("name")): clean_name(p.get("type")).lower() for p in proxies}

    manual_all = [n for n in all_names if n in manual_names.get("all", set())]
    manual_vmess = [n for n in all_names if n in manual_names.get("vmess", set()) and type_by_name.get(n) == "vmess"]
    if not manual_vmess:
        # Fallback for prior manual-injection names when exact source names no longer survive renaming.
        manual_vmess = [n for n in all_names if type_by_name.get(n) == "vmess" and name_has_keyword(n, ("manual", "input", "link"))]
    if not manual_all:
        manual_all = [n for n in all_names if name_has_keyword(n, ("manual", "input", "link", "utama", "google", "youtube", "reddit", "linkedin", "blibli"))]

    pools: Dict[str, List[str]] = {}
    pools["ALL"] = dedupe_keep_order(all_names)[:max_candidates]
    pools["MANUAL"] = dedupe_keep_order(manual_all)[:max_candidates]
    pools["INPUT-VMESS"] = dedupe_keep_order(manual_vmess)[:max_candidates]

    for group_name, keywords in APP_KEYWORDS.items():
        by_kw = [n for n in all_names if name_has_keyword(n, keywords)]
        by_manual_kw = [n for n in manual_all if name_has_keyword(n, keywords)]
        if group_name in {"BANK", "MARKETPLACE", "SOCIAL"}:
            # User specifically asked marketplace/social/bank to prefer input vmess; keep that priority.
            pool = dedupe_keep_order(by_manual_kw + manual_vmess + by_kw + manual_all + all_names)
        else:
            pool = dedupe_keep_order(by_manual_kw + by_kw + manual_all + all_names)
        pools[group_name] = pool[:max_candidates]

    # YouTube can also use Google-specific nodes if no YouTube-labeled node exists.
    pools["YOUTUBE"] = dedupe_keep_order(pools.get("YOUTUBE", []) + pools.get("GOOGLE", []) + manual_all + all_names)[:max_candidates]
    pools["GOOGLE"] = dedupe_keep_order(pools.get("GOOGLE", []) + pools.get("YOUTUBE", []) + manual_all + all_names)[:max_candidates]
    return pools


def url_test_group(name: str, proxies: Sequence[str], url: str, interval: int, tolerance: int, group_type: str = "url-test") -> Dict[str, Any]:
    items = dedupe_keep_order(proxies)
    return {
        "name": name,
        "type": group_type,
        "proxies": items,
        "url": url,
        "interval": int(interval),
        "tolerance": int(tolerance),
    }


def fallback_group(name: str, proxies: Sequence[str], url: str, interval: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "fallback",
        "proxies": dedupe_keep_order(proxies),
        "url": url,
        "interval": int(interval),
    }


def select_group(name: str, proxies: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": dedupe_keep_order(proxies)}


def build_groups(pools: Mapping[str, List[str]], interval: int, tolerance: int) -> List[Dict[str, Any]]:
    all_candidates = pools.get("ALL", [])
    if not all_candidates:
        return []

    input_vmess = pools.get("INPUT-VMESS") or all_candidates
    utama = pools.get("UTAMA") or pools.get("MANUAL") or all_candidates

    groups: List[Dict[str, Any]] = []
    groups.append(select_group("PROXY", [
        "UTAMA", "GOOGLE", "YOUTUBE", "REDDIT", "LINKEDIN", "BLIBLI",
        "BANK", "MARKETPLACE", "SOCIAL", "STREAMING", "GAME", "AI", "WORK", "DOWNLOAD",
        "AUTO", "FALLBACK", "DEFAULT", "BYPASS", "BLOCK",
    ]))
    groups.append(select_group("UTAMA", utama + ["AUTO", "FALLBACK", "DIRECT"]))
    groups.append(url_test_group("AUTO", all_candidates, CHECK_URLS["AUTO"], interval, tolerance))
    groups.append(fallback_group("FALLBACK", all_candidates, CHECK_URLS["FALLBACK"], interval))
    groups.append(fallback_group("INPUT-VMESS", input_vmess, CHECK_URLS["AUTO"], interval))

    # App-aware groups: each has URL test relevant to the app/service.
    groups.append(url_test_group("GOOGLE", pools.get("GOOGLE") or all_candidates, CHECK_URLS["GOOGLE"], interval, tolerance))
    groups.append(url_test_group("YOUTUBE", pools.get("YOUTUBE") or pools.get("GOOGLE") or all_candidates, CHECK_URLS["YOUTUBE"], interval, tolerance))
    groups.append(url_test_group("REDDIT", pools.get("REDDIT") or utama or all_candidates, CHECK_URLS["REDDIT"], interval, tolerance))
    groups.append(url_test_group("LINKEDIN", pools.get("LINKEDIN") or input_vmess or all_candidates, CHECK_URLS["LINKEDIN"], interval, tolerance))
    groups.append(url_test_group("BLIBLI", pools.get("BLIBLI") or input_vmess or all_candidates, CHECK_URLS["BLIBLI"], interval, tolerance))

    # Sensitive/transactional categories use select so user can override quickly in OpenClash UI.
    groups.append(select_group("BANK", dedupe_keep_order((pools.get("BANK") or []) + input_vmess + ["UTAMA", "AUTO", "FALLBACK", "BYPASS"])))
    groups.append(select_group("MARKETPLACE", dedupe_keep_order((pools.get("MARKETPLACE") or []) + input_vmess + ["UTAMA", "AUTO", "FALLBACK", "BYPASS"])))
    groups.append(select_group("SOCIAL", dedupe_keep_order((pools.get("SOCIAL") or []) + input_vmess + ["LINKEDIN", "UTAMA", "AUTO", "FALLBACK"])))

    groups.append(url_test_group("STREAMING", pools.get("STREAMING") or pools.get("YOUTUBE") or all_candidates, CHECK_URLS["STREAMING"], interval, tolerance))
    groups.append(url_test_group("GAME", pools.get("GAME") or all_candidates, CHECK_URLS["GAME"], interval, tolerance))
    groups.append(url_test_group("AI", pools.get("AI") or all_candidates, CHECK_URLS["AI"], interval, tolerance))
    groups.append(url_test_group("WORK", pools.get("WORK") or all_candidates, CHECK_URLS["WORK"], interval, tolerance))
    groups.append(fallback_group("DOWNLOAD", pools.get("WORK") or all_candidates, CHECK_URLS["DOWNLOAD"], max(interval, 120)))
    groups.append(select_group("DEFAULT", ["UTAMA", "AUTO", "FALLBACK", "DIRECT"]))
    groups.append(select_group("BYPASS", ["DIRECT", "UTAMA", "AUTO", "FALLBACK"]))
    groups.append(select_group("BLOCK", ["REJECT", "DIRECT", "UTAMA", "AUTO"]))

    return groups


def sanitize_rules(rules: Sequence[Any], group_names: Set[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in rules:
        rule = str(raw).strip()
        if not rule or rule.startswith("#"):
            continue
        parts = [p.strip() for p in rule.split(",")]
        if len(parts) < 2:
            continue
        # Last non-option part is normally target. no-resolve is an option.
        target_idx = len(parts) - 1
        if parts[target_idx].lower() == "no-resolve" and target_idx >= 1:
            target_idx -= 1
        target = parts[target_idx]
        if target == "DIRECT":
            parts[target_idx] = "BYPASS"
        elif target == "REJECT":
            parts[target_idx] = "BLOCK"
        elif target not in group_names:
            # Drop rules that point to removed legacy groups/proxies to prevent OpenClash errors.
            continue
        cleaned.append(",".join(parts))
    # Ensure MATCH exists and points to PROXY.
    cleaned = [r for r in cleaned if not r.upper().startswith("MATCH,")]
    cleaned.append("MATCH,PROXY")
    return dedupe_keep_order(cleaned)


def process_config(path: Path, manual_names: Mapping[str, Set[str]], interval: int, tolerance: int, max_candidates: int) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"file": str(path), "status": "error", "error": f"YAML parse failed: {exc}"}
    if not isinstance(data, dict):
        return {"file": str(path), "status": "skip", "reason": "not a mapping"}

    for key in RISKY_TOP_LEVEL_KEYS:
        data.pop(key, None)

    raw_proxies = data.get("proxies") or []
    proxies: List[Dict[str, Any]] = []
    dropped = 0
    duplicates = 0
    seen_names: Set[str] = set()
    for item in raw_proxies:
        if not isinstance(item, dict):
            dropped += 1
            continue
        typ = clean_name(item.get("type")).lower()
        name = clean_name(item.get("name"))
        if typ in DROP_PROXY_TYPES or typ not in SUPPORTED_PROXY_TYPES or not name:
            dropped += 1
            continue
        if name in seen_names:
            duplicates += 1
            continue
        seen_names.add(name)
        proxies.append(clean_proxy(item))

    if not proxies:
        return {"file": str(path), "status": "skip", "reason": "no supported proxies", "dropped": dropped}

    pools = build_candidates(proxies, manual_names, max_candidates=max_candidates)
    groups = build_groups(pools, interval=interval, tolerance=tolerance)
    group_names = {g["name"] for g in groups if isinstance(g, dict) and g.get("name")}

    # Use clean app-aware rules to avoid stale WEB/QOS/TRAFIK targets.
    rules = sanitize_rules(APP_RULES, group_names)

    data["proxies"] = proxies
    data["proxy-groups"] = groups
    data["rules"] = rules

    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

    def count_pool(name: str) -> int:
        return len(pools.get(name, []))

    return {
        "file": str(path),
        "status": "updated",
        "proxies": len(proxies),
        "groups": len(groups),
        "rules": len(rules),
        "dropped": dropped,
        "duplicates": duplicates,
        "manual_names": len(manual_names.get("all", set())),
        "input_vmess_candidates": count_pool("INPUT-VMESS"),
        "utama_candidates": count_pool("UTAMA"),
        "google_candidates": count_pool("GOOGLE"),
        "youtube_candidates": count_pool("YOUTUBE"),
        "reddit_candidates": count_pool("REDDIT"),
        "linkedin_candidates": count_pool("LINKEDIN"),
        "blibli_candidates": count_pool("BLIBLI"),
    }


def create_manual_only(root: Path, source_yaml: Path, manual_names: Mapping[str, Set[str]], interval: int, tolerance: int, max_candidates: int) -> Dict[str, Any]:
    target = root / "output/manual_only.yaml"
    if not source_yaml.exists():
        return {"file": str(target), "status": "skip", "reason": "source yaml missing"}
    try:
        data = yaml.safe_load(source_yaml.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"file": str(target), "status": "error", "error": str(exc)}
    if not isinstance(data, dict):
        return {"file": str(target), "status": "skip", "reason": "source not mapping"}
    proxies = [p for p in data.get("proxies") or [] if isinstance(p, dict)]
    manual_set = manual_names.get("all", set())
    manual_proxies = [p for p in proxies if clean_name(p.get("name")) in manual_set]
    if not manual_proxies:
        # If exact names were lost, keep vmess/vless/trojan that look manual/input.
        manual_proxies = [p for p in proxies if name_has_keyword(clean_name(p.get("name")), ("manual", "input", "link", "utama", "google", "reddit", "linkedin", "blibli"))]
    if not manual_proxies:
        return {"file": str(target), "status": "skip", "reason": "no manual proxies found"}
    data["proxies"] = manual_proxies
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return process_config(target, manual_names, interval=interval, tolerance=tolerance, max_candidates=max_candidates)


def iter_yaml_files(root: Path, explicit: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    for rel in explicit:
        path = root / rel
        if path.exists() and path.is_file():
            paths.append(path)
    # Add any top-level output YAML not explicitly listed.
    output_dir = root / "output"
    if output_dir.exists():
        for path in sorted(output_dir.glob("*.yaml")):
            if path not in paths:
                paths.append(path)
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply strict-safe app-aware OpenClash routing groups.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--input-files", default=os.getenv("MANUAL_INPUT_FILES", ",".join(DEFAULT_INPUT_FILES)))
    parser.add_argument("--interval", type=int, default=int(os.getenv("APP_AWARE_INTERVAL", os.getenv("STRICT_SAFE_INTERVAL", "90"))))
    parser.add_argument("--tolerance", type=int, default=int(os.getenv("APP_AWARE_TOLERANCE", os.getenv("STRICT_SAFE_TOLERANCE", "40"))))
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("APP_AWARE_MAX_CANDIDATES", "20")))
    parser.add_argument("--yaml-files", default=",".join(DEFAULT_YAML_FILES))
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    input_files = [x.strip() for x in args.input_files.split(",") if x.strip()]
    yaml_files = [x.strip() for x in args.yaml_files.split(",") if x.strip()]

    manual_names = load_manual_names(root, input_files)
    source_for_manual = root / "output/fast.yaml"
    manual_result = create_manual_only(root, source_for_manual, manual_names, args.interval, args.tolerance, args.max_candidates)

    results: List[Dict[str, Any]] = []
    for path in iter_yaml_files(root, yaml_files):
        results.append(process_config(path, manual_names, args.interval, args.tolerance, args.max_candidates))

    report = {
        "status": "ok",
        "policy": "app-aware-url-test-strict-safe",
        "direct_reject_policy": "DIRECT and REJECT may appear only inside selector groups",
        "unsupported_protocols_dropped": sorted(DROP_PROXY_TYPES),
        "supported_protocols": sorted(SUPPORTED_PROXY_TYPES),
        "manual_input_files": input_files,
        "manual_names_count": {k: len(v) for k, v in manual_names.items()},
        "manual_only": manual_result,
        "results": results,
        "check_urls": CHECK_URLS,
    }
    out_dir = root / "output/Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "app_aware_groups_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    updated = [r for r in results if r.get("status") == "updated"]
    if not updated:
        print("ERROR: no YAML files updated", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

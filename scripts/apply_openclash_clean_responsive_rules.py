#!/usr/bin/env python3
"""
Clean responsive OpenClash rules and simplify proxy groups.

Purpose:
- reduce confusing duplicate WEB-* / QOS-* groups into a compact selector tree;
- keep DIRECT and REJECT only inside selector groups, never as direct rule targets;
- route marketplace, social media including LinkedIn, and banking to INPUT-VMESS-LB;
- build INPUT-VMESS-LB from VMess nodes found in input/links.txt, input.txt, links.txt;
- build REDDIT-INPUT from input nodes whose names contain "reddit" plus existing reddit-named nodes;
- keep ss/ssr out of the output for OpenClash-safe compatibility.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import yaml

CHECK_URL = "http://www.gstatic.com/generate_204"
REPORT_PATH = "output/Validation/clean_responsive_rules_report.json"
DEFAULT_INPUT_FILES = ["input/links.txt", "input.txt", "links.txt"]
DEFAULT_OUTPUT_FILES = [
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/general.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/openclash-ready.yaml",
    "output/openclash-lite-ready.yaml",
    "output/manual_only.yaml",
    "output/Performance/performance-lite.yaml",
]

SPECIAL_REFS = {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
DROP_TYPES = {"ss", "ssr"}

# Compact, user-facing group names. These are intentionally fewer than the
# previous WEB-* and QOS-* group families so OpenClash UI is easier to read.
GROUP_PRIMARY = "PILIHAN-UTAMA"
GROUP_AUTO = "AUTO-RESPONSIF"
GROUP_FALLBACK = "FALLBACK-RESPONSIF"
GROUP_INPUT_VMESS_LB = "INPUT-VMESS-LB"
GROUP_REDDIT = "REDDIT-INPUT"
GROUP_SOCIAL = "TRAFIK-SOSMED"
GROUP_BANK_MARKET = "TRAFIK-BANK-MARKET"
GROUP_STREAMING = "TRAFIK-STREAMING"
GROUP_GAMING = "TRAFIK-GAME"
GROUP_AI = "TRAFIK-AI"
GROUP_WORK = "TRAFIK-KERJA"
GROUP_DOWNLOAD = "TRAFIK-DOWNLOAD"
GROUP_DEFAULT = "TRAFIK-UMUM"
GROUP_BYPASS = "BYPASS"
GROUP_BLOCK = "BLOKIR"

SIMPLIFIED_GROUPS = {
    GROUP_PRIMARY,
    GROUP_AUTO,
    GROUP_FALLBACK,
    GROUP_INPUT_VMESS_LB,
    GROUP_REDDIT,
    GROUP_SOCIAL,
    GROUP_BANK_MARKET,
    GROUP_STREAMING,
    GROUP_GAMING,
    GROUP_AI,
    GROUP_WORK,
    GROUP_DOWNLOAD,
    GROUP_DEFAULT,
    GROUP_BYPASS,
    GROUP_BLOCK,
}

LEGACY_EXACT_GROUPS = {
    "MANUAL-LINK",
    "MANUAL-FALLBACK",
    "MANUAL-BEST",
    "SMART-BEST",
    "SAT-SET",
    "ANTI-BENGONG",
    "BEST-STABLE",
    "fallback-link",
    "best-link",
    "QOS-REALTIME",
    "QOS-GAMING",
    "QOS-STREAMING",
    "QOS-AI",
    "QOS-SOCIAL",
    "QOS-WORK",
    "QOS-BANKING",
    "QOS-MARKETPLACE",
    "QOS-DOWNLOAD",
    "QOS-BYPASS",
    "QOS-BLOCK",
    "QOS-DEFAULT",
    "WEB-AI",
    "WEB-STREAMING",
    "WEB-SOCIAL",
    "WEB-GAMING",
    "WEB-BANKING",
    "WEB-MARKETPLACE",
    "WEB-DEV",
    "WEB-GOOGLE",
    "WEB-DEFAULT",
    "WEB-BYPASS",
    "WEB-BLOCK",
}

LEGACY_PREFIXES = ("WEB-", "QOS-")
LEGACY_TARGET_MAP = {
    "WEB-SOCIAL": GROUP_SOCIAL,
    "QOS-SOCIAL": GROUP_SOCIAL,
    "WEB-BANKING": GROUP_BANK_MARKET,
    "QOS-BANKING": GROUP_BANK_MARKET,
    "WEB-MARKETPLACE": GROUP_BANK_MARKET,
    "QOS-MARKETPLACE": GROUP_BANK_MARKET,
    "WEB-STREAMING": GROUP_STREAMING,
    "QOS-STREAMING": GROUP_STREAMING,
    "WEB-GAMING": GROUP_GAMING,
    "QOS-GAMING": GROUP_GAMING,
    "WEB-AI": GROUP_AI,
    "QOS-AI": GROUP_AI,
    "WEB-DEV": GROUP_WORK,
    "QOS-WORK": GROUP_WORK,
    "WEB-GOOGLE": GROUP_WORK,
    "QOS-DOWNLOAD": GROUP_DOWNLOAD,
    "WEB-DEFAULT": GROUP_DEFAULT,
    "QOS-DEFAULT": GROUP_DEFAULT,
    "WEB-BYPASS": GROUP_BYPASS,
    "QOS-BYPASS": GROUP_BYPASS,
    "WEB-BLOCK": GROUP_BLOCK,
    "QOS-BLOCK": GROUP_BLOCK,
    "DIRECT": GROUP_BYPASS,
    "REJECT": GROUP_BLOCK,
}

MANAGED_TARGETS = set(LEGACY_TARGET_MAP) | SIMPLIFIED_GROUPS | LEGACY_EXACT_GROUPS

DOMAIN_RULES: Dict[str, List[str]] = {
    GROUP_REDDIT: [
        "reddit.com",
        "redd.it",
        "redditmedia.com",
        "redditstatic.com",
        "redditinc.com",
    ],
    GROUP_BANK_MARKET: [
        # Indonesian banking / e-wallets / payments
        "bca.co.id",
        "klikbca.com",
        "mybca.bca.co.id",
        "bankmandiri.co.id",
        "livin.mandiri.co.id",
        "bri.co.id",
        "brimo.bri.co.id",
        "bni.co.id",
        "btn.co.id",
        "cimbniaga.co.id",
        "danamon.co.id",
        "permatabank.com",
        "ocbc.id",
        "jenius.com",
        "blu.id",
        "seabank.co.id",
        "bankjago.com",
        "ovo.id",
        "gopay.co.id",
        "dana.id",
        "linkaja.id",
        "shopeepay.co.id",
        "paypal.com",
        # marketplace / transport / ticketing
        "tokopedia.com",
        "shopee.co.id",
        "shopee.com",
        "lazada.co.id",
        "bukalapak.com",
        "blibli.com",
        "tiket.com",
        "traveloka.com",
        "gojek.com",
        "gopay.co.id",
        "grab.com",
        "maxim.com",
    ],
    GROUP_SOCIAL: [
        "linkedin.com",
        "licdn.com",
        "lnkd.in",
        "linkedin.cn",
        "whatsapp.com",
        "whatsapp.net",
        "telegram.org",
        "t.me",
        "facebook.com",
        "fbcdn.net",
        "messenger.com",
        "instagram.com",
        "cdninstagram.com",
        "threads.net",
        "twitter.com",
        "x.com",
        "twimg.com",
        "discord.com",
        "discord.gg",
        "discordapp.com",
        "tiktok.com",
        "tiktokv.com",
        "tiktokcdn.com",
        "byteoversea.com",
    ],
    GROUP_AI: [
        "openai.com",
        "chatgpt.com",
        "oaistatic.com",
        "oaiusercontent.com",
        "anthropic.com",
        "claude.ai",
        "perplexity.ai",
        "gemini.google.com",
        "ai.google.dev",
        "makersuite.google.com",
        "copilot.microsoft.com",
        "huggingface.co",
    ],
    GROUP_STREAMING: [
        "youtube.com",
        "youtu.be",
        "googlevideo.com",
        "ytimg.com",
        "netflix.com",
        "nflxvideo.net",
        "nflximg.net",
        "nflxext.com",
        "disneyplus.com",
        "hotstar.com",
        "max.com",
        "hbomax.com",
        "spotify.com",
        "scdn.co",
        "twitch.tv",
        "ttvnw.net",
        "vidio.com",
        "viu.com",
        "iq.com",
        "primevideo.com",
        "amazonvideo.com",
    ],
    GROUP_GAMING: [
        "steampowered.com",
        "steamcommunity.com",
        "steamstatic.com",
        "epicgames.com",
        "unrealengine.com",
        "riotgames.com",
        "valorant.com",
        "roblox.com",
        "garena.com",
        "mobilelegends.com",
        "m.mobilelegends.com",
        "moonton.com",
        "pubgmobile.com",
        "krafton.com",
        "hoyoverse.com",
        "genshinimpact.com",
        "zenlesszonezero.com",
        "battle.net",
        "blizzard.com",
    ],
    GROUP_WORK: [
        "github.com",
        "githubusercontent.com",
        "githubassets.com",
        "github.io",
        "gitlab.com",
        "npmjs.com",
        "nodejs.org",
        "pypi.org",
        "pythonhosted.org",
        "docker.com",
        "docker.io",
        "ghcr.io",
        "cloudflare.com",
        "vercel.com",
        "netlify.app",
        "stackoverflow.com",
        "stackexchange.com",
        "google.com",
        "google.co.id",
        "gstatic.com",
        "googleapis.com",
        "googleusercontent.com",
        "ggpht.com",
    ],
    GROUP_DOWNLOAD: [
        "ubuntu.com",
        "debian.org",
        "archive.ubuntu.com",
        "security.ubuntu.com",
        "microsoft.com",
        "windowsupdate.com",
        "windows.com",
        "apple.com",
        "icloud.com",
        "dropbox.com",
        "mega.nz",
        "mediafire.com",
        "drive.google.com",
    ],
}

LAN_RULES = [
    f"DOMAIN-SUFFIX,local,{GROUP_BYPASS}",
    f"DOMAIN-SUFFIX,lan,{GROUP_BYPASS}",
    f"IP-CIDR,127.0.0.0/8,{GROUP_BYPASS},no-resolve",
    f"IP-CIDR,10.0.0.0/8,{GROUP_BYPASS},no-resolve",
    f"IP-CIDR,172.16.0.0/12,{GROUP_BYPASS},no-resolve",
    f"IP-CIDR,192.168.0.0/16,{GROUP_BYPASS},no-resolve",
    f"IP-CIDR,169.254.0.0/16,{GROUP_BYPASS},no-resolve",
]

URI_PATTERN = re.compile(r"(?:vmess|vless|trojan)://[^\s]+", re.IGNORECASE)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def split_env_list(name: str, default: Sequence[str]) -> List[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


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


def b64decode_text(raw: str) -> str:
    text = raw.strip()
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode((text + pad).encode()).decode("utf-8", "replace")
    except Exception:
        return base64.b64decode((text + pad).encode()).decode("utf-8", "replace")


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def clean_node_name(name: str, fallback: str) -> str:
    text = unquote(str(name or "")).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120] if text else fallback


def q_first(query: Dict[str, List[str]], *names: str) -> str:
    for name in names:
        vals = query.get(name)
        if vals and vals[0] is not None:
            return str(vals[0])
    return ""


def is_cdn_compatible(proxy: Dict[str, Any]) -> bool:
    ptype = str(proxy.get("type") or "").lower()
    network = str(proxy.get("network") or "tcp").lower()
    security = str(proxy.get("flow") or proxy.get("security") or "").lower()
    if ptype not in {"vmess", "vless", "trojan"}:
        return False
    if "reality" in security:
        return False
    return network in {"ws", "grpc", "h2", "http"}


def maybe_override_server(proxy: Dict[str, Any]) -> Dict[str, Any]:
    override = os.getenv("MANUAL_SERVER_OVERRIDE", "").strip()
    mode = os.getenv("MANUAL_SERVER_OVERRIDE_TYPES", "cdn-compatible").strip().lower()
    if not override:
        return proxy
    out = copy.deepcopy(proxy)
    if mode in {"all", "true", "1"} or (mode in {"cdn-compatible", "cdn", "safe"} and is_cdn_compatible(out)):
        out["server"] = override
    return out


def parse_vmess(uri: str, index: int) -> Optional[Dict[str, Any]]:
    payload = uri.split("vmess://", 1)[1]
    try:
        obj = json.loads(b64decode_text(payload))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    name = clean_node_name(obj.get("ps") or obj.get("name") or obj.get("remarks") or "", f"INPUT-VMESS-{index:03d}")
    server = str(obj.get("add") or obj.get("server") or "").strip()
    port = safe_int(obj.get("port"), 0)
    uuid = str(obj.get("id") or obj.get("uuid") or "").strip()
    if not server or not port or not uuid:
        return None
    network = str(obj.get("net") or obj.get("network") or "tcp").lower().strip() or "tcp"
    tls_raw = str(obj.get("tls") or "").lower()
    proxy: Dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": safe_int(obj.get("aid") or obj.get("alterId"), 0),
        "cipher": str(obj.get("scy") or obj.get("cipher") or "auto"),
        "network": network,
        "udp": True,
    }
    if tls_raw in {"tls", "true", "1"}:
        proxy["tls"] = True
    sni = str(obj.get("sni") or obj.get("servername") or obj.get("host") or "").strip()
    if sni:
        proxy["servername"] = sni
    if network == "ws":
        path = str(obj.get("path") or "/").strip() or "/"
        host = str(obj.get("host") or sni or "").strip()
        ws_opts: Dict[str, Any] = {"path": path}
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif network == "grpc":
        service = str(obj.get("path") or obj.get("serviceName") or "").strip()
        if service:
            proxy["grpc-opts"] = {"grpc-service-name": service}
    return maybe_override_server(proxy)


def parse_vless_or_trojan(uri: str, index: int) -> Optional[Dict[str, Any]]:
    try:
        parsed = urlparse(uri)
    except Exception:
        return None
    ptype = parsed.scheme.lower()
    if ptype not in {"vless", "trojan"}:
        return None
    name = clean_node_name(unquote(parsed.fragment or ""), f"INPUT-{ptype.upper()}-{index:03d}")
    server = str(parsed.hostname or "").strip()
    port = safe_int(parsed.port, 0)
    credential = unquote(parsed.username or "").strip()
    if not server or not port or not credential:
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    network = q_first(query, "type", "network", "net") or "tcp"
    security = q_first(query, "security")
    proxy: Dict[str, Any] = {
        "name": name,
        "type": ptype,
        "server": server,
        "port": port,
        "network": network,
        "udp": True,
    }
    if ptype == "vless":
        proxy["uuid"] = credential
        if security:
            proxy["security"] = security
    else:
        proxy["password"] = credential
    sni = q_first(query, "sni", "servername", "peer")
    if sni:
        proxy["servername"] = sni
        if ptype == "trojan":
            proxy["sni"] = sni
    if q_first(query, "security") == "tls" or q_first(query, "tls") in {"1", "true", "tls"}:
        proxy["tls"] = True
    if network == "ws":
        path = q_first(query, "path") or "/"
        host = q_first(query, "host") or sni
        ws_opts: Dict[str, Any] = {"path": path}
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif network == "grpc":
        service = q_first(query, "serviceName", "service", "grpc-service-name")
        if service:
            proxy["grpc-opts"] = {"grpc-service-name": service}
    return maybe_override_server(proxy)


def parse_proxy_uri(uri: str, index: int) -> Optional[Dict[str, Any]]:
    low = uri.lower()
    if low.startswith("vmess://"):
        return parse_vmess(uri, index)
    if low.startswith("vless://") or low.startswith("trojan://"):
        return parse_vless_or_trojan(uri, index)
    return None


def read_input_proxies(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    files = split_env_list("MANUAL_INPUT_FILES", DEFAULT_INPUT_FILES)
    proxies: List[Dict[str, Any]] = []
    stats = {"files_checked": [], "uri_count": 0, "parsed_count": 0, "skipped_count": 0}
    index = 0
    for rel in files:
        path = root / rel
        stats["files_checked"].append(str(rel))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in URI_PATTERN.finditer(text):
            index += 1
            stats["uri_count"] += 1
            proxy = parse_proxy_uri(match.group(0), index)
            if proxy and str(proxy.get("type", "")).lower() not in DROP_TYPES:
                proxy["_input_source"] = rel
                proxy["_input_index"] = index
                proxies.append(proxy)
                stats["parsed_count"] += 1
            else:
                stats["skipped_count"] += 1
    return proxies, stats


def read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120),
        encoding="utf-8",
    )


def strip_private_fields(proxy: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in proxy.items() if not str(k).startswith("_")}


def get_proxies(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    proxies = data.get("proxies")
    if not isinstance(proxies, list):
        data["proxies"] = []
        return data["proxies"]
    cleaned: List[Dict[str, Any]] = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        if not proxy.get("name"):
            continue
        if str(proxy.get("type", "")).lower() in DROP_TYPES:
            continue
        cleaned.append(proxy)
    data["proxies"] = cleaned
    return cleaned


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


def proxy_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(str(p.get("name")) for p in get_proxies(data) if p.get("name"))


def proxy_name_to_type(data: Dict[str, Any]) -> Dict[str, str]:
    return {str(p.get("name")): str(p.get("type") or "").lower() for p in get_proxies(data) if p.get("name")}


def ensure_unique_proxy_names(proxies: List[Dict[str, Any]]) -> None:
    seen: Dict[str, int] = {}
    for proxy in proxies:
        base = str(proxy.get("name") or "NODE").strip() or "NODE"
        count = seen.get(base, 0)
        if count:
            proxy["name"] = f"{base} #{count + 1}"
        seen[base] = count + 1


def add_input_proxies_to_data(data: Dict[str, Any], input_proxies: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    proxies = get_proxies(data)
    ensure_unique_proxy_names(proxies)
    existing = {str(p.get("name")) for p in proxies if p.get("name")}
    added = 0
    for proxy in input_proxies:
        name = str(proxy.get("name") or "").strip()
        if not name or name in existing:
            continue
        clean = strip_private_fields(proxy)
        proxies.append(clean)
        existing.add(name)
        added += 1
    return {"input_proxies_added": added}


def is_legacy_group(name: str) -> bool:
    if name in LEGACY_EXACT_GROUPS:
        return True
    return any(name.startswith(prefix) for prefix in LEGACY_PREFIXES)


def clean_text_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def name_has_keyword(name: str, keywords: Sequence[str]) -> bool:
    clean = f" {clean_text_for_match(name)} "
    raw = str(name or "").lower()
    for keyword in keywords:
        key = str(keyword).strip().lower()
        if not key:
            continue
        if key in raw or f" {key} " in clean:
            return True
    return False


def select_by_keywords(names: Sequence[str], keywords: Sequence[str], limit: int) -> List[str]:
    return unique_keep_order([name for name in names if name_has_keyword(name, keywords)])[:limit]


def select_responsive_candidates(data: Dict[str, Any], manual_vmess: Sequence[str], reddit_nodes: Sequence[str], limit: int) -> List[str]:
    names = proxy_names(data)
    keywords = ["stable", "best", "fast", "id", "indo", "sg", "singapore", "premium", "low", "ping"]
    kw = select_by_keywords(names, keywords, limit)
    return unique_keep_order(list(manual_vmess) + list(reddit_nodes) + kw + names)[:limit]


def existing_refs(data: Dict[str, Any], refs: Sequence[str], groups: Optional[Sequence[Dict[str, Any]]] = None) -> List[str]:
    pnames = set(proxy_names(data))
    gnames = {str(g.get("name")) for g in (groups if groups is not None else get_groups(data)) if isinstance(g, dict) and g.get("name")}
    allowed = pnames | gnames | SPECIAL_REFS
    return [ref for ref in unique_keep_order(refs) if ref in allowed]


def proxy_only_refs(data: Dict[str, Any], refs: Sequence[str]) -> List[str]:
    pnames = set(proxy_names(data))
    return [ref for ref in unique_keep_order(refs) if ref in pnames]


def make_select(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": unique_keep_order(refs)}


def make_url_test(name: str, refs: Sequence[str], interval: int, tolerance: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": interval,
        "tolerance": tolerance,
    }


def make_fallback(name: str, refs: Sequence[str], interval: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "fallback",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": interval,
    }


def make_load_balance(name: str, refs: Sequence[str], interval: int) -> Dict[str, Any]:
    # No strategy key by default for OpenClash compatibility. Users can add it
    # via env INPUT_VMESS_LB_STRATEGY when their core supports it.
    group: Dict[str, Any] = {
        "name": name,
        "type": "load-balance",
        "proxies": unique_keep_order(refs),
        "url": CHECK_URL,
        "interval": interval,
    }
    strategy = os.getenv("INPUT_VMESS_LB_STRATEGY", "").strip()
    if strategy:
        group["strategy"] = strategy
    return group


def build_groups(data: Dict[str, Any], input_proxies: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    interval = env_int("CLEAN_RULE_INTERVAL", env_int("SMART_QOS_INTERVAL", 60))
    tolerance = env_int("CLEAN_RULE_TOLERANCE", env_int("SMART_QOS_TOLERANCE", 30))
    max_candidates = env_int("CLEAN_RULE_MAX_CANDIDATES", 24)
    lb_interval = env_int("INPUT_VMESS_LB_INTERVAL", 60)

    names = proxy_names(data)
    type_map = proxy_name_to_type(data)
    input_name_set = {str(p.get("name")) for p in input_proxies if p.get("name")}
    input_vmess = [name for name in names if name in input_name_set and type_map.get(name) == "vmess"]
    if not input_vmess:
        # Fallback: preserve previous generated manual/input VMess names.
        input_vmess = [
            name for name in names
            if type_map.get(name) == "vmess" and name_has_keyword(name, ["manual", "input", "trusted", "link"])
        ]
    reddit_from_input = [
        str(p.get("name"))
        for p in input_proxies
        if p.get("name") and "reddit" in str(p.get("name")).lower()
    ]
    reddit_from_output = [name for name in names if "reddit" in name.lower()]
    reddit_nodes = proxy_only_refs(data, unique_keep_order(reddit_from_input + reddit_from_output))

    responsive = proxy_only_refs(data, select_responsive_candidates(data, input_vmess, reddit_nodes, max_candidates))
    if not responsive:
        responsive = proxy_only_refs(data, names[:max_candidates])

    # Do not build url-test/fallback/load-balance without real proxy nodes.
    auto_group = make_url_test(GROUP_AUTO, responsive, interval, tolerance) if responsive else make_select(GROUP_AUTO, ["DIRECT"])
    fallback_group = make_fallback(GROUP_FALLBACK, responsive, interval) if responsive else make_select(GROUP_FALLBACK, [GROUP_AUTO, "DIRECT"])
    if input_vmess:
        input_lb_group = make_load_balance(GROUP_INPUT_VMESS_LB, proxy_only_refs(data, input_vmess), lb_interval)
    else:
        input_lb_group = make_select(GROUP_INPUT_VMESS_LB, [GROUP_AUTO, GROUP_FALLBACK, "DIRECT"])

    reddit_refs = unique_keep_order(reddit_nodes + [GROUP_INPUT_VMESS_LB, GROUP_AUTO, GROUP_FALLBACK, "DIRECT"])
    reddit_group = make_select(GROUP_REDDIT, reddit_refs)

    bank_market_refs = [GROUP_INPUT_VMESS_LB, GROUP_AUTO, GROUP_FALLBACK, "DIRECT"]
    social_refs = [GROUP_INPUT_VMESS_LB, GROUP_AUTO, GROUP_FALLBACK, GROUP_REDDIT, "DIRECT"]
    default_refs = [GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, "DIRECT"]

    primary_refs = [
        GROUP_AUTO,
        GROUP_FALLBACK,
        GROUP_INPUT_VMESS_LB,
        GROUP_REDDIT,
        GROUP_BANK_MARKET,
        GROUP_SOCIAL,
        GROUP_STREAMING,
        GROUP_GAMING,
        GROUP_AI,
        GROUP_WORK,
        GROUP_DOWNLOAD,
        GROUP_DEFAULT,
        GROUP_BYPASS,
        GROUP_BLOCK,
        "DIRECT",
    ]

    new_groups: List[Dict[str, Any]] = [
        make_select(GROUP_PRIMARY, primary_refs),
        make_select("PROXY", [GROUP_PRIMARY, GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, GROUP_DEFAULT, "DIRECT"]),
        auto_group,
        fallback_group,
        input_lb_group,
        reddit_group,
        make_select(GROUP_BANK_MARKET, bank_market_refs),
        make_select(GROUP_SOCIAL, social_refs),
        make_select(GROUP_STREAMING, [GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, "DIRECT"]),
        make_select(GROUP_GAMING, [GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, "DIRECT"]),
        make_select(GROUP_AI, [GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, "DIRECT"]),
        make_select(GROUP_WORK, [GROUP_AUTO, GROUP_FALLBACK, GROUP_INPUT_VMESS_LB, "DIRECT"]),
        make_select(GROUP_DOWNLOAD, [GROUP_FALLBACK, GROUP_AUTO, GROUP_INPUT_VMESS_LB, "DIRECT"]),
        make_select(GROUP_DEFAULT, default_refs),
        make_select(GROUP_BYPASS, ["DIRECT", GROUP_DEFAULT, GROUP_AUTO]),
        make_select(GROUP_BLOCK, ["REJECT", GROUP_BYPASS, GROUP_DEFAULT]),
    ]

    kept_groups: List[Dict[str, Any]] = []
    removed: List[str] = []
    for group in get_groups(data):
        name = str(group.get("name") or "")
        if name == "PROXY" or name in SIMPLIFIED_GROUPS or is_legacy_group(name):
            removed.append(name)
            continue
        kept_groups.append(group)

    # Place simplified groups first for a cleaner OpenClash UI.
    groups = new_groups + kept_groups
    group_names = {str(g.get("name")) for g in groups if g.get("name")}
    proxy_name_set = set(proxy_names(data))
    allowed = proxy_name_set | group_names | SPECIAL_REFS

    for group in groups:
        refs = []
        for ref in group.get("proxies") or []:
            ref_text = str(ref).strip()
            ref_text = LEGACY_TARGET_MAP.get(ref_text, ref_text)
            if ref_text == str(group.get("name")):
                continue
            if ref_text in allowed:
                refs.append(ref_text)
        group["proxies"] = unique_keep_order(refs)
        # selector groups may intentionally contain DIRECT/REJECT; automatic
        # test groups must contain proxy nodes only.
        if group.get("type") in {"url-test", "fallback", "load-balance"}:
            group["proxies"] = proxy_only_refs(data, group.get("proxies") or [])
            if not group["proxies"]:
                group["type"] = "select"
                group["proxies"] = [GROUP_DEFAULT] if group.get("name") != GROUP_DEFAULT else ["DIRECT"]
        for risky in ("lazy", "timeout"):
            group.pop(risky, None)

    stats = {
        "removed_legacy_groups": unique_keep_order(removed),
        "input_vmess_nodes": input_vmess,
        "reddit_nodes": reddit_nodes,
        "responsive_candidates": responsive,
    }
    return groups, stats


def rule_target(rule: str) -> Optional[str]:
    parts = [p.strip() for p in str(rule).split(",")]
    if not parts:
        return None
    kind = parts[0].upper()
    if kind == "MATCH" and len(parts) >= 2:
        return parts[1]
    if len(parts) >= 3:
        return parts[2]
    return None


def set_rule_target(rule: str, target: str) -> str:
    parts = [p.strip() for p in str(rule).split(")")]
    # Never used; keep a separate robust implementation below.
    return rule


def retarget_rule(rule: str) -> Tuple[str, Optional[str]]:
    text = str(rule or "").strip()
    if not text or text.startswith("#"):
        return text, None
    parts = [part.strip() for part in text.split(",")]
    if not parts:
        return text, None
    target_pos: Optional[int] = None
    if parts[0].upper() == "MATCH" and len(parts) >= 2:
        target_pos = 1
    elif len(parts) >= 3:
        target_pos = 2
    if target_pos is None or target_pos >= len(parts):
        return text, None
    old = parts[target_pos]
    new = LEGACY_TARGET_MAP.get(old.upper(), LEGACY_TARGET_MAP.get(old, old))
    if new != old:
        parts[target_pos] = new
        return ",".join(parts), old
    return text, None


def is_managed_rule(rule: str) -> bool:
    target = rule_target(rule)
    if not target:
        return False
    target_upper = target.upper()
    if target in MANAGED_TARGETS or target_upper in {"DIRECT", "REJECT"}:
        return True
    if any(target.startswith(prefix) for prefix in LEGACY_PREFIXES):
        return True
    return False


def build_clean_rules(existing_rules: Sequence[Any]) -> Tuple[List[str], Dict[str, Any]]:
    clean_custom: List[str] = []
    removed_managed = 0
    retargeted_direct_reject = 0
    seen: Set[str] = set()

    for item in existing_rules:
        text = str(item or "").strip()
        if not text:
            continue
        retargeted, old = retarget_rule(text)
        if old in {"DIRECT", "REJECT"}:
            retargeted_direct_reject += 1
        if is_managed_rule(retargeted):
            removed_managed += 1
            continue
        if retargeted.upper().startswith("MATCH,"):
            # This patch owns the final MATCH rule to keep routing predictable.
            removed_managed += 1
            continue
        if retargeted not in seen:
            clean_custom.append(retargeted)
            seen.add(retargeted)

    managed_rules: List[str] = []
    managed_rules.extend(LAN_RULES)
    for group, domains in DOMAIN_RULES.items():
        for domain in domains:
            managed_rules.append(f"DOMAIN-SUFFIX,{domain},{group}")
    managed_rules.append(f"MATCH,{GROUP_DEFAULT}")

    final_rules = unique_keep_order(managed_rules[:-1] + clean_custom + [managed_rules[-1]])
    stats = {
        "removed_old_managed_rules": removed_managed,
        "retargeted_direct_reject_rules": retargeted_direct_reject,
        "managed_rules_added": len(managed_rules),
        "final_rule_count": len(final_rules),
    }
    return final_rules, stats


def validate_data(data: Dict[str, Any], path: Path) -> List[str]:
    errors: List[str] = []
    proxies = get_proxies(data)
    groups = get_groups(data)
    pnames = {str(p.get("name")) for p in proxies if p.get("name")}
    gnames = {str(g.get("name")) for g in groups if g.get("name")}
    allowed = pnames | gnames | SPECIAL_REFS

    for proxy in proxies:
        ptype = str(proxy.get("type") or "").lower()
        if ptype in DROP_TYPES:
            errors.append(f"{path}: blocked proxy type still exists: {proxy.get('name')} ({ptype})")
    for group in groups:
        gname = str(group.get("name") or "")
        gtype = str(group.get("type") or "")
        if not group.get("proxies"):
            errors.append(f"{path}: group has empty proxies: {gname}")
        for risky in ("lazy", "timeout"):
            if risky in group:
                errors.append(f"{path}: risky group key {risky}: {gname}")
        for ref in group.get("proxies") or []:
            ref = str(ref)
            if ref == gname:
                errors.append(f"{path}: group self-reference: {gname}")
            if ref not in allowed:
                errors.append(f"{path}: invalid group reference: {gname} -> {ref}")
            if gtype in {"url-test", "fallback", "load-balance"} and ref in {"DIRECT", "REJECT"}:
                errors.append(f"{path}: {ref} appears in non-selector group: {gname}")
    for rule in data.get("rules") or []:
        target = rule_target(str(rule))
        if target and target.upper() in {"DIRECT", "REJECT"}:
            errors.append(f"{path}: DIRECT/REJECT used as rule target: {rule}")
        if target and target not in allowed and target.upper() not in {"DIRECT", "REJECT"}:
            errors.append(f"{path}: rule target not found: {rule}")
    return errors


def process_file(path: Path, input_proxies: Sequence[Dict[str, Any]], strict: bool) -> Dict[str, Any]:
    data = read_yaml(path)
    before_groups = len(get_groups(data))
    before_rules = len(data.get("rules") or [])
    add_stats = add_input_proxies_to_data(data, input_proxies)
    groups, group_stats = build_groups(data, input_proxies)
    data["proxy-groups"] = groups
    rules, rule_stats = build_clean_rules(data.get("rules") or [])
    data["rules"] = rules
    errors = validate_data(data, path)
    if errors and strict:
        raise RuntimeError("\n".join(errors))
    write_yaml(path, data)
    return {
        "file": str(path),
        "before_groups": before_groups,
        "after_groups": len(get_groups(data)),
        "before_rules": before_rules,
        "after_rules": len(data.get("rules") or []),
        "validation_errors": errors,
        **add_stats,
        **group_stats,
        **rule_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--strict", action="store_true", help="Fail on validation errors")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_files = split_env_list("CLEAN_RULE_OUTPUT_FILES", DEFAULT_OUTPUT_FILES)
    input_proxies, input_stats = read_input_proxies(root)

    processed: List[Dict[str, Any]] = []
    skipped: List[str] = []
    failed: List[Dict[str, Any]] = []

    for rel in output_files:
        path = root / rel
        if not path.exists():
            skipped.append(rel)
            continue
        try:
            processed.append(process_file(path, input_proxies, args.strict))
        except Exception as exc:
            failed.append({"file": rel, "error": str(exc)})
            if args.strict:
                break

    report = {
        "schema": "sumberyaml.clean-responsive-rules.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "input": input_stats,
        "input_proxy_names": [str(p.get("name")) for p in input_proxies if p.get("name")],
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "policy": {
            "direct_reject_rule_target_allowed": False,
            "direct_reject_selector_only": True,
            "dropped_proxy_types": sorted(DROP_TYPES),
            "simplified_groups": sorted(SIMPLIFIED_GROUPS),
            "reddit_group": GROUP_REDDIT,
            "input_vmess_load_balance_group": GROUP_INPUT_VMESS_LB,
        },
    }
    report_path = root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if failed:
        print(json.dumps({"failed": failed}, indent=2, ensure_ascii=False))
        return 1
    print(f"Clean responsive rules applied to {len(processed)} file(s). Report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

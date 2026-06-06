#!/usr/bin/env python3
"""
Strict-safe OpenClash finalizer for SumberYAML.

Goals:
- repair YAML that fails on older OpenClash/core builds;
- remove confusing legacy WEB/QOS/load-balance group trees;
- avoid load-balance entirely; use only select, url-test, fallback;
- keep DIRECT and REJECT only inside select groups;
- route marketplace, social media including LinkedIn, and banking through VMess nodes from input/links.txt;
- use nodes whose name contains "reddit" from input/links.txt as a special Reddit route;
- keep ss/ssr out because they caused OpenClash errors for this project.
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

CHECK_URL = os.getenv("STRICT_SAFE_CHECK_URL", "http://www.gstatic.com/generate_204")
REPORT_PATH = "output/Validation/openclash_strict_safe_fix_report.json"
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

DROP_TYPES = {"ss", "ssr"}
SPECIAL = {"DIRECT", "REJECT"}
AUTO_GROUP_TYPES = {"url-test", "fallback"}
RISKY_GROUP_KEYS = {
    "lazy",
    "timeout",
    "disable-udp",
    "interface-name",
    "routing-mark",
    "strategy",
}
RISKY_TOP_KEYS = {
    # These are valid only on some cores/config styles; do not force them in this safe profile.
    "tcp-concurrent",
    "unified-delay",
    "profile",
}

# Compact ASCII-only names for maximum compatibility in old OpenClash UIs/log parsers.
G_PROXY = "PROXY"
G_AUTO = "AUTO"
G_FALLBACK = "FALLBACK"
G_INPUT = "INPUT-VMESS"
G_REDDIT = "REDDIT"
G_SOCIAL_BANK_MARKET = "SOCIAL-BANK-MARKET"
G_STREAMING = "STREAMING"
G_GAME = "GAME"
G_AI = "AI"
G_WORK = "WORK"
G_DOWNLOAD = "DOWNLOAD"
G_DEFAULT = "DEFAULT"
G_BYPASS = "BYPASS"
G_BLOCK = "BLOCK"

STRICT_GROUPS = {
    G_PROXY,
    G_AUTO,
    G_FALLBACK,
    G_INPUT,
    G_REDDIT,
    G_SOCIAL_BANK_MARKET,
    G_STREAMING,
    G_GAME,
    G_AI,
    G_WORK,
    G_DOWNLOAD,
    G_DEFAULT,
    G_BYPASS,
    G_BLOCK,
}

# Groups created by older patches that should be fully replaced.
LEGACY_PREFIXES = ("WEB-", "QOS-", "TRAFIK-")
LEGACY_NAMES = {
    "PILIHAN-UTAMA",
    "AUTO-RESPONSIF",
    "FALLBACK-RESPONSIF",
    "INPUT-VMESS-LB",
    "REDDIT-INPUT",
    "TRAFIK-SOSMED",
    "TRAFIK-BANK-MARKET",
    "TRAFIK-STREAMING",
    "TRAFIK-GAME",
    "TRAFIK-AI",
    "TRAFIK-KERJA",
    "TRAFIK-DOWNLOAD",
    "TRAFIK-UMUM",
    "BLOKIR",
    "MANUAL-LINK",
    "MANUAL-FALLBACK",
    "MANUAL-BEST",
    "SMART-BEST",
    "SAT-SET",
    "ANTI-BENGONG",
    "BEST-STABLE",
    "fallback-link",
    "best-link",
    "INPUT-VMESS-LB",
}

URI_RE = re.compile(r"(?:vmess|vless|trojan|ssr|ss)://[^\s\"'<>]+", re.IGNORECASE)

LAN_RULES = [
    f"DOMAIN-SUFFIX,local,{G_BYPASS}",
    f"DOMAIN-SUFFIX,lan,{G_BYPASS}",
    f"IP-CIDR,127.0.0.0/8,{G_BYPASS},no-resolve",
    f"IP-CIDR,10.0.0.0/8,{G_BYPASS},no-resolve",
    f"IP-CIDR,172.16.0.0/12,{G_BYPASS},no-resolve",
    f"IP-CIDR,192.168.0.0/16,{G_BYPASS},no-resolve",
    f"IP-CIDR,169.254.0.0/16,{G_BYPASS},no-resolve",
]

ADS_RULES = [
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
]

DOMAIN_RULES: Dict[str, List[str]] = {
    G_REDDIT: [
        "reddit.com",
        "redd.it",
        "redditmedia.com",
        "redditstatic.com",
        "redditinc.com",
    ],
    G_SOCIAL_BANK_MARKET: [
        # social media and communication, including LinkedIn
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
        # Indonesian banking / payment apps
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
        # marketplace, delivery, transport, ticketing
        "tokopedia.com",
        "shopee.co.id",
        "shopee.com",
        "lazada.co.id",
        "bukalapak.com",
        "blibli.com",
        "tiket.com",
        "traveloka.com",
        "gojek.com",
        "grab.com",
        "maxim.com",
    ],
    G_STREAMING: [
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
    G_GAME: [
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
        "moonton.com",
        "pubgmobile.com",
        "krafton.com",
        "hoyoverse.com",
        "genshinimpact.com",
        "battle.net",
        "blizzard.com",
    ],
    G_AI: [
        "openai.com",
        "chatgpt.com",
        "oaistatic.com",
        "oaiusercontent.com",
        "anthropic.com",
        "claude.ai",
        "perplexity.ai",
        "gemini.google.com",
        "ai.google.dev",
        "copilot.microsoft.com",
        "huggingface.co",
    ],
    G_WORK: [
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
    G_DOWNLOAD: [
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
    return [x.strip() for x in raw.split(",") if x.strip()]


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


def clean_name(value: Any, fallback: str) -> str:
    text = unquote(str(value or "")).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Keep names readable but not huge; OpenClash UI can struggle with very long names.
    return text[:96] if text else fallback


def q_first(query: Dict[str, List[str]], *keys: str) -> str:
    for key in keys:
        vals = query.get(key)
        if vals and vals[0] is not None:
            return str(vals[0])
    return ""


def is_cdn_compatible(proxy: Dict[str, Any]) -> bool:
    ptype = str(proxy.get("type") or "").lower()
    network = str(proxy.get("network") or "tcp").lower()
    security = str(proxy.get("security") or proxy.get("flow") or "").lower()
    if ptype not in {"vmess", "vless", "trojan"}:
        return False
    if "reality" in security:
        return False
    return network in {"ws", "grpc", "h2", "http"}


def maybe_override_server(proxy: Dict[str, Any]) -> Dict[str, Any]:
    override = os.getenv("MANUAL_SERVER_OVERRIDE", "104.17.3.81").strip()
    mode = os.getenv("MANUAL_SERVER_OVERRIDE_TYPES", "cdn-compatible").strip().lower()
    out = copy.deepcopy(proxy)
    if not override:
        return out
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
    name = clean_name(obj.get("ps") or obj.get("name") or obj.get("remarks"), f"INPUT-VMESS-{index:03d}")
    server = str(obj.get("add") or obj.get("server") or "").strip()
    port = safe_int(obj.get("port"), 0)
    uuid = str(obj.get("id") or obj.get("uuid") or "").strip()
    if not server or not port or not uuid:
        return None
    network = str(obj.get("net") or obj.get("network") or "tcp").lower().strip() or "tcp"
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
    tls_raw = str(obj.get("tls") or "").lower()
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
    server = str(parsed.hostname or "").strip()
    port = safe_int(parsed.port, 0)
    credential = unquote(parsed.username or "").strip()
    if not server or not port or not credential:
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = clean_name(parsed.fragment, f"INPUT-{ptype.upper()}-{index:03d}")
    network = (q_first(query, "type", "network", "net") or "tcp").lower()
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
    if security == "tls" or q_first(query, "tls") in {"1", "true", "tls"}:
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
    elif network == "h2":
        path = q_first(query, "path")
        host = q_first(query, "host")
        h2_opts: Dict[str, Any] = {}
        if path:
            h2_opts["path"] = path
        if host:
            h2_opts["host"] = [host]
        if h2_opts:
            proxy["h2-opts"] = h2_opts
    return maybe_override_server(proxy)


def parse_uri(uri: str, index: int) -> Optional[Dict[str, Any]]:
    low = uri.lower()
    if low.startswith("ss://") or low.startswith("ssr://"):
        return None
    if low.startswith("vmess://"):
        return parse_vmess(uri, index)
    if low.startswith("vless://") or low.startswith("trojan://"):
        return parse_vless_or_trojan(uri, index)
    return None


def read_input_proxies(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    files = split_env_list("MANUAL_INPUT_FILES", DEFAULT_INPUT_FILES)
    proxies: List[Dict[str, Any]] = []
    stats = {"files_checked": [], "uri_count": 0, "parsed_count": 0, "skipped_count": 0, "blocked_ss_ssr": 0}
    index = 0
    for rel in files:
        path = root / rel
        stats["files_checked"].append(rel)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in URI_RE.finditer(text):
            uri = match.group(0).strip()
            index += 1
            stats["uri_count"] += 1
            if uri.lower().startswith(("ss://", "ssr://")):
                stats["blocked_ss_ssr"] += 1
                stats["skipped_count"] += 1
                continue
            proxy = parse_uri(uri, index)
            if proxy and str(proxy.get("type") or "").lower() not in DROP_TYPES:
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


def sanitize_top_level(data: Dict[str, Any]) -> None:
    for key in list(RISKY_TOP_KEYS):
        data.pop(key, None)


def get_proxies(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = data.get("proxies")
    if not isinstance(raw, list):
        data["proxies"] = []
        return data["proxies"]
    cleaned: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        ptype = str(item.get("type") or "").lower()
        if ptype in DROP_TYPES:
            continue
        cleaned.append(item)
    data["proxies"] = cleaned
    return cleaned


def strip_private(proxy: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in proxy.items() if not str(k).startswith("_")}


def ensure_unique_names(proxies: List[Dict[str, Any]]) -> None:
    counts: Dict[str, int] = {}
    for proxy in proxies:
        base = str(proxy.get("name") or "NODE").strip() or "NODE"
        n = counts.get(base, 0) + 1
        counts[base] = n
        if n > 1:
            proxy["name"] = f"{base}-{n}"


def add_input_proxies(data: Dict[str, Any], input_proxies: Sequence[Dict[str, Any]]) -> int:
    proxies = get_proxies(data)
    ensure_unique_names(proxies)
    existing = {str(p.get("name")) for p in proxies if p.get("name")}
    added = 0
    for p in input_proxies:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        clean = strip_private(p)
        # Preserve input names when possible; disambiguate duplicates safely.
        final_name = name
        suffix = 2
        while final_name in existing:
            final_name = f"{name}-{suffix}"
            suffix += 1
        clean["name"] = final_name
        proxies.append(clean)
        existing.add(final_name)
        added += 1
    return added


def proxy_names(data: Dict[str, Any]) -> List[str]:
    return unique_keep_order(str(p.get("name")) for p in get_proxies(data) if p.get("name"))


def type_by_name(data: Dict[str, Any]) -> Dict[str, str]:
    return {str(p.get("name")): str(p.get("type") or "").lower() for p in get_proxies(data) if p.get("name")}


def name_has_keyword(name: str, keywords: Sequence[str]) -> bool:
    raw = str(name or "").lower()
    compact = " " + re.sub(r"[^a-z0-9]+", " ", raw).strip() + " "
    for keyword in keywords:
        key = str(keyword).lower().strip()
        if not key:
            continue
        if key in raw or f" {key} " in compact:
            return True
    return False


def manual_input_names_from_data(data: Dict[str, Any]) -> List[str]:
    names = proxy_names(data)
    tmap = type_by_name(data)
    return [n for n in names if tmap.get(n) == "vmess" and name_has_keyword(n, ["input", "manual", "trusted", "link"])]


def pick_candidates(data: Dict[str, Any], prefer: Sequence[str], limit: int) -> List[str]:
    names = proxy_names(data)
    keywords = ["fast", "best", "stable", "id", "indo", "sg", "singapore", "premium", "low", "ping"]
    scored = [n for n in names if name_has_keyword(n, keywords)]
    return unique_keep_order(list(prefer) + scored + names)[:limit]


def refs_are_proxies(data: Dict[str, Any], refs: Sequence[str]) -> List[str]:
    pset = set(proxy_names(data))
    return [r for r in unique_keep_order(refs) if r in pset]


def make_select(name: str, refs: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": unique_keep_order(refs) or ["DIRECT"]}


def make_url_test(name: str, refs: Sequence[str], interval: int, tolerance: int) -> Dict[str, Any]:
    refs = unique_keep_order(refs)
    if not refs:
        return make_select(name, ["DIRECT"])
    return {"name": name, "type": "url-test", "proxies": refs, "url": CHECK_URL, "interval": interval, "tolerance": tolerance}


def make_fallback(name: str, refs: Sequence[str], interval: int) -> Dict[str, Any]:
    refs = unique_keep_order(refs)
    if not refs:
        return make_select(name, [G_AUTO, "DIRECT"])
    return {"name": name, "type": "fallback", "proxies": refs, "url": CHECK_URL, "interval": interval}


def build_groups(data: Dict[str, Any], input_proxies: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    interval = env_int("STRICT_SAFE_INTERVAL", 90)
    tolerance = env_int("STRICT_SAFE_TOLERANCE", 40)
    max_candidates = env_int("STRICT_SAFE_MAX_CANDIDATES", 20)

    names = proxy_names(data)
    tmap = type_by_name(data)

    # Match input proxies by original names, plus existing generated manual/input names.
    input_names = {str(p.get("name")) for p in input_proxies if p.get("name")}
    input_vmess = [n for n in names if n in input_names and tmap.get(n) == "vmess"]
    input_vmess.extend(manual_input_names_from_data(data))
    input_vmess = refs_are_proxies(data, input_vmess)

    reddit_input_names = [str(p.get("name")) for p in input_proxies if p.get("name") and "reddit" in str(p.get("name")).lower()]
    reddit_output_names = [n for n in names if "reddit" in n.lower()]
    reddit_nodes = refs_are_proxies(data, unique_keep_order(reddit_input_names + reddit_output_names))

    responsive = refs_are_proxies(data, pick_candidates(data, unique_keep_order(input_vmess + reddit_nodes), max_candidates))

    groups: List[Dict[str, Any]] = [
        make_select(G_PROXY, [G_AUTO, G_FALLBACK, G_INPUT, G_REDDIT, G_SOCIAL_BANK_MARKET, G_DEFAULT, G_BYPASS]),
        make_url_test(G_AUTO, responsive, interval, tolerance),
        make_fallback(G_FALLBACK, responsive, interval),
        make_fallback(G_INPUT, input_vmess, interval) if input_vmess else make_select(G_INPUT, [G_AUTO, G_FALLBACK, G_DEFAULT, "DIRECT"]),
        make_fallback(G_REDDIT, reddit_nodes, interval) if reddit_nodes else make_select(G_REDDIT, [G_INPUT, G_AUTO, G_FALLBACK, G_DEFAULT, "DIRECT"]),
        make_select(G_SOCIAL_BANK_MARKET, [G_INPUT, G_AUTO, G_FALLBACK, G_DEFAULT, "DIRECT"]),
        make_select(G_STREAMING, [G_AUTO, G_FALLBACK, G_INPUT, G_DEFAULT, "DIRECT"]),
        make_select(G_GAME, [G_AUTO, G_FALLBACK, G_INPUT, G_DEFAULT, "DIRECT"]),
        make_select(G_AI, [G_AUTO, G_FALLBACK, G_INPUT, G_DEFAULT, "DIRECT"]),
        make_select(G_WORK, [G_AUTO, G_FALLBACK, G_INPUT, G_DEFAULT, "DIRECT"]),
        make_select(G_DOWNLOAD, [G_FALLBACK, G_AUTO, G_INPUT, G_DEFAULT, "DIRECT"]),
        make_select(G_DEFAULT, [G_AUTO, G_FALLBACK, G_INPUT, "DIRECT"]),
        make_select(G_BYPASS, ["DIRECT", G_DEFAULT]),
        make_select(G_BLOCK, ["REJECT", G_BYPASS, G_DEFAULT]),
    ]

    # Only keep custom old groups that are not managed and not risky. This avoids legacy WEB/QOS/load-balance confusion.
    old_groups = data.get("proxy-groups") or []
    kept: List[Dict[str, Any]] = []
    removed: List[str] = []
    for g in old_groups:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        name = str(g.get("name"))
        gtype = str(g.get("type") or "")
        if name in STRICT_GROUPS or name in LEGACY_NAMES or any(name.startswith(pfx) for pfx in LEGACY_PREFIXES) or gtype == "load-balance":
            removed.append(name)
            continue
        clean = copy.deepcopy(g)
        for key in RISKY_GROUP_KEYS:
            clean.pop(key, None)
        if clean.get("type") in AUTO_GROUP_TYPES:
            clean["proxies"] = refs_are_proxies(data, clean.get("proxies") or [])
            if not clean["proxies"]:
                removed.append(name)
                continue
        kept.append(clean)

    # Reference cleanup after adding kept groups.
    all_groups = groups + kept
    group_names = {str(g.get("name")) for g in all_groups if g.get("name")}
    proxy_set = set(proxy_names(data))
    allowed = proxy_set | group_names | SPECIAL
    for g in all_groups:
        gname = str(g.get("name"))
        gtype = str(g.get("type") or "")
        refs = []
        for ref in g.get("proxies") or []:
            ref = str(ref).strip()
            if ref == gname:
                continue
            if gtype in AUTO_GROUP_TYPES and ref not in proxy_set:
                continue
            if ref in allowed:
                refs.append(ref)
        refs = unique_keep_order(refs)
        if not refs:
            refs = ["DIRECT"] if gtype == "select" else refs_are_proxies(data, responsive)
        if not refs:
            # Last resort: convert to selector to avoid OpenClash parser/runtime errors.
            g["type"] = "select"
            refs = ["DIRECT"]
        g["proxies"] = refs
        for key in RISKY_GROUP_KEYS:
            g.pop(key, None)
        if g.get("type") == "load-balance":
            # Strict mode never emits load-balance.
            g["type"] = "fallback"
            g["url"] = CHECK_URL
            g["interval"] = interval

    stats = {
        "removed_groups": unique_keep_order(removed),
        "input_vmess_nodes": input_vmess,
        "reddit_nodes": reddit_nodes,
        "responsive_candidates": responsive,
        "load_balance_emitted": False,
    }
    return all_groups, stats


def rule_target(rule: str) -> Optional[str]:
    parts = [p.strip() for p in str(rule).split(",")]
    if not parts:
        return None
    if parts[0].upper() == "MATCH" and len(parts) >= 2:
        return parts[1]
    if len(parts) >= 3:
        return parts[2]
    return None


def is_old_managed_rule(rule: str) -> bool:
    t = rule_target(rule)
    if not t:
        return False
    if t in STRICT_GROUPS or t in LEGACY_NAMES or t.upper() in {"DIRECT", "REJECT"}:
        return True
    if any(str(t).startswith(pfx) for pfx in LEGACY_PREFIXES):
        return True
    if str(rule).upper().startswith("MATCH,"):
        return True
    return False


def build_rules(existing: Sequence[Any]) -> Tuple[List[str], Dict[str, Any]]:
    custom: List[str] = []
    removed = 0
    seen: Set[str] = set()
    for item in existing:
        text = str(item or "").strip()
        if not text or text.startswith("#"):
            continue
        if is_old_managed_rule(text):
            removed += 1
            continue
        if text not in seen:
            custom.append(text)
            seen.add(text)

    rules: List[str] = []
    rules.extend(LAN_RULES)
    for domain in ADS_RULES:
        rules.append(f"DOMAIN-SUFFIX,{domain},{G_BLOCK}")
    for group, domains in DOMAIN_RULES.items():
        for domain in domains:
            rules.append(f"DOMAIN-SUFFIX,{domain},{group}")
    # Keep custom rules after managed high-priority rules, then final default.
    rules.extend(custom)
    rules.append(f"MATCH,{G_DEFAULT}")
    final = unique_keep_order(rules)
    return final, {"old_managed_rules_removed": removed, "final_rule_count": len(final)}


def validate(data: Dict[str, Any], path: Path) -> List[str]:
    errors: List[str] = []
    proxies = get_proxies(data)
    groups = data.get("proxy-groups") or []
    rules = data.get("rules") or []
    pset = {str(p.get("name")) for p in proxies if isinstance(p, dict) and p.get("name")}
    gset = {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}
    allowed = pset | gset | SPECIAL
    for p in proxies:
        ptype = str(p.get("type") or "").lower()
        if ptype in DROP_TYPES:
            errors.append(f"{path}: blocked proxy type still exists: {p.get('name')} ({ptype})")
    for g in groups:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name") or "")
        gtype = str(g.get("type") or "")
        refs = [str(r) for r in (g.get("proxies") or [])]
        if gtype == "load-balance":
            errors.append(f"{path}: load-balance is disabled in strict-safe mode: {name}")
        if not refs:
            errors.append(f"{path}: empty proxy group: {name}")
        for key in RISKY_GROUP_KEYS:
            if key in g:
                errors.append(f"{path}: risky group key remains: {name}.{key}")
        for ref in refs:
            if ref == name:
                errors.append(f"{path}: self-reference group: {name}")
            if ref not in allowed:
                errors.append(f"{path}: invalid group ref: {name} -> {ref}")
            if gtype in AUTO_GROUP_TYPES and ref in SPECIAL:
                errors.append(f"{path}: {ref} in automatic group: {name}")
    for r in rules:
        t = rule_target(str(r))
        if not t:
            continue
        if t.upper() in {"DIRECT", "REJECT"}:
            errors.append(f"{path}: DIRECT/REJECT used as rule target: {r}")
        if t not in allowed:
            errors.append(f"{path}: rule target not found: {r}")
    return errors


def process_file(path: Path, input_proxies: Sequence[Dict[str, Any]], strict: bool) -> Dict[str, Any]:
    data = read_yaml(path)
    sanitize_top_level(data)
    before_proxy_count = len(get_proxies(data))
    before_group_count = len(data.get("proxy-groups") or [])
    before_rule_count = len(data.get("rules") or [])
    added = add_input_proxies(data, input_proxies)
    data["proxy-groups"], group_stats = build_groups(data, input_proxies)
    data["rules"], rule_stats = build_rules(data.get("rules") or [])
    errors = validate(data, path)
    if errors and strict:
        raise RuntimeError("\n".join(errors))
    write_yaml(path, data)
    return {
        "file": str(path),
        "before_proxy_count": before_proxy_count,
        "after_proxy_count": len(get_proxies(data)),
        "input_proxies_added": added,
        "before_group_count": before_group_count,
        "after_group_count": len(data.get("proxy-groups") or []),
        "before_rule_count": before_rule_count,
        "after_rule_count": len(data.get("rules") or []),
        "validation_errors": errors,
        **group_stats,
        **rule_stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    output_files = split_env_list("STRICT_SAFE_OUTPUT_FILES", DEFAULT_OUTPUT_FILES)
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
        "schema": "sumberyaml.openclash-strict-safe-fix.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "input": input_stats,
        "input_proxy_names": [str(p.get("name")) for p in input_proxies if p.get("name")],
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "policy": {
            "no_load_balance": True,
            "automatic_group_types": sorted(AUTO_GROUP_TYPES),
            "direct_reject_rule_target_allowed": False,
            "direct_reject_selector_only": True,
            "blocked_proxy_types": sorted(DROP_TYPES),
            "server_override": os.getenv("MANUAL_SERVER_OVERRIDE", "104.17.3.81"),
            "server_override_types": os.getenv("MANUAL_SERVER_OVERRIDE_TYPES", "cdn-compatible"),
            "groups": sorted(STRICT_GROUPS),
        },
    }
    report_path = root / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if failed:
        print(json.dumps({"failed": failed}, indent=2, ensure_ascii=False))
        return 1
    print(f"Strict-safe OpenClash fix applied to {len(processed)} file(s). Report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Build service-aware, score-sorted OpenClash groups.

Key policy:
- Keep OpenClash strict-safe output: only select/url-test/fallback groups.
- Keep DIRECT/REJECT only inside selector groups.
- Drop ss/ssr and risky group/top-level options.
- Prefer TCP-alive and historically successful nodes.
- Use service-specific URL tests so OpenClash does not choose purely by generic ping.
- BLIBLI is special: its direct proxy candidates may ONLY come from links.txt-style manual files
  configured by --blibli-input-files. It must not use extra-source/provider nodes.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple
from urllib.parse import unquote, urlparse

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML is required: {exc}", file=sys.stderr)
    sys.exit(2)

SUPPORTED_PROXY_TYPES = {"vmess", "vless", "trojan"}
DROP_PROXY_TYPES = {"ss", "ssr"}
RISKY_TOP_LEVEL_KEYS = {"tcp-concurrent", "unified-delay"}
RISKY_GROUP_KEYS = {"lazy", "timeout", "strategy"}

DEFAULT_INPUT_FILES = [
    "input/links.txt",
    "input.txt",
    "links.txt",
    "input/google.txt",
    "input/oracle.txt",
    "input/microsoft.txt",
    "input/amazon.txt",
    "input/digitalocean.txt",
    "input/melbikom.txt",
    "input/vultr.txt",
    "input/r3xxe.txt",
]
DEFAULT_BLIBLI_FILES = [
    ".manual_source/input_links_original.txt",
    "input.txt",
    "links.txt",
]
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

# URL tests that OpenClash will use at runtime. This is what makes the selection app-aware.
CHECK_URLS: Mapping[str, str] = {
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
    "AI": "https://chatgpt.com/",
    "WORK": "https://github.com/",
    "DOWNLOAD": "https://github.com/",
}

APP_KEYWORDS: Mapping[str, Sequence[str]] = {
    "UTAMA": ("utama", "main", "primary", "prioritas", "default"),
    "GOOGLE": ("google", "gmail", "gstatic", "googlevideo", "ytimg", "youtube", "youtu"),
    "YOUTUBE": ("youtube", "youtu", "yt", "googlevideo", "ytimg"),
    "REDDIT": ("reddit", "redd.it", "r3xxe"),
    "LINKEDIN": ("linkedin", "licdn", "lnkd"),
    "BLIBLI": ("blibli",),
    "BANK": ("bank", "bca", "bri", "bni", "mandiri", "jago", "seabank", "blu", "livin", "brimo"),
    "MARKETPLACE": ("market", "tokopedia", "shopee", "lazada", "bukalapak", "blibli", "olshop"),
    "SOCIAL": ("social", "sosmed", "whatsapp", "telegram", "facebook", "instagram", "twitter", "x.com", "linkedin"),
    "STREAMING": ("stream", "netflix", "disney", "spotify", "twitch", "video", "youtube"),
    "AI": ("ai", "openai", "chatgpt", "claude", "gemini", "copilot"),
    "WORK": ("work", "github", "gitlab", "docker", "npm", "pypi", "dev"),
}

APP_RULES: Sequence[str] = [
    # BYPASS/BLOCK are selector groups, not direct DIRECT/REJECT targets.
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
    "DOMAIN-SUFFIX,meet.google.com,GOOGLE",
    # YouTube/video.
    "DOMAIN-SUFFIX,youtube.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtu.be,YOUTUBE",
    "DOMAIN-SUFFIX,ytimg.com,YOUTUBE",
    "DOMAIN-SUFFIX,googlevideo.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtubei.googleapis.com,YOUTUBE",
    "DOMAIN-SUFFIX,youtubekids.com,YOUTUBE",
    # Special applications.
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
    # Bank/e-wallet.
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
    "MATCH,PROXY",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def b64decode_maybe(value: str) -> str:
    raw = value.strip()
    raw += "=" * (-len(raw) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder(raw.encode()).decode("utf-8", "ignore")
        except Exception:
            pass
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
            return "vmess", unquote(frag).strip() if frag else None
    if line.startswith("vless://") or line.startswith("trojan://"):
        proto = line.split("://", 1)[0]
        frag = line.split("#", 1)[1] if "#" in line else None
        return proto, unquote(frag).strip() if frag else None
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
    tokens = set(hay.split())
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        if k in raw or k in tokens:
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


def proxy_key(proxy: Mapping[str, Any]) -> str:
    return clean_name(proxy.get("name"))


def valid_proxy(prox: Any) -> bool:
    if not isinstance(prox, dict):
        return False
    name = clean_name(prox.get("name"))
    typ = clean_name(prox.get("type")).lower()
    server = clean_name(prox.get("server"))
    port = prox.get("port")
    try:
        port_i = int(port)
    except Exception:
        return False
    return bool(name and server and typ in SUPPORTED_PROXY_TYPES and 0 < port_i <= 65535)


def clean_proxy(prox: Mapping[str, Any]) -> Dict[str, Any]:
    item = dict(prox)
    typ = clean_name(item.get("type")).lower()
    if typ in DROP_PROXY_TYPES:
        return {}
    # Do not aggressively modify proxy protocol fields. Only strip obvious non-proxy/risky group fields.
    for key in list(item.keys()):
        if key in RISKY_GROUP_KEYS or key in RISKY_TOP_LEVEL_KEYS:
            item.pop(key, None)
    return item


async def tcp_check_one(name: str, server: str, port: int, timeout: float, sem: asyncio.Semaphore) -> Tuple[str, bool, float | None, str | None]:
    started = time.perf_counter()
    async with sem:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout)
            elapsed = (time.perf_counter() - started) * 1000.0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return name, True, elapsed, None
        except Exception as exc:
            return name, False, None, exc.__class__.__name__


async def tcp_check_all(proxies: Sequence[Mapping[str, Any]], timeout: float, concurrency: int) -> Dict[str, Dict[str, Any]]:
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    tasks = []
    for p in proxies:
        name = clean_name(p.get("name"))
        server = clean_name(p.get("server"))
        try:
            port = int(p.get("port"))
        except Exception:
            continue
        if name and server and 0 < port <= 65535:
            tasks.append(tcp_check_one(name, server, port, timeout, sem))
    result: Dict[str, Dict[str, Any]] = {}
    for coro in asyncio.as_completed(tasks):
        name, ok, delay, err = await coro
        result[name] = {"tcp_alive": ok, "tcp_delay_ms": round(delay, 2) if delay is not None else None, "error": err}
    return result


def load_score_cache(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def update_score_cache(path: Path, proxies: Sequence[Mapping[str, Any]], tcp_results: Mapping[str, Mapping[str, Any]], services: Mapping[str, List[str]]) -> Dict[str, Any]:
    cache = load_score_cache(path)
    nodes = cache.get("nodes") if isinstance(cache.get("nodes"), dict) else {}
    proxy_by_name = {clean_name(p.get("name")): p for p in proxies}
    now = now_iso()
    for name, p in proxy_by_name.items():
        item = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
        item.update({
            "name": name,
            "type": clean_name(p.get("type")).lower(),
            "server": clean_name(p.get("server")),
            "port": p.get("port"),
            "last_seen_at": now,
        })
        tcp = tcp_results.get(name)
        if tcp:
            alive = bool(tcp.get("tcp_alive"))
            item["last_tcp_alive"] = alive
            item["last_tcp_delay_ms"] = tcp.get("tcp_delay_ms")
            item["last_tcp_error"] = tcp.get("error")
            item["last_tcp_checked_at"] = now
            item["tcp_success_count"] = int(item.get("tcp_success_count") or 0) + (1 if alive else 0)
            item["tcp_fail_count"] = int(item.get("tcp_fail_count") or 0) + (0 if alive else 1)
        nodes[name] = item
    cache = {
        "updated_at_utc": now,
        "policy": "tcp-score-plus-openclash-service-url-test",
        "note": "TCP score is an early filter. App compatibility is selected at OpenClash runtime by service-specific url-test groups.",
        "nodes": nodes,
        "services": services,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cache


def score_name(name: str, service: str, score_cache: Mapping[str, Any], manual_names: Mapping[str, Set[str]], service_keywords: Sequence[str]) -> Tuple[int, float, int, str]:
    nodes = score_cache.get("nodes") if isinstance(score_cache.get("nodes"), dict) else {}
    item = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
    alive = 1 if item.get("last_tcp_alive") is True else 0
    success = int(item.get("tcp_success_count") or 0)
    fail = int(item.get("tcp_fail_count") or 0)
    delay = item.get("last_tcp_delay_ms")
    try:
        delay_f = float(delay) if delay is not None else 999999.0
    except Exception:
        delay_f = 999999.0
    keyword = 1 if name_has_keyword(name, service_keywords) else 0
    manual = 1 if name in manual_names.get("all", set()) else 0
    # Higher first for alive/keyword/manual/success; lower delay/fail first.
    primary = alive * 100000 + keyword * 10000 + manual * 1000 + success * 10 - fail * 50
    return (-primary, delay_f, fail, name.lower())


def sorted_candidates(names: Iterable[str], service: str, score_cache: Mapping[str, Any], manual_names: Mapping[str, Set[str]], keywords: Sequence[str], max_candidates: int, prefer_alive: bool = True) -> List[str]:
    items = dedupe_keep_order(names)
    nodes = score_cache.get("nodes") if isinstance(score_cache.get("nodes"), dict) else {}
    if prefer_alive:
        alive_items = [n for n in items if isinstance(nodes.get(n), dict) and nodes[n].get("last_tcp_alive") is True]
        if alive_items:
            items = alive_items
    items = sorted(items, key=lambda n: score_name(n, service, score_cache, manual_names, keywords))
    return items[:max_candidates]


def build_candidate_pools(
    proxies: Sequence[Dict[str, Any]],
    manual_names: Mapping[str, Set[str]],
    blibli_names: Mapping[str, Set[str]],
    score_cache: Mapping[str, Any],
    max_candidates: int,
) -> Dict[str, List[str]]:
    all_names = [clean_name(p.get("name")) for p in proxies]
    type_by_name = {clean_name(p.get("name")): clean_name(p.get("type")).lower() for p in proxies}

    manual_all = [n for n in all_names if n in manual_names.get("all", set())]
    if not manual_all:
        manual_all = [n for n in all_names if name_has_keyword(n, ("manual", "input", "link", "utama", "google", "youtube", "reddit", "linkedin", "blibli"))]
    manual_vmess = [n for n in manual_all if type_by_name.get(n) == "vmess"]
    if not manual_vmess:
        manual_vmess = [n for n in all_names if type_by_name.get(n) == "vmess" and name_has_keyword(n, ("manual", "input", "link"))]

    pools: Dict[str, List[str]] = {}
    pools["ALL"] = sorted_candidates(all_names, "AUTO", score_cache, manual_names, (), max_candidates)
    pools["MANUAL"] = sorted_candidates(manual_all, "UTAMA", score_cache, manual_names, APP_KEYWORDS["UTAMA"], max_candidates)
    pools["INPUT-VMESS"] = sorted_candidates(manual_vmess, "INPUT-VMESS", score_cache, manual_names, (), max_candidates)

    for group_name, keywords in APP_KEYWORDS.items():
        by_kw = [n for n in all_names if name_has_keyword(n, keywords)]
        by_manual_kw = [n for n in manual_all if name_has_keyword(n, keywords)]
        pool = dedupe_keep_order(by_manual_kw + by_kw + manual_all + all_names)
        pools[group_name] = sorted_candidates(pool, group_name, score_cache, manual_names, keywords, max_candidates)

    # YouTube and Google can share candidate families.
    pools["YOUTUBE"] = sorted_candidates(
        dedupe_keep_order(pools.get("YOUTUBE", []) + pools.get("GOOGLE", []) + manual_all + all_names),
        "YOUTUBE", score_cache, manual_names, APP_KEYWORDS["YOUTUBE"], max_candidates,
    )
    pools["GOOGLE"] = sorted_candidates(
        dedupe_keep_order(pools.get("GOOGLE", []) + pools.get("YOUTUBE", []) + manual_all + all_names),
        "GOOGLE", score_cache, manual_names, APP_KEYWORDS["GOOGLE"], max_candidates,
    )

    # BLIBLI STRICT POLICY: only manual links.txt-style candidates. Do not add extra-source/all fallback names.
    blibli_source = [n for n in all_names if n in blibli_names.get("all", set())]
    blibli_named = [n for n in blibli_source if name_has_keyword(n, APP_KEYWORDS["BLIBLI"])]
    pools["BLIBLI"] = sorted_candidates(
        dedupe_keep_order(blibli_named + blibli_source),
        "BLIBLI", score_cache, blibli_names, APP_KEYWORDS["BLIBLI"], max_candidates,
    )

    return pools


def url_test_group(name: str, proxies: Sequence[str], url: str, interval: int, tolerance: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "url-test",
        "proxies": dedupe_keep_order(proxies),
        "url": url,
        "interval": int(interval),
        "tolerance": int(tolerance),
    }


def fallback_group(name: str, proxies: Sequence[str], url: str, interval: int) -> Dict[str, Any]:
    return {"name": name, "type": "fallback", "proxies": dedupe_keep_order(proxies), "url": url, "interval": int(interval)}


def select_group(name: str, proxies: Sequence[str]) -> Dict[str, Any]:
    return {"name": name, "type": "select", "proxies": dedupe_keep_order(proxies)}


def build_groups(pools: Mapping[str, List[str]], interval: int, tolerance: int) -> List[Dict[str, Any]]:
    all_candidates = pools.get("ALL", [])
    if not all_candidates:
        return []
    input_vmess = pools.get("INPUT-VMESS") or all_candidates
    utama = pools.get("UTAMA") or pools.get("MANUAL") or all_candidates
    blibli_candidates = pools.get("BLIBLI") or []

    groups: List[Dict[str, Any]] = []
    groups.append(select_group("PROXY", [
        "UTAMA", "GOOGLE", "YOUTUBE", "REDDIT", "LINKEDIN", "BLIBLI",
        "BANK", "MARKETPLACE", "SOCIAL", "STREAMING", "AI", "WORK", "DOWNLOAD",
        "AUTO", "FALLBACK", "DEFAULT", "BYPASS", "BLOCK",
    ]))
    groups.append(select_group("UTAMA", utama + ["AUTO", "FALLBACK", "DIRECT"]))
    groups.append(url_test_group("AUTO", all_candidates, CHECK_URLS["AUTO"], interval, tolerance))
    groups.append(fallback_group("FALLBACK", all_candidates, CHECK_URLS["FALLBACK"], interval))
    groups.append(fallback_group("INPUT-VMESS", input_vmess, CHECK_URLS["AUTO"], interval))

    groups.append(url_test_group("GOOGLE", pools.get("GOOGLE") or all_candidates, CHECK_URLS["GOOGLE"], interval, tolerance))
    groups.append(url_test_group("YOUTUBE", pools.get("YOUTUBE") or pools.get("GOOGLE") or all_candidates, CHECK_URLS["YOUTUBE"], interval, tolerance))
    groups.append(url_test_group("REDDIT", pools.get("REDDIT") or utama or all_candidates, CHECK_URLS["REDDIT"], interval, tolerance))
    groups.append(url_test_group("LINKEDIN", pools.get("LINKEDIN") or input_vmess or all_candidates, CHECK_URLS["LINKEDIN"], interval, tolerance))
    if blibli_candidates:
        groups.append(url_test_group("BLIBLI", blibli_candidates, CHECK_URLS["BLIBLI"], interval, tolerance))
    else:
        # Keep config valid without using extra-source proxies for BLIBLI.
        groups.append(select_group("BLIBLI", ["BYPASS", "DEFAULT"]))

    groups.append(select_group("BANK", dedupe_keep_order((pools.get("BANK") or []) + input_vmess + ["UTAMA", "AUTO", "FALLBACK", "BYPASS"])))
    groups.append(select_group("MARKETPLACE", dedupe_keep_order((pools.get("MARKETPLACE") or []) + input_vmess + ["UTAMA", "AUTO", "FALLBACK", "BYPASS"])))
    groups.append(select_group("SOCIAL", dedupe_keep_order((pools.get("SOCIAL") or []) + input_vmess + ["LINKEDIN", "UTAMA", "AUTO", "FALLBACK"])))
    groups.append(url_test_group("STREAMING", pools.get("STREAMING") or pools.get("YOUTUBE") or all_candidates, CHECK_URLS["STREAMING"], interval, tolerance))
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
        target_idx = len(parts) - 1
        if parts[target_idx].lower() == "no-resolve" and target_idx >= 1:
            target_idx -= 1
        target = parts[target_idx]
        if target == "DIRECT":
            parts[target_idx] = "BYPASS"
        elif target == "REJECT":
            parts[target_idx] = "BLOCK"
        elif target not in group_names:
            continue
        cleaned.append(",".join(parts))
    cleaned = [r for r in cleaned if not r.upper().startswith("MATCH,")]
    cleaned.append("MATCH,PROXY")
    return dedupe_keep_order(cleaned)


def process_config(
    path: Path,
    manual_names: Mapping[str, Set[str]],
    blibli_names: Mapping[str, Set[str]],
    score_cache: Mapping[str, Any],
    interval: int,
    tolerance: int,
    max_candidates: int,
) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"file": str(path), "status": "error", "error": f"YAML parse failed: {exc}"}
    if not isinstance(data, dict):
        return {"file": str(path), "status": "skip", "reason": "not a mapping"}

    for key in RISKY_TOP_LEVEL_KEYS:
        data.pop(key, None)
    data.pop("rule-providers", None)

    raw_proxies = data.get("proxies") or []
    proxies: List[Dict[str, Any]] = []
    dropped = 0
    duplicates = 0
    seen_names: Set[str] = set()
    for item in raw_proxies:
        cleaned = clean_proxy(item) if isinstance(item, dict) else {}
        if not valid_proxy(cleaned):
            dropped += 1
            continue
        name = clean_name(cleaned.get("name"))
        if name in seen_names:
            duplicates += 1
            continue
        seen_names.add(name)
        proxies.append(cleaned)

    if not proxies:
        return {"file": str(path), "status": "skip", "reason": "no supported proxies", "dropped": dropped}

    pools = build_candidate_pools(proxies, manual_names, blibli_names, score_cache, max_candidates=max_candidates)
    groups = build_groups(pools, interval=interval, tolerance=tolerance)
    group_names = {g["name"] for g in groups if isinstance(g, dict) and g.get("name")}
    rules = sanitize_rules(APP_RULES, group_names)

    data["proxies"] = proxies
    data["proxy-groups"] = groups
    data["rules"] = rules
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")

    return {
        "file": str(path),
        "status": "updated",
        "proxies": len(proxies),
        "groups": len(groups),
        "rules": len(rules),
        "dropped": dropped,
        "duplicates": duplicates,
        "manual_names": len(manual_names.get("all", set())),
        "blibli_links_only_candidates": len(pools.get("BLIBLI", [])),
        "google_candidates": len(pools.get("GOOGLE", [])),
        "youtube_candidates": len(pools.get("YOUTUBE", [])),
        "reddit_candidates": len(pools.get("REDDIT", [])),
        "linkedin_candidates": len(pools.get("LINKEDIN", [])),
        "input_vmess_candidates": len(pools.get("INPUT-VMESS", [])),
    }


def iter_yaml_files(root: Path, explicit: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    for rel in explicit:
        path = root / rel
        if path.exists() and path.is_file() and path not in paths:
            paths.append(path)
    output_dir = root / "output"
    if output_dir.exists():
        for path in sorted(output_dir.glob("*.yaml")):
            if path not in paths:
                paths.append(path)
    return paths


def create_manual_only(root: Path, source_yaml: Path, manual_names: Mapping[str, Set[str]], score_cache: Mapping[str, Any], interval: int, tolerance: int, max_candidates: int) -> Dict[str, Any]:
    target = root / "output/manual_only.yaml"
    if not source_yaml.exists():
        return {"file": str(target), "status": "skip", "reason": "source yaml missing"}
    try:
        data = yaml.safe_load(source_yaml.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"file": str(target), "status": "error", "error": str(exc)}
    if not isinstance(data, dict):
        return {"file": str(target), "status": "skip", "reason": "source not mapping"}
    proxies = [p for p in data.get("proxies") or [] if isinstance(p, dict) and valid_proxy(clean_proxy(p))]
    manual_set = manual_names.get("all", set())
    manual_proxies = [clean_proxy(p) for p in proxies if clean_name(p.get("name")) in manual_set]
    if not manual_proxies:
        manual_proxies = [clean_proxy(p) for p in proxies if name_has_keyword(clean_name(p.get("name")), ("manual", "input", "link", "utama", "google", "reddit", "linkedin", "blibli"))]
    if not manual_proxies:
        return {"file": str(target), "status": "skip", "reason": "no manual proxies found"}
    data["proxies"] = manual_proxies
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return process_config(target, manual_names, manual_names, score_cache, interval=interval, tolerance=tolerance, max_candidates=max_candidates)


def collect_proxies_from_yaml(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    proxies: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for raw in data.get("proxies") or []:
            if not isinstance(raw, dict):
                continue
            cleaned = clean_proxy(raw)
            if not valid_proxy(cleaned):
                continue
            name = clean_name(cleaned.get("name"))
            if name in seen:
                continue
            seen.add(name)
            proxies.append(cleaned)
    return proxies


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply service-score app-aware OpenClash groups with BLIBLI links-only policy.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--input-files", default=os.getenv("MANUAL_INPUT_FILES", ",".join(DEFAULT_INPUT_FILES)))
    parser.add_argument("--blibli-input-files", default=os.getenv("BLIBLI_INPUT_FILES", ",".join(DEFAULT_BLIBLI_FILES)))
    parser.add_argument("--interval", type=int, default=int(os.getenv("SERVICE_SCORE_INTERVAL", os.getenv("APP_AWARE_INTERVAL", "90"))))
    parser.add_argument("--tolerance", type=int, default=int(os.getenv("SERVICE_SCORE_TOLERANCE", os.getenv("APP_AWARE_TOLERANCE", "40"))))
    parser.add_argument("--max-candidates", type=int, default=int(os.getenv("SERVICE_SCORE_MAX_CANDIDATES", os.getenv("APP_AWARE_MAX_CANDIDATES", "25"))))
    parser.add_argument("--yaml-files", default=";".join(DEFAULT_YAML_FILES))
    parser.add_argument("--score-cache", default=os.getenv("SERVICE_SCORE_CACHE", "cache/service_node_score.json"))
    parser.add_argument("--tcp-probe", default=os.getenv("SERVICE_SCORE_TCP_PROBE", "true"))
    parser.add_argument("--tcp-timeout", type=float, default=float(os.getenv("SERVICE_SCORE_TCP_TIMEOUT", "2.5")))
    parser.add_argument("--tcp-concurrency", type=int, default=int(os.getenv("SERVICE_SCORE_TCP_CONCURRENCY", "120")))
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    input_files = [x.strip() for x in re.split(r"[,;]", args.input_files) if x.strip()]
    blibli_input_files = [x.strip() for x in re.split(r"[,;]", args.blibli_input_files) if x.strip()]
    yaml_files = [x.strip() for x in re.split(r"[,;]", args.yaml_files) if x.strip()]
    paths = iter_yaml_files(root, yaml_files)

    manual_names = load_manual_names(root, input_files)
    blibli_names = load_manual_names(root, blibli_input_files)
    all_proxies = collect_proxies_from_yaml(paths)

    score_path = root / args.score_cache
    tcp_results: Dict[str, Dict[str, Any]] = {}
    if str(args.tcp_probe).lower() in {"1", "true", "yes", "on"} and all_proxies:
        tcp_results = asyncio.run(tcp_check_all(all_proxies, args.tcp_timeout, args.tcp_concurrency))

    # Preliminary service map is updated after each file, but the cache records candidate intent too.
    service_cache_stub: Dict[str, List[str]] = {name: [] for name in CHECK_URLS}
    score_cache = update_score_cache(score_path, all_proxies, tcp_results, service_cache_stub)

    source_for_manual = root / "output/fast.yaml"
    manual_result = create_manual_only(root, source_for_manual, manual_names, score_cache, args.interval, args.tolerance, args.max_candidates)

    results: List[Dict[str, Any]] = []
    for path in iter_yaml_files(root, yaml_files):
        results.append(process_config(path, manual_names, blibli_names, score_cache, args.interval, args.tolerance, args.max_candidates))

    report = {
        "status": "ok",
        "generated_at_utc": now_iso(),
        "policy": "service-score-url-test-strict-safe-blibli-links-only",
        "meaning": "Nodes are pre-sorted by TCP/live score and OpenClash uses per-service url-test groups at runtime. BLIBLI direct candidates are limited to links.txt-style input files.",
        "direct_reject_policy": "DIRECT and REJECT may appear only inside selector groups",
        "unsupported_protocols_dropped": sorted(DROP_PROXY_TYPES),
        "supported_protocols": sorted(SUPPORTED_PROXY_TYPES),
        "manual_input_files": input_files,
        "blibli_input_files": blibli_input_files,
        "manual_names_count": {k: len(v) for k, v in manual_names.items()},
        "blibli_links_only_names_count": {k: len(v) for k, v in blibli_names.items()},
        "tcp_probe_enabled": str(args.tcp_probe).lower() in {"1", "true", "yes", "on"},
        "tcp_probe_checked": len(tcp_results),
        "tcp_probe_alive": sum(1 for x in tcp_results.values() if x.get("tcp_alive")),
        "score_cache": args.score_cache,
        "check_urls": CHECK_URLS,
        "manual_only": manual_result,
        "results": results,
    }
    out_dir = root / "output/Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "service_score_groups_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    updated = [r for r in results if r.get("status") == "updated"]
    if not updated:
        print("ERROR: no YAML files updated", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

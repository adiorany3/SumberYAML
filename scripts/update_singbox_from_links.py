#!/usr/bin/env python3
"""
Generate sing-box 1.13+/1.14-ready config and merged link.txt from SumberYAML inputs.

Strict-safe policy:
- Accept vmess://, vless://, trojan:// only.
- Drop ss:// and ssr://.
- Read trusted/manual files plus generated alive/provider files.
- Write root link.txt, input/link.txt, output/SingBox/links.txt,
  output/SingBox/sing-box.json, output/SingBox/outbounds.json,
  output/Validation/singbox_report.json.
- Use non-legacy DNS server formats and avoid legacy inbound sniff fields.
- Preserve Blibli links-only policy: BLIBLI sing-box group only uses nodes
  that came from original input/links.txt, input.txt, or links.txt.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as _dt
import hashlib
import ipaddress
import json
import os
import pathlib
import re
import socket
import sys
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

SUPPORTED_SCHEMES = {"vmess", "vless", "trojan"}
DROPPED_SCHEMES = {"ss", "ssr"}

DEFAULT_INPUT_FILES = [
    "input/links.txt",
    "input.txt",
    "links.txt",
    "input/link.txt",
    "link.txt",
    "input/extra_sources_alive.txt",
    "input/google.txt",
    "input/oracle.txt",
    "input/microsoft.txt",
    "input/amazon.txt",
    "input/digitalocean.txt",
    "input/melbikom.txt",
    "input/vultr.txt",
    "input/r3xxe.txt",
]

MANUAL_SOURCE_FILES = [
    ".manual_source/input_links_original.txt",
    "input/links.txt",
    "input.txt",
    "links.txt",
]

SERVICE_KEYWORDS = {
    "google": ["google", "gcp", "gmail", "gstatic", "googlevideo", "ytimg"],
    "youtube": ["youtube", "youtu", "yt-", "yt_", "googlevideo", "ytimg"],
    "reddit": ["reddit", "redd.it"],
    "linkedin": ["linkedin", "licdn", "lnkd"],
    "blibli": ["blibli"],
    "oracle": ["oracle", "oci", "oraclecloud"],
    "microsoft": ["microsoft", "azure", "msft"],
    "amazon": ["amazon", "aws", "amazonaws", "ec2", "cloudfront"],
    "digitalocean": ["digitalocean", "digital ocean", "digital-ocean", "droplet"],
    "melbikom": ["melbikom", "melbi"],
    "vultr": ["vultr"],
}

SERVICE_TEST_URLS = {
    "sb-auto": "https://www.gstatic.com/generate_204",
    "sb-google": "https://www.gstatic.com/generate_204",
    "sb-youtube": "https://www.youtube.com/generate_204",
    "sb-reddit": "https://www.reddit.com/",
    "sb-linkedin": "https://www.linkedin.com/",
    "sb-blibli": "https://www.blibli.com/",
    "sb-work": "https://github.com/",
}

GAME_BLOCK_DOMAINS = [
    "callofwar.com", "bytro.com", "supremacy1914.com", "ironorder1919.com",
    "conflictofnations.com", "travian.com", "ogame.org", "ikariam.com",
    "tribalwars.net", "grepolis.com", "forgeofempires.com", "poki.com",
    "crazygames.com", "y8.com", "krunker.io", "slither.io", "agar.io",
    "roblox.com", "steampowered.com", "steamcommunity.com", "epicgames.com",
    "riotgames.com", "pubgmobile.com", "mobilelegends.com", "freefiremobile.com",
    "garena.com", "battle.net", "blizzard.com", "minecraft.net", "xboxlive.com",
    "playstation.com", "nintendo.com", "ea.com", "ubisoft.com", "hoyoverse.com",
    "genshinimpact.com", "supercell.com", "callofduty.com", "rockstargames.com",
    "kongregate.com", "itch.io", "now.gg", "geforcenow.com",
]

GOOGLE_DOMAINS = [
    "google.com", "google.co.id", "googleapis.com", "gstatic.com", "googleusercontent.com",
    "googlevideo.com", "ytimg.com", "youtube.com", "youtu.be", "youtubei.googleapis.com",
    "ggpht.com", "gmail.com", "googlemail.com", "meet.google.com",
]

YOUTUBE_DOMAINS = ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com", "youtubei.googleapis.com"]
REDDIT_DOMAINS = ["reddit.com", "redd.it", "redditmedia.com", "redditstatic.com", "redditinc.com"]
LINKEDIN_DOMAINS = ["linkedin.com", "licdn.com", "lnkd.in", "linkedin.cn"]
BLIBLI_DOMAINS = ["blibli.com", "blibli.co.id"]
WORK_DOMAINS = ["github.com", "githubusercontent.com", "gitlab.com", "docker.com", "npmjs.com", "pypi.org", "stackoverflow.com"]


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def b64decode_padded(value: str) -> bytes:
    value = value.strip()
    value = value.replace("-", "+").replace("_", "/")
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value)


def b64decode_text(value: str) -> Optional[str]:
    try:
        return b64decode_padded(value).decode("utf-8", "ignore")
    except Exception:
        return None


def is_probably_subscription_blob(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    if "://" in text:
        return False
    return len(compact) > 80 and re.fullmatch(r"[A-Za-z0-9_+/=\-]+", compact) is not None


def extract_links_from_text(text: str) -> List[str]:
    candidates: List[str] = []
    if is_probably_subscription_blob(text):
        decoded = b64decode_text(text)
        if decoded and "://" in decoded:
            text = decoded
    # Split by common separators but keep URI query fragments.
    for raw in re.split(r"[\r\n\t <>|]+", text):
        item = raw.strip().strip('"\'`,;')
        if not item:
            continue
        if re.match(r"^(vmess|vless|trojan|ss|ssr)://", item, re.I):
            candidates.append(item)
    return candidates


def read_all_links(root: pathlib.Path, files: Iterable[str]) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    for rel in files:
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for link in extract_links_from_text(text):
            items.append((link, rel))
    return items


def get_scheme(link: str) -> str:
    return link.split(":", 1)[0].lower().strip()


def safe_name(text: str, fallback: str) -> str:
    text = urllib.parse.unquote(text or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" #")
    if not text:
        text = fallback
    # sing-box tag can contain spaces, but short clean tags are easier to manage.
    text = re.sub(r"[^0-9A-Za-z_.@()\- +]+", "-", text)
    text = text[:80].strip(" -") or fallback
    return text


def unique_tag(base: str, used: set[str]) -> str:
    tag = base
    i = 2
    while tag in used or tag in {"direct", "block", "select", "sb-auto", "sb-google", "sb-youtube", "sb-reddit", "sb-linkedin", "sb-blibli", "sb-work"}:
        suffix = f"-{i}"
        tag = (base[: max(1, 80 - len(suffix))] + suffix).strip()
        i += 1
    used.add(tag)
    return tag


def parse_port(value: Any) -> Optional[int]:
    try:
        port = int(str(value).strip())
    except Exception:
        return None
    if 1 <= port <= 65535:
        return port
    return None


def host_for_urlparse(authority_url: str) -> Tuple[Optional[str], Optional[int], str, str, Dict[str, List[str]]]:
    parsed = urllib.parse.urlsplit(authority_url)
    host = parsed.hostname
    port = parsed.port
    username = urllib.parse.unquote(parsed.username or "")
    password = urllib.parse.unquote(parsed.password or "")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return host, port, username, password, query


def first(query: Dict[str, List[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in query and query[key]:
            return query[key][0]
    return default


def build_tls(security: str, sni: str = "", alpn: str = "", insecure: str = "", reality: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    sec = (security or "").lower()
    if sec not in {"tls", "reality"}:
        return None
    tls: Dict[str, Any] = {"enabled": True}
    if sni:
        tls["server_name"] = sni
    if alpn:
        tls["alpn"] = [x.strip() for x in alpn.split(",") if x.strip()]
    if insecure.lower() in {"1", "true", "yes"}:
        tls["insecure"] = True
    if sec == "reality" and reality:
        r: Dict[str, Any] = {"enabled": True}
        if reality.get("public_key"):
            r["public_key"] = reality["public_key"]
        if reality.get("short_id"):
            r["short_id"] = reality["short_id"]
        tls["reality"] = r
    return tls


def build_transport(net: str, query: Dict[str, List[str]], host_hint: str = "", path_hint: str = "") -> Optional[Dict[str, Any]]:
    net = (net or "tcp").lower()
    if net in {"ws", "websocket"}:
        host = first(query, "host", "Host", default=host_hint)
        path = first(query, "path", default=path_hint or "/")
        tr: Dict[str, Any] = {"type": "ws"}
        if path:
            tr["path"] = urllib.parse.unquote(path)
        if host:
            tr["headers"] = {"Host": urllib.parse.unquote(host)}
        return tr
    if net == "grpc":
        service_name = first(query, "serviceName", "serviceName", "service", default=path_hint)
        tr = {"type": "grpc"}
        if service_name:
            tr["service_name"] = urllib.parse.unquote(service_name).lstrip("/")
        return tr
    if net in {"h2", "http"}:
        host = first(query, "host", default=host_hint)
        path = first(query, "path", default=path_hint or "/")
        tr = {"type": "http"}
        if host:
            tr["host"] = [urllib.parse.unquote(host)]
        if path:
            tr["path"] = urllib.parse.unquote(path)
        return tr
    return None


def parse_vmess(link: str, used: set[str], source: str) -> Optional[Dict[str, Any]]:
    payload = link.split("://", 1)[1]
    text = b64decode_text(payload)
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    server = str(data.get("add") or data.get("server") or "").strip()
    port = parse_port(data.get("port"))
    uuid = str(data.get("id") or data.get("uuid") or "").strip()
    if not server or not port or not uuid:
        return None
    tag = unique_tag(safe_name(str(data.get("ps") or data.get("name") or ""), f"vmess-{server}-{port}"), used)
    net = str(data.get("net") or data.get("network") or "tcp")
    tls_security = str(data.get("tls") or "").lower()
    if tls_security == "tls":
        security = "tls"
    else:
        security = ""
    query: Dict[str, List[str]] = {}
    if data.get("host"):
        query["host"] = [str(data.get("host"))]
    if data.get("path"):
        query["path"] = [str(data.get("path"))]
    if data.get("sni"):
        query["sni"] = [str(data.get("sni"))]
    outbound: Dict[str, Any] = {
        "type": "vmess",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": str(data.get("scy") or data.get("security") or "auto"),
        "alter_id": int(data.get("aid") or data.get("alterId") or 0),
        "_source": source,
        "_raw_scheme": "vmess",
    }
    tls = build_tls(security, str(data.get("sni") or data.get("host") or ""))
    if tls:
        outbound["tls"] = tls
    tr = build_transport(net, query, str(data.get("host") or ""), str(data.get("path") or ""))
    if tr:
        outbound["transport"] = tr
    return outbound


def parse_vless(link: str, used: set[str], source: str) -> Optional[Dict[str, Any]]:
    host, port, username, _password, query = host_for_urlparse(link)
    if not host or not port or not username:
        return None
    name = urllib.parse.urlsplit(link).fragment
    tag = unique_tag(safe_name(name, f"vless-{host}-{port}"), used)
    security = first(query, "security", default="")
    sni = first(query, "sni", "servername", "peer", default="")
    reality = {
        "public_key": first(query, "pbk", "publicKey", default=""),
        "short_id": first(query, "sid", "shortId", default=""),
    }
    outbound: Dict[str, Any] = {
        "type": "vless",
        "tag": tag,
        "server": host,
        "server_port": port,
        "uuid": username,
        "_source": source,
        "_raw_scheme": "vless",
    }
    flow = first(query, "flow", default="")
    if flow:
        outbound["flow"] = flow
    tls = build_tls(security, sni, first(query, "alpn", default=""), first(query, "allowInsecure", "insecure", default=""), reality)
    if tls:
        outbound["tls"] = tls
    tr = build_transport(first(query, "type", "network", default="tcp"), query)
    if tr:
        outbound["transport"] = tr
    return outbound


def parse_trojan(link: str, used: set[str], source: str) -> Optional[Dict[str, Any]]:
    host, port, username, _password, query = host_for_urlparse(link)
    if not host or not port or not username:
        return None
    name = urllib.parse.urlsplit(link).fragment
    tag = unique_tag(safe_name(name, f"trojan-{host}-{port}"), used)
    security = first(query, "security", default="tls") or "tls"
    sni = first(query, "sni", "servername", "peer", default="")
    outbound: Dict[str, Any] = {
        "type": "trojan",
        "tag": tag,
        "server": host,
        "server_port": port,
        "password": username,
        "_source": source,
        "_raw_scheme": "trojan",
    }
    tls = build_tls(security, sni, first(query, "alpn", default=""), first(query, "allowInsecure", "insecure", default=""))
    if tls:
        outbound["tls"] = tls
    tr = build_transport(first(query, "type", "network", default="tcp"), query)
    if tr:
        outbound["transport"] = tr
    return outbound


def parse_link(link: str, used: set[str], source: str) -> Optional[Dict[str, Any]]:
    scheme = get_scheme(link)
    try:
        if scheme == "vmess":
            return parse_vmess(link, used, source)
        if scheme == "vless":
            return parse_vless(link, used, source)
        if scheme == "trojan":
            return parse_trojan(link, used, source)
    except Exception:
        return None
    return None


def strip_private_fields(outbound: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in outbound.items() if not k.startswith("_")}


def tcp_alive(server: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((server, port), timeout=timeout):
            return True
    except Exception:
        return False


def is_manual_source(source: str) -> bool:
    normalized = source.replace("\\", "/")
    return normalized in {".manual_source/input_links_original.txt", "input/links.txt", "input.txt", "links.txt"}


def keyword_match(outbound: Dict[str, Any], keywords: List[str]) -> bool:
    haystack_parts = [
        str(outbound.get("tag", "")),
        str(outbound.get("server", "")),
        str(outbound.get("_source", "")),
    ]
    tls = outbound.get("tls") or {}
    if isinstance(tls, dict):
        haystack_parts.append(str(tls.get("server_name", "")))
    transport = outbound.get("transport") or {}
    if isinstance(transport, dict):
        headers = transport.get("headers") or {}
        if isinstance(headers, dict):
            haystack_parts.append(str(headers.get("Host", "")))
        host = transport.get("host")
        if isinstance(host, list):
            haystack_parts.extend(map(str, host))
        else:
            haystack_parts.append(str(host or ""))
    haystack = " ".join(haystack_parts).lower()
    return any(k.lower() in haystack for k in keywords)


def select_tags(outbounds: List[Dict[str, Any]], service: str, fallback_limit: int, manual_only: bool = False) -> List[str]:
    keywords = SERVICE_KEYWORDS.get(service, [])
    matched = [o["tag"] for o in outbounds if (not manual_only or o.get("_manual")) and keyword_match(o, keywords)]
    if matched:
        return matched[:fallback_limit]
    if manual_only:
        return [o["tag"] for o in outbounds if o.get("_manual")][:fallback_limit]
    return [o["tag"] for o in outbounds][:fallback_limit]


def build_config(outbounds: List[Dict[str, Any]], fallback_limit: int) -> Dict[str, Any]:
    proxy_tags = [o["tag"] for o in outbounds]
    if not proxy_tags:
        raise SystemExit("No supported sing-box outbounds available.")

    # Service candidate tags. BLIBLI must only use manual/trusted links.
    google_tags = select_tags(outbounds, "google", fallback_limit)
    youtube_tags = select_tags(outbounds, "youtube", fallback_limit)
    reddit_tags = select_tags(outbounds, "reddit", fallback_limit)
    linkedin_tags = select_tags(outbounds, "linkedin", fallback_limit)
    blibli_tags = select_tags(outbounds, "blibli", fallback_limit, manual_only=True)
    work_tags = select_tags(outbounds, "microsoft", fallback_limit) or proxy_tags[:fallback_limit]

    generated_groups: List[Dict[str, Any]] = [
        {"type": "selector", "tag": "select", "outbounds": ["sb-auto"] + proxy_tags[:fallback_limit] + ["direct"], "default": "sb-auto"},
        {"type": "urltest", "tag": "sb-auto", "outbounds": proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-auto"], "interval": "3m", "tolerance": 50},
        {"type": "urltest", "tag": "sb-google", "outbounds": google_tags or proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-google"], "interval": "3m", "tolerance": 50},
        {"type": "urltest", "tag": "sb-youtube", "outbounds": youtube_tags or google_tags or proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-youtube"], "interval": "3m", "tolerance": 50},
        {"type": "urltest", "tag": "sb-reddit", "outbounds": reddit_tags or proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-reddit"], "interval": "3m", "tolerance": 50},
        {"type": "urltest", "tag": "sb-linkedin", "outbounds": linkedin_tags or proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-linkedin"], "interval": "3m", "tolerance": 50},
        {"type": "selector", "tag": "sb-blibli", "outbounds": (blibli_tags or ["select"]) + ["select", "direct"], "default": (blibli_tags[0] if blibli_tags else "select")},
        {"type": "urltest", "tag": "sb-work", "outbounds": work_tags or proxy_tags[:fallback_limit], "url": SERVICE_TEST_URLS["sb-work"], "interval": "3m", "tolerance": 50},
    ]

    final_outbounds = generated_groups + [strip_private_fields(o) for o in outbounds] + [
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"},
    ]

    route_rules = [
        {"ip_is_private": True, "action": "route", "outbound": "direct"},
        {"domain_suffix": GAME_BLOCK_DOMAINS, "action": "route", "outbound": "block"},
        {"domain_suffix": YOUTUBE_DOMAINS, "action": "route", "outbound": "sb-youtube"},
        {"domain_suffix": GOOGLE_DOMAINS, "action": "route", "outbound": "sb-google"},
        {"domain_suffix": REDDIT_DOMAINS, "action": "route", "outbound": "sb-reddit"},
        {"domain_suffix": LINKEDIN_DOMAINS, "action": "route", "outbound": "sb-linkedin"},
        {"domain_suffix": BLIBLI_DOMAINS, "action": "route", "outbound": "sb-blibli"},
        {"domain_suffix": WORK_DOMAINS, "action": "route", "outbound": "sb-work"},
    ]

    # sing-box 1.12+ introduced the new DNS server format; legacy
    # {"address": "tls://..."} DNS servers are removed in 1.14.
    # Keep the generated config 1.13-compatible and 1.14-ready by using
    # typed DNS servers. Do not add legacy inbound sniff fields; sniffing is
    # handled through route actions when needed, and domain routing still
    # works for mixed inbound domain requests.
    config: Dict[str, Any] = {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"type": "tls", "tag": "dns-google", "server": "8.8.8.8", "server_port": 853},
                {"type": "tls", "tag": "dns-cloudflare", "server": "1.1.1.1", "server_port": 853},
            ],
            "final": "dns-google",
            "strategy": "prefer_ipv4",
            "timeout": "10s",
        },
        "inbounds": [
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 2080},
        ],
        "outbounds": final_outbounds,
        "route": {"rules": route_rules, "final": "select"},
        "experimental": {"cache_file": {"enabled": True, "path": "cache.db"}},
    }
    return config


def write_json(path: pathlib.Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    tags = []
    for outbound in config.get("outbounds", []):
        tag = outbound.get("tag")
        if not tag:
            errors.append("outbound without tag")
            continue
        tags.append(tag)
        if outbound.get("type") in {"ss", "shadowsocks", "ssr"}:
            errors.append(f"unsupported outbound type in sing-box output: {outbound.get('type')}")
    if len(tags) != len(set(tags)):
        errors.append("duplicate outbound tags")
    tagset = set(tags)
    for outbound in config.get("outbounds", []):
        if outbound.get("type") in {"selector", "urltest"}:
            for target in outbound.get("outbounds", []):
                if target not in tagset:
                    errors.append(f"group {outbound.get('tag')} references missing outbound {target}")
    for rule in config.get("route", {}).get("rules", []):
        target = rule.get("outbound")
        if target and target not in tagset:
            errors.append(f"route rule references missing outbound {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-outbounds", type=int, default=int(os.environ.get("SINGBOX_MAX_OUTBOUNDS", "500")))
    parser.add_argument("--fallback-limit", type=int, default=int(os.environ.get("SINGBOX_GROUP_LIMIT", "60")))
    parser.add_argument("--tcp-check", action="store_true", default=os.environ.get("SINGBOX_TCP_CHECK", "false").lower() == "true")
    parser.add_argument("--tcp-timeout", type=float, default=float(os.environ.get("SINGBOX_TCP_TIMEOUT", "3")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("SINGBOX_CONCURRENCY", "100")))
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    input_files = DEFAULT_INPUT_FILES
    raw_items = read_all_links(root, input_files)

    # Add original manual links to preserve Blibli links-only semantics even after input/links.txt is temporarily appended.
    manual_raw = read_all_links(root, MANUAL_SOURCE_FILES)
    manual_hashes = {hashlib.sha256(link.encode("utf-8", "ignore")).hexdigest() for link, _src in manual_raw}
    raw_items.extend(manual_raw)

    seen: set[str] = set()
    used_tags: set[str] = set()
    supported_links: List[Tuple[str, str]] = []
    dropped_by_scheme: Dict[str, int] = {}
    parse_failed = 0
    parsed: List[Dict[str, Any]] = []

    for link, source in raw_items:
        scheme = get_scheme(link)
        if scheme in DROPPED_SCHEMES:
            dropped_by_scheme[scheme] = dropped_by_scheme.get(scheme, 0) + 1
            continue
        if scheme not in SUPPORTED_SCHEMES:
            continue
        key = hashlib.sha256(link.encode("utf-8", "ignore")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        outbound = parse_link(link, used_tags, source)
        if not outbound:
            parse_failed += 1
            continue
        outbound["_manual"] = key in manual_hashes or is_manual_source(source)
        outbound["_raw_link"] = link
        parsed.append(outbound)
        supported_links.append((link, source))
        if len(parsed) >= args.max_outbounds:
            break

    tcp_report: Dict[str, bool] = {}
    if args.tcp_check and parsed:
        def check(o: Dict[str, Any]) -> Tuple[str, bool]:
            return o["tag"], tcp_alive(str(o.get("server")), int(o.get("server_port")), args.tcp_timeout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            futures = [ex.submit(check, o) for o in parsed]
            for fut in concurrent.futures.as_completed(futures):
                tag, ok = fut.result()
                tcp_report[tag] = ok
        parsed = [o for o in parsed if tcp_report.get(o["tag"], False) or o.get("_manual")]
        # Keep manual links even if TCP check fails; they are trusted/manual and user expects them preserved.
        supported_links = [(o.get("_raw_link", ""), o.get("_source", "")) for o in parsed if o.get("_raw_link")]

    config = build_config(parsed, args.fallback_limit)
    errors = validate_config(config)
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        return 2

    out_dir = root / "output" / "SingBox"
    validation_dir = root / "output" / "Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)

    merged_links = [link for link, _source in supported_links]
    link_text = "\n".join(merged_links) + ("\n" if merged_links else "")
    for rel in ["link.txt", "input/link.txt", "output/SingBox/links.txt"]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(link_text, encoding="utf-8")

    write_json(out_dir / "sing-box.json", config)
    write_json(out_dir / "outbounds.json", [strip_private_fields(o) for o in parsed])

    service_counts = {}
    for svc in SERVICE_KEYWORDS:
        service_counts[svc] = sum(1 for o in parsed if keyword_match(o, SERVICE_KEYWORDS[svc]))
    blibli_manual_tags = select_tags(parsed, "blibli", args.fallback_limit, manual_only=True)

    report = {
        "generated_at": utc_now(),
        "input_files": [str(f) for f in input_files],
        "raw_items_seen": len(raw_items),
        "supported_unique_links": len(supported_links),
        "outbounds_generated": len(parsed),
        "manual_outbounds": sum(1 for o in parsed if o.get("_manual")),
        "parse_failed": parse_failed,
        "dropped_by_scheme": dropped_by_scheme,
        "tcp_check_enabled": bool(args.tcp_check),
        "tcp_alive_count": sum(1 for ok in tcp_report.values() if ok) if tcp_report else None,
        "service_keyword_counts": service_counts,
        "blibli_policy": "links-only/manual-source-only",
        "blibli_manual_tags": blibli_manual_tags,
        "outputs": [
            "link.txt",
            "input/link.txt",
            "output/SingBox/links.txt",
            "output/SingBox/sing-box.json",
            "output/SingBox/outbounds.json",
        ],
    }
    write_json(validation_dir / "singbox_report.json", report)
    (out_dir / "README.txt").write_text(
        "Generated by scripts/update_singbox_from_links.py\n"
        "Supported schemes: vmess, vless, trojan. ss/ssr are dropped.\n"
        "BLIBLI uses links-only/manual-source candidates.\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

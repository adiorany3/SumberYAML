#!/usr/bin/env python3
"""
OpenClash-compatible responsive post-processor for SumberYAML.

This version is intentionally conservative. It does not force Meta/Mihomo-only
root options and it removes group-level fields that often make OpenClash reject
YAML on older Clash/OpenClash cores.

What it does:
- keeps compatible manual/trusted accounts intact;
- injects direct vmess/vless/trojan nodes from input/links.txt/input.txt into every output YAML;
- intentionally skips ss:// and ssr:// links because they can break some OpenClash cores;
- can force compatible trusted manual input node servers to a CDN/IP host such as 104.17.3.81 only when the transport is CDN-safe;
- removes existing ss/ssr proxy objects and cleans group references by default;
- never tests, quarantines, or removes compatible manual/trusted input accounts;
- builds safe MANUAL-FALLBACK / SMART-BEST / SAT-SET / ANTI-BENGONG / BEST-STABLE groups and output/manual_only.yaml;
- uses only broadly compatible proxy-group keys;
- repairs risky keys from the previous turbo/no-delay patch.
"""

from __future__ import annotations

import argparse
import csv
import json
import base64
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, unquote, urlparse

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
    "output/manual_only.yaml",
    "output/Performance/performance-lite.yaml",
]

MANUAL_INPUT_FILES = [
    "input/links.txt",
    "input.txt",
    "links.txt",
]

# Extra SS/SSR source scanning is kept only for backward-compatible CLI arguments,
# but it is disabled by default in this OpenClash-safe patch.
EXTRA_SS_SSR_SOURCE_PATHS = [
    "input",
    "sources",
    "source",
    "subs",
    "sub",
    "subscription",
    "subscriptions",
    "raw",
    "data",
    "output/Cache/sources",
    "output/Raw",
    "output/Sources",
    "output/Subs",
]

TEXT_SCAN_EXTENSIONS = {
    ".txt", ".list", ".csv", ".json", ".yaml", ".yml", ".log", ".conf", ".md"
}

SKIP_SCAN_PARTS = {
    ".git", ".github", "node_modules", ".venv", "venv", "__pycache__",
    "Backup", "Validation", "backup", "validation",
}

SS_SSR_SERVER_OVERRIDE = ""
DROP_PROXY_TYPES = "ss,ssr"
# Trusted manual nodes from input/links.txt/input.txt/links.txt can also have
# their server field rewritten. This patch rewrites only compatible OpenClash
# node types by default and skips ss/ssr links entirely.
MANUAL_SERVER_OVERRIDE = "104.17.3.81"
MANUAL_SERVER_OVERRIDE_TYPES = "cdn-compatible"

MANUAL_GROUP_SELECT = "MANUAL-LINK"
MANUAL_GROUP_FALLBACK = "MANUAL-FALLBACK"
MANUAL_GROUP_URLTEST = "MANUAL-BEST"
SMART_GROUP_BEST = "SMART-BEST"
MANUAL_ONLY_OUTPUT = "output/manual_only.yaml"
NODE_SCORE_CACHE = "cache/node_score.json"
TEXT_REPORT = "output/report.txt"
MANUAL_PROXY_PREFIX = "MANUAL-LINK"

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

def split_env_list(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def normalize_server_override(value: str) -> str:
    # Accept plain IP/host or accidental URL-style input. Clash expects only host/IP
    # in the server field, not a scheme.
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        parsed = urlparse(raw)
        return parsed.hostname or raw
    return raw.strip("/ ")


def b64_decode_text(value: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return decoder(raw.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            continue
    return None


def q_one(query: Dict[str, List[str]], key: str, default: str = "") -> str:
    values = query.get(key) or []
    if not values:
        return default
    return unquote(str(values[0]))


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def parse_host_port(value: str) -> Tuple[str, int]:
    raw = str(value or "").strip()
    if not raw:
        return "", 0
    parsed = urlparse("//" + raw)
    host = parsed.hostname or ""
    try:
        port = int(parsed.port or 0)
    except Exception:
        port = 0
    return host, port


def clean_display_name(value: str, fallback: str) -> str:
    name = unquote(str(value or "")).strip()
    name = re.sub(r"[\r\n\t]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = fallback
    return name[:72]


def make_manual_name(index: int, preferred: str, used_names: Set[str]) -> str:
    display = clean_display_name(preferred, f"Input {index:03d}")
    base = f"{MANUAL_PROXY_PREFIX}-{index:03d} {display}"[:96]
    name = base
    suffix = 2
    while name in used_names:
        tail = f" #{suffix}"
        name = f"{base[:96-len(tail)]}{tail}"
        suffix += 1
    used_names.add(name)
    return name


def add_transport_opts(proxy: Dict[str, Any], network: str, query_or_dict: Dict[str, Any]) -> None:
    net = str(network or "").strip().lower()
    if net and net != "tcp":
        proxy["network"] = net

    def get_value(key: str, default: str = "") -> str:
        if isinstance(query_or_dict, dict):
            value = query_or_dict.get(key, default)
            if isinstance(value, list):
                value = value[0] if value else default
            return unquote(str(value or default))
        return default

    if net == "ws":
        path = get_value("path") or "/"
        host = get_value("host")
        opts: Dict[str, Any] = {"path": path}
        if host:
            opts["headers"] = {"Host": host}
        proxy["ws-opts"] = opts
    elif net == "grpc":
        service = get_value("serviceName") or get_value("service-name") or get_value("path")
        if service:
            proxy["grpc-opts"] = {"grpc-service-name": service}
    elif net in {"h2", "http"}:
        host = get_value("host")
        path = get_value("path") or "/"
        opts: Dict[str, Any] = {"path": [path]}
        if host:
            opts["host"] = [host]
        proxy["h2-opts"] = opts


def parse_vmess_link(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    payload = line[len("vmess://"):].strip()
    decoded = b64_decode_text(payload)
    if not decoded:
        return None, "vmess base64 decode failed"
    try:
        item = json.loads(decoded)
    except Exception as exc:
        return None, f"vmess json decode failed: {exc}"
    server = str(item.get("add") or item.get("server") or "").strip()
    port = parse_int(item.get("port"), 0)
    uuid = str(item.get("id") or item.get("uuid") or "").strip()
    if not server or not port or not uuid:
        return None, "vmess missing server/port/uuid"
    proxy: Dict[str, Any] = {
        "name": clean_display_name(str(item.get("ps") or ""), "VMess Manual"),
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": parse_int(item.get("aid"), 0),
        "cipher": str(item.get("scy") or "auto"),
        "udp": True,
    }
    tls_value = str(item.get("tls") or "").strip().lower()
    if tls_value in {"tls", "true", "1"}:
        proxy["tls"] = True
        sni = str(item.get("sni") or item.get("host") or "").strip()
        if sni:
            proxy["servername"] = sni
    network = str(item.get("net") or "tcp").strip().lower()
    add_transport_opts(proxy, network, {
        "path": item.get("path") or "/",
        "host": item.get("host") or "",
        "serviceName": item.get("path") or "",
    })
    return proxy, ""


def parse_vless_link(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    parsed = urlparse(line)
    uuid = unquote(parsed.username or "")
    server = parsed.hostname or ""
    try:
        port = int(parsed.port or 0)
    except Exception:
        port = 0
    if not uuid or not server or not port:
        return None, "vless missing uuid/server/port"
    query = parse_qs(parsed.query, keep_blank_values=True)
    security = q_one(query, "security").lower()
    network = q_one(query, "type", "tcp").lower()
    proxy: Dict[str, Any] = {
        "name": clean_display_name(parsed.fragment, "VLESS Manual"),
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "udp": True,
    }
    encryption = q_one(query, "encryption")
    if encryption:
        proxy["encryption"] = encryption
    flow = q_one(query, "flow")
    if flow:
        proxy["flow"] = flow
    if security in {"tls", "reality"}:
        proxy["tls"] = True
        sni = q_one(query, "sni") or q_one(query, "servername") or q_one(query, "peer")
        if sni:
            proxy["servername"] = sni
        fp = q_one(query, "fp") or q_one(query, "fingerprint")
        if fp:
            proxy["client-fingerprint"] = fp
    if security == "reality":
        reality: Dict[str, Any] = {}
        pbk = q_one(query, "pbk") or q_one(query, "public-key")
        sid = q_one(query, "sid") or q_one(query, "short-id")
        if pbk:
            reality["public-key"] = pbk
        if sid:
            reality["short-id"] = sid
        if reality:
            proxy["reality-opts"] = reality
    add_transport_opts(proxy, network, query)
    return proxy, ""


def parse_trojan_link(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    parsed = urlparse(line)
    password = unquote(parsed.username or "")
    server = parsed.hostname or ""
    try:
        port = int(parsed.port or 0)
    except Exception:
        port = 0
    if not password or not server or not port:
        return None, "trojan missing password/server/port"
    query = parse_qs(parsed.query, keep_blank_values=True)
    network = q_one(query, "type", "tcp").lower()
    proxy: Dict[str, Any] = {
        "name": clean_display_name(parsed.fragment, "Trojan Manual"),
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "udp": True,
    }
    sni = q_one(query, "sni") or q_one(query, "peer") or q_one(query, "servername")
    if sni:
        proxy["sni"] = sni
    security = q_one(query, "security")
    if security in {"tls", ""}:
        proxy["tls"] = True
    add_transport_opts(proxy, network, query)
    return proxy, ""


def parse_ss_link(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = line[len("ss://"):].strip()
    main, _, fragment = raw.partition("#")
    main, _, query_text = main.partition("?")
    name = clean_display_name(fragment, "SS Manual")
    if "@" in main:
        userinfo, hostport = main.rsplit("@", 1)
        if ":" not in userinfo:
            decoded = b64_decode_text(userinfo)
            if not decoded:
                return None, "ss userinfo base64 decode failed"
            userinfo = decoded
    else:
        decoded = b64_decode_text(main)
        if not decoded or "@" not in decoded:
            return None, "ss base64 decode failed"
        userinfo, hostport = decoded.rsplit("@", 1)
    if ":" not in userinfo:
        return None, "ss missing cipher/password"
    cipher, password = userinfo.split(":", 1)
    server, port = parse_host_port(hostport)
    if not cipher or not password or not server or not port:
        return None, "ss missing cipher/password/server/port"
    proxy: Dict[str, Any] = {
        "name": name,
        "type": "ss",
        "server": server,
        "port": port,
        "cipher": unquote(cipher),
        "password": unquote(password),
        "udp": True,
    }
    query = parse_qs(query_text, keep_blank_values=True)
    plugin = q_one(query, "plugin")
    if plugin.startswith("obfs"):
        proxy["plugin"] = "obfs"
        plugin_opts: Dict[str, Any] = {}
        for part in plugin.split(";")[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                if key == "obfs":
                    plugin_opts["mode"] = value
                elif key == "obfs-host":
                    plugin_opts["host"] = value
        if plugin_opts:
            proxy["plugin-opts"] = plugin_opts
    return proxy, ""


def parse_ssr_link(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    decoded = b64_decode_text(line[len("ssr://"):].strip())
    if not decoded:
        return None, "ssr base64 decode failed"
    try:
        head, _, query_text = decoded.partition("/?")
        server, port, protocol, method, obfs, password_b64 = head.split(":", 5)
        password = b64_decode_text(password_b64) or password_b64
        query = parse_qs(query_text, keep_blank_values=True)
        remarks = b64_decode_text(q_one(query, "remarks")) or "SSR Manual"
        proxy: Dict[str, Any] = {
            "name": clean_display_name(remarks, "SSR Manual"),
            "type": "ssr",
            "server": server,
            "port": parse_int(port, 0),
            "protocol": protocol,
            "cipher": method,
            "obfs": obfs,
            "password": password,
            "udp": True,
        }
        obfs_param = b64_decode_text(q_one(query, "obfsparam") or "")
        proto_param = b64_decode_text(q_one(query, "protoparam") or "")
        if obfs_param:
            proxy["obfs-param"] = obfs_param
        if proto_param:
            proxy["protocol-param"] = proto_param
        if not proxy["server"] or not proxy["port"]:
            return None, "ssr missing server/port"
        return proxy, ""
    except Exception as exc:
        return None, f"ssr parse failed: {exc}"


def parse_clash_proxy_line(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    candidate = line.strip()
    if candidate.startswith("-"):
        candidate = candidate[1:].strip()
    try:
        data = yaml.safe_load(candidate)
    except Exception as exc:
        return None, f"inline clash yaml parse failed: {exc}"
    if not isinstance(data, dict):
        return None, "inline clash yaml is not a mapping"
    if not data.get("type") or not data.get("server"):
        return None, "inline clash proxy missing type/server"
    ptype = str(data.get("type") or "").strip().lower()
    if ptype in {"ss", "ssr"}:
        return None, "ss/ssr disabled for OpenClash compatibility"
    data = dict(data)
    data.setdefault("name", "Manual Clash Proxy")
    return data, ""


def parse_manual_link_line(line: str) -> Tuple[Optional[Dict[str, Any]], str]:
    value = str(line or "").strip()
    if not value or value.startswith("#"):
        return None, "blank/comment"
    lowered = value.lower()
    if lowered.startswith("vmess://"):
        return parse_vmess_link(value)
    if lowered.startswith("vless://"):
        return parse_vless_link(value)
    if lowered.startswith("trojan://"):
        return parse_trojan_link(value)
    if lowered.startswith("ss://"):
        return None, "ss disabled for OpenClash compatibility"
    if lowered.startswith("ssr://"):
        return None, "ssr disabled for OpenClash compatibility"
    if value.startswith("{") or value.startswith("-"):
        return parse_clash_proxy_line(value)
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return None, "subscription/http source, not a direct proxy node"
    return None, "unsupported or unparsable direct proxy format"


def proxy_signature(proxy: Dict[str, Any]) -> str:
    ptype = str(proxy.get("type") or "").lower()
    # For SS/SSR, ignore the server in the de-dup key because this patch may
    # intentionally rewrite server to the CDN/IP override.
    if ptype == "ss":
        return "|".join([
            ptype,
            str(proxy.get("port") or ""),
            str(proxy.get("cipher") or ""),
            str(proxy.get("password") or ""),
            str(proxy.get("plugin") or ""),
            json.dumps(proxy.get("plugin-opts") or {}, sort_keys=True, ensure_ascii=False),
        ])
    if ptype == "ssr":
        return "|".join([
            ptype,
            str(proxy.get("port") or ""),
            str(proxy.get("protocol") or ""),
            str(proxy.get("cipher") or ""),
            str(proxy.get("obfs") or ""),
            str(proxy.get("password") or ""),
            str(proxy.get("obfs-param") or ""),
            str(proxy.get("protocol-param") or ""),
        ])
    return json.dumps(proxy, sort_keys=True, ensure_ascii=False, default=str)


def apply_ss_ssr_server_override_to_proxy(proxy: Dict[str, Any], server_override: str) -> bool:
    target = normalize_server_override(server_override)
    if not target:
        return False
    ptype = str(proxy.get("type") or "").strip().lower()
    if ptype not in {"ss", "ssr"}:
        return False
    if str(proxy.get("server") or "") == target:
        return False
    proxy["server"] = target
    proxy["_ss_ssr_server_forced"] = True
    return True


def proxy_transport(proxy: Dict[str, Any]) -> str:
    network = str(proxy.get("network") or "").strip().lower()
    if network:
        return network
    if proxy.get("ws-opts"):
        return "ws"
    if proxy.get("grpc-opts"):
        return "grpc"
    if proxy.get("h2-opts"):
        return "h2"
    if proxy.get("http-opts"):
        return "http"
    return "tcp"


def is_cdn_compatible_proxy(proxy: Dict[str, Any]) -> bool:
    """Return True only for node shapes that are usually safe behind a CDN IP.

    The goal is to avoid breaking OpenClash by forcing 104.17.3.81 on nodes
    that need their original upstream server, especially VLESS Reality and raw
    TCP/TLS nodes.
    """
    ptype = str(proxy.get("type") or "").strip().lower()
    if ptype not in {"vmess", "vless", "trojan"}:
        return False
    if proxy.get("reality-opts"):
        return False
    transport = proxy_transport(proxy)
    return transport in {"ws", "grpc", "h2", "http"}


def type_allowed_for_manual_server_override(proxy: Dict[str, Any], allowed_types: Set[str]) -> bool:
    if not allowed_types:
        return False
    ptype = str(proxy.get("type") or "").strip().lower()
    if not ptype or "server" not in proxy:
        return False
    if "cdn-compatible" in allowed_types or "cdn" in allowed_types or "cdn-only" in allowed_types:
        return is_cdn_compatible_proxy(proxy)
    if "all" in allowed_types or "*" in allowed_types:
        return True
    return ptype in allowed_types


def apply_manual_server_override_to_proxy(
    proxy: Dict[str, Any],
    server_override: str,
    allowed_types: Set[str],
) -> bool:
    target = normalize_server_override(server_override)
    if not target:
        return False
    if not type_allowed_for_manual_server_override(proxy, allowed_types):
        return False
    if str(proxy.get("server") or "") == target:
        proxy["_manual_server_forced"] = True
        return False
    proxy["server"] = target
    proxy["_manual_server_forced"] = True
    return True


def override_manual_servers_in_existing_data(
    data: Dict[str, Any],
    server_override: str,
    allowed_types: Set[str],
) -> Dict[str, Any]:
    target = normalize_server_override(server_override)
    stats: Dict[str, Any] = {"target": target, "changed": 0, "seen": 0}
    if not target:
        return stats
    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        return stats
    for item in proxies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not is_manual_name(name):
            continue
        if not type_allowed_for_manual_server_override(item, allowed_types):
            continue
        stats["seen"] += 1
        if str(item.get("server") or "") != target:
            item["server"] = target
            stats["changed"] += 1
    return stats


def override_ss_ssr_servers_in_data(data: Dict[str, Any], server_override: str) -> Dict[str, Any]:
    # Backward-compatible no-op in this patch. SS/SSR is not rewritten; it is
    # removed by drop_proxy_types_from_data instead.
    return {"target": normalize_server_override(server_override), "changed": 0, "seen": 0, "disabled": True}


def drop_proxy_types_from_data(data: Dict[str, Any], drop_types: Set[str]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {"drop_types": sorted(drop_types), "removed": 0, "removed_names": [], "group_refs_removed": 0}
    if not drop_types:
        return stats
    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        return stats

    kept: List[Any] = []
    removed_names: Set[str] = set()
    for item in proxies:
        if isinstance(item, dict) and str(item.get("type") or "").strip().lower() in drop_types:
            name = str(item.get("name") or "").strip()
            if name:
                removed_names.add(name)
            stats["removed"] += 1
            continue
        kept.append(item)
    data["proxies"] = kept
    stats["removed_names"] = sorted(removed_names)

    if removed_names:
        for group in get_groups(data):
            refs = group.get("proxies")
            if not isinstance(refs, list):
                continue
            fixed = [ref for ref in refs if str(ref) not in removed_names]
            stats["group_refs_removed"] += len(refs) - len(fixed)
            group["proxies"] = fixed
    return stats


def clean_extracted_link_token(token: str) -> str:
    value = str(token or "").strip()
    # Remove common delimiters accidentally captured from JSON/YAML/Markdown.
    value = value.strip("'\"<>`")
    while value and value[-1] in ",;)]}":
        value = value[:-1]
    return value.strip()


def extract_ss_ssr_links_from_text(text: str) -> List[str]:
    # Match raw links from txt/csv/json/yaml cache files. Link fragments are allowed
    # but whitespace terminates the token.
    found = re.findall(r"(?i)\b(?:ssr|ss)://[^\s'\"<>]+", text or "")
    return unique_keep_order(clean_extracted_link_token(item) for item in found)


def should_scan_file(path: Path) -> bool:
    if any(part in SKIP_SCAN_PARTS for part in path.parts):
        return False
    if not path.is_file():
        return False
    if path.suffix.lower() in TEXT_SCAN_EXTENSIONS:
        return True
    # Some source cache files have no extension. Read extensionless files too.
    return path.suffix == ""


def iter_scan_files(root: Path, paths: Sequence[str]) -> Iterable[Path]:
    yielded: Set[Path] = set()
    for rel in paths:
        if not str(rel or "").strip():
            continue
        base = (root / rel).resolve()
        try:
            base.relative_to(root)
        except Exception:
            # Keep scanning inside the repo only.
            continue
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for path in candidates:
            try:
                resolved = path.resolve()
                resolved.relative_to(root)
            except Exception:
                continue
            if resolved in yielded or not should_scan_file(resolved):
                continue
            yielded.add(resolved)
            yield resolved


def load_extra_ss_ssr_proxy_templates(
    root: Path,
    source_paths: Sequence[str],
    server_override: str,
    starting_sequence: int,
    known_signatures: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    templates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    sequence = starting_sequence
    target = normalize_server_override(server_override)
    for path in iter_scan_files(root, source_paths):
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            skipped.append({"source": rel, "reason": f"read failed: {exc}"})
            continue
        for link in extract_ss_ssr_links_from_text(text):
            proxy, reason = parse_manual_link_line(link)
            if proxy is None:
                skipped.append({"source": rel, "reason": reason, "preview": link[:120]})
                continue
            if str(proxy.get("type") or "").lower() not in {"ss", "ssr"}:
                continue
            apply_ss_ssr_server_override_to_proxy(proxy, target)
            sig = proxy_signature(proxy)
            if sig in known_signatures:
                continue
            known_signatures.add(sig)
            sequence += 1
            proxy = dict(proxy)
            proxy["_manual_index"] = sequence
            proxy["_manual_original_name"] = str(proxy.get("name") or f"SS SSR Source {sequence:03d}")
            proxy["_manual_source"] = rel
            proxy["_ss_ssr_extra_source"] = True
            templates.append(proxy)
    return templates, skipped


def load_manual_proxy_templates(root: Path, input_files: Sequence[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    templates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    sequence = 0
    for rel in input_files:
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            sequence += 1
            proxy, reason = parse_manual_link_line(line)
            if proxy is None:
                skipped.append({
                    "source": rel,
                    "line": line_no,
                    "reason": reason,
                    "preview": line[:120],
                })
                continue
            proxy = dict(proxy)
            proxy["_manual_index"] = sequence
            proxy["_manual_original_name"] = str(proxy.get("name") or f"Input {sequence:03d}")
            templates.append(proxy)
    return templates, skipped


def prepare_manual_proxies(templates: Sequence[Dict[str, Any]], existing_names: Set[str]) -> List[Dict[str, Any]]:
    used_names = set(existing_names)
    out: List[Dict[str, Any]] = []
    for local_index, template in enumerate(templates, start=1):
        proxy = {k: v for k, v in template.items() if not str(k).startswith("_")}
        original_index = parse_int(template.get("_manual_index"), local_index)
        preferred = str(template.get("_manual_original_name") or proxy.get("name") or f"Input {original_index:03d}")
        proxy["name"] = make_manual_name(original_index, preferred, used_names)
        out.append(proxy)
    return out


def inject_manual_input_proxies(data: Dict[str, Any], manual_templates: Sequence[Dict[str, Any]], tuning: Tuning) -> Dict[str, Any]:
    if not manual_templates:
        return {"manual_input_count": 0, "manual_inserted": 0, "manual_replaced": 0, "manual_group_count": 0}

    proxies = data.get("proxies")
    if not isinstance(proxies, list):
        proxies = []
    existing = [item for item in proxies if isinstance(item, dict)]
    existing_names = {str(item.get("name") or "").strip() for item in existing if str(item.get("name") or "").strip()}
    manual_proxies = prepare_manual_proxies(manual_templates, existing_names)
    manual_names = [str(item.get("name")) for item in manual_proxies if item.get("name")]
    manual_name_set = set(manual_names)

    remaining: List[Dict[str, Any]] = []
    replaced = 0
    for item in existing:
        name = str(item.get("name") or "").strip()
        if name in manual_name_set:
            replaced += 1
            continue
        remaining.append(item)

    # Manual links are placed at the top of the account section so their order
    # follows input/links.txt exactly before generated/filtered accounts.
    data["proxies"] = manual_proxies + remaining

    upsert_group(data, build_select_group(MANUAL_GROUP_SELECT, manual_names + ["DIRECT"]))
    upsert_group(data, build_fallback_group(MANUAL_GROUP_FALLBACK, manual_names, tuning))
    upsert_group(data, build_urltest_group(MANUAL_GROUP_URLTEST, manual_names, tuning))

    return {
        "manual_input_count": len(manual_templates),
        "manual_inserted": len(manual_proxies),
        "manual_replaced": replaced,
        "manual_group_count": len(manual_names),
        "manual_groups": [MANUAL_GROUP_SELECT, MANUAL_GROUP_FALLBACK, MANUAL_GROUP_URLTEST],
    }


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


def read_delay_map(root: Path) -> Dict[str, float]:
    delays: Dict[str, float] = {}
    for rel in CANDIDATE_SCORE_FILES:
        path = root / rel
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    name = str(row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
                    if not name:
                        continue
                    delay = parse_delay_ms(row)
                    if delay is None:
                        continue
                    old = delays.get(name)
                    if old is None or delay < old:
                        delays[name] = float(delay)
        except Exception:
            continue
    return delays


def smart_ranked_candidates(
    root: Path,
    proxy_names: Sequence[str],
    manual_names: Sequence[str],
    limit: int,
) -> List[str]:
    proxy_set = set(proxy_names)
    manual_set = set(manual_names)
    delays = read_delay_map(root)
    previous: Dict[str, Any] = {}
    cache_path = root / NODE_SCORE_CACHE
    if cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded.get("nodes") if isinstance(loaded.get("nodes"), dict) else loaded
        except Exception:
            previous = {}

    ranked: List[Tuple[float, int, str]] = []
    for order, name in enumerate(proxy_names):
        if name not in proxy_set:
            continue
        score = 0.0
        if name in manual_set:
            score -= 100000.0
        delay = delays.get(name)
        score += delay if delay is not None else 5000.0
        item = previous.get(name) if isinstance(previous, dict) else None
        if isinstance(item, dict):
            try:
                score -= float(item.get("success", 0)) * 10.0
                score += float(item.get("fail", 0)) * 100.0
            except Exception:
                pass
        ranked.append((score, order, name))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return unique_keep_order(name for _, _, name in ranked)[: max(1, int(limit))]


def write_node_score_cache(root: Path, summary: Dict[str, Any]) -> Optional[str]:
    cache_path = root / NODE_SCORE_CACHE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    delays = read_delay_map(root)
    seen_names: Set[str] = set()
    for result in summary.get("results") or []:
        if not isinstance(result, dict) or not result.get("ok"):
            continue
        path = root / str(result.get("file") or "")
        if not path.exists():
            continue
        try:
            data = read_yaml(path)
        except Exception:
            continue
        for name in get_proxy_names(data):
            seen_names.add(name)
    now = datetime.now(timezone.utc).isoformat()
    nodes: Dict[str, Any] = {}
    old_path = cache_path
    if old_path.exists():
        try:
            old = json.loads(old_path.read_text(encoding="utf-8"))
            old_nodes = old.get("nodes", {}) if isinstance(old, dict) else {}
            if isinstance(old_nodes, dict):
                nodes.update(old_nodes)
        except Exception:
            pass
    for name in sorted(seen_names):
        current = nodes.get(name) if isinstance(nodes.get(name), dict) else {}
        current["last_seen"] = now
        current["avg_delay"] = delays.get(name, current.get("avg_delay"))
        current["manual"] = is_manual_name(name)
        current.setdefault("success", 0)
        current.setdefault("fail", 0)
        nodes[name] = current
    payload = {
        "generated_at": now,
        "policy": "manual first, historical failure penalty, delay-based smart ranking when CSV telemetry exists",
        "nodes": nodes,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(cache_path.relative_to(root))


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

    smart = smart_ranked_candidates(root, proxy_names, manual_names, args.max_combined)
    combined = unique_keep_order(manual_names + smart + stable + non_manual[: args.max_combined] + proxy_names[: args.max_combined])
    actions: List[str] = []
    counts: Dict[str, int] = {}

    if smart:
        action, count = upsert_group(data, build_urltest_group(SMART_GROUP_BEST, smart, tuning))
        actions.append(f"{action}:{SMART_GROUP_BEST}")
        counts[SMART_GROUP_BEST] = count

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
        MANUAL_GROUP_FALLBACK,
        MANUAL_GROUP_SELECT,
        MANUAL_GROUP_URLTEST,
        SMART_GROUP_BEST,
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
        group_name = str(group.get("name") or "")
        if group_name in {main_name, MANUAL_GROUP_SELECT}:
            continue
        if str(group.get("type") or "").lower() in {"select", "selector"}:
            if put_refs_front(
                group,
                [MANUAL_GROUP_FALLBACK, MANUAL_GROUP_SELECT, SMART_GROUP_BEST, "SAT-SET", "ANTI-BENGONG", "BEST-STABLE", "DIRECT"],
                data,
                proxy_names,
            ):
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
        "smart_count": len(smart),
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


def validate_openclash_data(data: Dict[str, Any], drop_types: Set[str]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    proxies = data.get("proxies") or []
    groups = data.get("proxy-groups") or []
    if not isinstance(proxies, list) or not proxies:
        errors.append("proxies is empty or missing")
        proxies = []
    if not isinstance(groups, list) or not groups:
        errors.append("proxy-groups is empty or missing")
        groups = []

    names: List[str] = []
    for idx, proxy in enumerate(proxies):
        if not isinstance(proxy, dict):
            errors.append(f"proxy index {idx} is not a mapping")
            continue
        name = str(proxy.get("name") or "").strip()
        ptype = str(proxy.get("type") or "").strip().lower()
        if not name:
            errors.append(f"proxy index {idx} has no name")
        else:
            names.append(name)
        if ptype in drop_types:
            errors.append(f"blocked proxy type still exists: {name or idx} type={ptype}")
        if not proxy.get("server") and ptype not in {"direct", "reject"}:
            warnings.append(f"proxy has no server: {name or idx}")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    for name in duplicates:
        errors.append(f"duplicate proxy name: {name}")

    proxy_set = set(names)
    group_names = {str(g.get("name") or "").strip() for g in groups if isinstance(g, dict) and str(g.get("name") or "").strip()}
    allowed = proxy_set | group_names | SPECIAL_REFS
    for idx, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"proxy-group index {idx} is not a mapping")
            continue
        gname = str(group.get("name") or "").strip()
        gtype = str(group.get("type") or "").strip().lower()
        if not gname:
            errors.append(f"proxy-group index {idx} has no name")
        if gtype not in {"select", "url-test", "fallback", "load-balance", "relay"}:
            warnings.append(f"uncommon proxy-group type: {gname} type={gtype}")
        refs = group.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"proxy-group has no proxies: {gname or idx}")
            continue
        for ref in refs:
            value = str(ref).strip()
            if value == gname:
                errors.append(f"proxy-group self reference: {gname}")
            if value not in allowed:
                errors.append(f"unknown proxy-group reference: {gname} -> {value}")
        for key in RISKY_GROUP_KEYS:
            if key in group:
                errors.append(f"risky group key still exists: {gname}.{key}")
    for key in RISKY_ROOT_KEYS:
        if key in data:
            errors.append(f"risky root key still exists: {key}")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def write_text_report(root: Path, summary: Dict[str, Any]) -> str:
    path = root / TEXT_REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("SumberYAML Smart Safe Generator Report")
    lines.append(f"Generated at UTC: {summary.get('generated_at', '')}")
    lines.append(f"Mode: {summary.get('mode', '')}")
    lines.append(f"Files processed: {summary.get('files_processed', 0)}")
    lines.append(f"Manual templates loaded: {summary.get('manual_input_templates_loaded', 0)}")
    lines.append(f"Manual skipped/unparsable: {len(summary.get('manual_input_skipped_unparsable') or [])}")
    lines.append(f"Manual server override: {summary.get('manual_server_override', '')}")
    lines.append(f"Manual server override policy/types: {', '.join(summary.get('manual_server_override_types') or [])}")
    lines.append(f"Blocked proxy types: {', '.join(summary.get('drop_proxy_types') or [])}")
    lines.append("")
    lines.append("Generated/processed outputs:")
    for result in summary.get("results") or []:
        if not isinstance(result, dict):
            continue
        status = "OK" if result.get("ok") else "FAILED"
        validation = result.get("validation") or {}
        lines.append(
            f"- {status} {result.get('file')} | proxies={result.get('proxy_count', 0)} | "
            f"manual={result.get('manual_count', 0)} | smart={result.get('smart_count', 0)} | "
            f"errors={len(validation.get('errors') or [])} | warnings={len(validation.get('warnings') or [])}"
        )
        if result.get("reason"):
            lines.append(f"  reason: {result.get('reason')}")
    lines.append("")
    lines.append("Policy notes:")
    lines.append("- ss/ssr links and proxy objects are removed for OpenClash compatibility.")
    lines.append("- server=104.17.3.81 is applied only to compatible manual vmess/vless/trojan nodes with CDN transport ws/grpc/h2/http.")
    lines.append("- manual_only.yaml contains only compatible trusted manual nodes from input/links.txt/input.txt/links.txt.")
    lines.append("- SMART-BEST uses telemetry CSVs and cache/node_score.json when available; it does not perform destructive filtering.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path.relative_to(root))


def backup_file(path: Path, root: Path, backup_dir: Path) -> Optional[str]:
    if not path.exists():
        return None
    rel = path.relative_to(root)
    target = backup_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return str(target.relative_to(root))


def apply_to_file(path: Path, root: Path, args: argparse.Namespace, backup_dir: Path, manual_templates: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None

    try:
        data = read_yaml(path)
    except Exception as exc:
        return {"file": str(path.relative_to(root)), "ok": False, "reason": f"YAML read failed: {exc}"}

    backup_rel = backup_file(path, root, backup_dir)
    tuning = profile_tuning(path, args)

    manual_injection = inject_manual_input_proxies(data, manual_templates, tuning)
    drop_type_stats = drop_proxy_types_from_data(data, args.drop_proxy_types)
    manual_override_stats = override_manual_servers_in_existing_data(
        data,
        args.manual_server_override,
        args.manual_server_override_types,
    )
    ss_ssr_override_stats = override_ss_ssr_servers_in_data(data, args.ss_ssr_server_override)

    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"file": str(path.relative_to(root)), "ok": False, "reason": "no proxies found"}

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
    validation = validate_openclash_data(data, args.drop_proxy_types)
    if not validation.get("ok"):
        if backup_rel:
            shutil.copy2(root / backup_rel, path)
        return {
            "file": str(path.relative_to(root)),
            "ok": False,
            "reason": "smart-safe validation failed before write",
            "validation": validation,
            "backup": backup_rel,
        }

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
        "manual_injection": manual_injection,
        "manual_server_override": manual_override_stats,
        "dropped_proxy_types": drop_type_stats,
        "ss_ssr_server_override": ss_ssr_override_stats,
        "validation": validation,
        **info,
    }


def create_manual_only_output(
    root: Path,
    args: argparse.Namespace,
    backup_dir: Path,
    manual_templates: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not manual_templates:
        return {"file": MANUAL_ONLY_OUTPUT, "ok": False, "reason": "no compatible manual proxy templates loaded"}
    path = root / MANUAL_ONLY_OUTPUT
    backup_rel = backup_file(path, root, backup_dir) if path.exists() else None
    tuning = Tuning(
        interval=max(60, int(args.fast_interval)),
        fallback_interval=max(60, int(args.fast_fallback_interval)),
        tolerance=max(0, int(args.fast_tolerance)),
    )
    data: Dict[str, Any] = {
        "mixed-port": 7890,
        "allow-lan": True,
        "mode": "rule",
        "log-level": "info",
        "proxies": [],
        "proxy-groups": [],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            f"MATCH,{MANUAL_GROUP_FALLBACK}",
        ],
    }
    manual_injection = inject_manual_input_proxies(data, manual_templates, tuning)
    drop_type_stats = drop_proxy_types_from_data(data, args.drop_proxy_types)
    proxy_names = get_proxy_names(data)
    if not proxy_names:
        return {"file": MANUAL_ONLY_OUTPUT, "ok": False, "reason": "manual_only has no proxies after filtering"}
    info = add_responsive_groups(data, root, path, args, tuning)
    for group in get_groups(data):
        sanitize_group_keys(group, tuning)
    ref_stats = sanitize_group_proxies(data, get_proxy_names(data))
    validation = validate_openclash_data(data, args.drop_proxy_types)
    if not validation.get("ok"):
        return {
            "file": MANUAL_ONLY_OUTPUT,
            "ok": False,
            "reason": "manual_only validation failed before write",
            "validation": validation,
            "backup": backup_rel,
        }
    try:
        write_yaml(path, data)
        read_yaml(path)
    except Exception as exc:
        if backup_rel:
            shutil.copy2(root / backup_rel, path)
        return {"file": MANUAL_ONLY_OUTPUT, "ok": False, "reason": f"manual_only write failed: {exc}", "backup": backup_rel}
    return {
        "file": MANUAL_ONLY_OUTPUT,
        "ok": True,
        "backup": backup_rel,
        "manual_only": True,
        "proxy_count": len(get_proxy_names(data)),
        "manual_count": len([name for name in get_proxy_names(data) if is_manual_name(name)]),
        "manual_injection": manual_injection,
        "dropped_proxy_types": drop_type_stats,
        "reference_repair": ref_stats,
        "validation": validation,
        "tuning": {"interval": tuning.interval, "fallback_interval": tuning.fallback_interval, "tolerance": tuning.tolerance},
        **info,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply safe responsive OpenClash groups without breaking older OpenClash cores.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=DEFAULT_OUTPUT_FILES, help="YAML files to update")
    parser.add_argument("--report", default="output/Validation/smart_safe_report.json")
    parser.add_argument("--manual-only-output", action=argparse.BooleanOptionalAction, default=env_bool("SMART_SAFE_MANUAL_ONLY", True), help="Create output/manual_only.yaml from compatible trusted manual nodes only")
    parser.add_argument(
        "--manual-input-files",
        default=os.getenv("MANUAL_INPUT_FILES", ",".join(MANUAL_INPUT_FILES)),
        help="Comma-separated trusted direct proxy link files to inject into every output YAML",
    )
    parser.add_argument(
        "--extra-ss-ssr-source-paths",
        default=os.getenv("EXTRA_SS_SSR_SOURCE_PATHS", ",".join(EXTRA_SS_SSR_SOURCE_PATHS)),
        help="Comma-separated repo paths to scan for raw ss:// and ssr:// links from other sources/cache files",
    )
    parser.add_argument(
        "--ss-ssr-server-override",
        default=os.getenv("SS_SSR_SERVER_OVERRIDE", SS_SSR_SERVER_OVERRIDE),
        help="Deprecated/no-op in this patch. SS/SSR nodes are removed instead of rewritten.",
    )
    parser.add_argument(
        "--drop-proxy-types",
        default=os.getenv("DROP_PROXY_TYPES", DROP_PROXY_TYPES),
        help="Comma-separated proxy types to remove from output YAML. Default: ss,ssr.",
    )
    parser.add_argument(
        "--manual-server-override",
        default=os.getenv("MANUAL_SERVER_OVERRIDE", MANUAL_SERVER_OVERRIDE),
        help="Force server field for trusted direct proxy nodes loaded from input/links.txt/input.txt/links.txt. Empty value disables override.",
    )
    parser.add_argument(
        "--manual-server-override-types",
        default=os.getenv("MANUAL_SERVER_OVERRIDE_TYPES", MANUAL_SERVER_OVERRIDE_TYPES),
        help="Comma-separated proxy types/policies to rewrite for manual input nodes. Default cdn-compatible rewrites only vmess/vless/trojan using ws/grpc/h2/http and skips Reality/raw TCP.",
    )
    parser.add_argument(
        "--no-extra-ss-ssr-scan",
        action="store_true",
        default=env_bool("DISABLE_EXTRA_SS_SSR_SCAN", True),
        help="Disable scanning extra source/cache files for ss:// and ssr:// links. Default enabled for safety.",
    )
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
    args.manual_input_files = split_env_list(args.manual_input_files) or MANUAL_INPUT_FILES
    args.extra_ss_ssr_source_paths = split_env_list(args.extra_ss_ssr_source_paths) or EXTRA_SS_SSR_SOURCE_PATHS
    args.ss_ssr_server_override = normalize_server_override(args.ss_ssr_server_override)
    args.manual_server_override = normalize_server_override(args.manual_server_override)
    args.drop_proxy_types = {
        item.strip().lower()
        for item in split_env_list(args.drop_proxy_types)
        if item.strip()
    }
    args.manual_server_override_types = {
        item.strip().lower()
        for item in split_env_list(args.manual_server_override_types)
        if item.strip()
    } or {"all"}

    manual_templates, manual_skipped = load_manual_proxy_templates(root, args.manual_input_files)

    # Apply the requested server override to every trusted manual input node.
    # Required behavior for input/links.txt: if the node still has a normal/original
    # server/IP, rewrite only the server field to 104.17.3.81.
    manual_server_overridden = 0
    manual_server_seen = 0
    manual_ss_ssr_overridden = 0
    known_signatures: Set[str] = set()
    for proxy in manual_templates:
        if type_allowed_for_manual_server_override(proxy, args.manual_server_override_types):
            manual_server_seen += 1
        if apply_manual_server_override_to_proxy(
            proxy,
            args.manual_server_override,
            args.manual_server_override_types,
        ):
            manual_server_overridden += 1
        # SS/SSR links are skipped before this point; this no-op counter is kept
        # only for backward-compatible reports.
        if apply_ss_ssr_server_override_to_proxy(proxy, args.ss_ssr_server_override):
            manual_ss_ssr_overridden += 1
        known_signatures.add(proxy_signature(proxy))

    # SS/SSR import from other sources is disabled in this patch because those
    # node types caused OpenClash startup errors for the target environment.
    extra_templates: List[Dict[str, Any]] = []
    extra_skipped: List[Dict[str, Any]] = []
    if not args.no_extra_ss_ssr_scan:
        # Keep the CLI flag backward-compatible, but do not import the results.
        # Users can see skipped info in the report without breaking output YAML.
        _, extra_skipped = load_extra_ss_ssr_proxy_templates(
            root=root,
            source_paths=args.extra_ss_ssr_source_paths,
            server_override=args.ss_ssr_server_override,
            starting_sequence=len(manual_templates),
            known_signatures=known_signatures,
        )

    combined_templates = list(manual_templates)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = root / "output" / "Backup" / f"openclash-safe-satset-{stamp}"
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for rel in args.files:
        # manual_only.yaml is generated from scratch after normal files.
        if str(rel).replace("\\", "/") == MANUAL_ONLY_OUTPUT:
            continue
        result = apply_to_file(root / rel, root, args, backup_dir, combined_templates)
        if result is not None:
            results.append(result)
    if args.manual_only_output:
        manual_only_result = create_manual_only_output(root, args, backup_dir, combined_templates)
        if manual_only_result is not None:
            results.append(manual_only_result)

    summary = {
        "ok": all(item.get("ok") for item in results) if results else False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "apply_openclash_responsive_stability.py",
        "mode": "smart-safe-generator-manual-only-cdn-104",
        "files_processed": len(results),
        "backup_dir": str(backup_dir.relative_to(root)) if backup_dir.exists() else None,
        "trusted_manual_policy": "Compatible vmess/vless/trojan direct proxy links from input/links.txt/input.txt/links.txt are injected into every processed output YAML and manual_only.yaml when they can be converted into valid Clash proxy objects. ss:// and ssr:// links are intentionally skipped/removed for OpenClash compatibility.",
        "manual_input_files": args.manual_input_files,
        "manual_input_templates_loaded": len(manual_templates),
        "manual_server_override": args.manual_server_override,
        "manual_server_override_types": sorted(args.manual_server_override_types),
        "manual_input_server_seen": manual_server_seen,
        "manual_input_server_overridden": manual_server_overridden,
        "manual_input_ss_ssr_server_overridden": manual_ss_ssr_overridden,
        "manual_input_skipped_unparsable": manual_skipped,
        "drop_proxy_types": sorted(args.drop_proxy_types),
        "extra_ss_ssr_scan_enabled": False,
        "extra_ss_ssr_source_paths": [],
        "extra_ss_ssr_templates_loaded": 0,
        "extra_ss_ssr_skipped_unparsable": extra_skipped,
        "ss_ssr_server_override": "disabled; ss/ssr removed",
        "total_injected_templates_loaded": len(combined_templates),
        "manual_input_groups": [MANUAL_GROUP_SELECT, MANUAL_GROUP_FALLBACK, MANUAL_GROUP_URLTEST, SMART_GROUP_BEST, "fallback-link", "best-link"],
        "compatibility_policy": {
            "root_meta_options_removed_by_default": RISKY_ROOT_KEYS,
            "group_fields_removed_by_default": RISKY_GROUP_KEYS,
            "dns_not_forced": True,
            "zero_delay_not_possible": "OpenClash still needs health-check and fallback intervals; this patch uses safer fast intervals instead of invalid zero-delay settings.",
            "manual_server_override": "For compatible trusted direct proxy nodes from input/links.txt/input.txt/links.txt, only the server field is rewritten when policy/type allows it. Default policy cdn-compatible only rewrites vmess/vless/trojan using ws/grpc/h2/http and skips Reality/raw TCP. Port, UUID, password, TLS/SNI, WS Host, and transport settings are preserved.",
            "ss_ssr_policy": "ss and ssr proxy types are skipped from manual input, not imported from extra sources, removed from existing output, and removed from proxy-group references.",
        },
        "results": results,
    }
    node_score_cache = write_node_score_cache(root, summary)
    summary["node_score_cache"] = node_score_cache
    text_report = write_text_report(root, summary)
    summary["text_report"] = text_report
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OpenClash smart-safe report: {report_path}")
    print(f"Text report: {root / text_report}")
    if node_score_cache:
        print(f"Node score cache: {root / node_score_cache}")
    for item in results:
        status = "OK" if item.get("ok") else "SKIP"
        tuning = item.get("tuning") or {}
        print(
            f"[{status}] {item.get('file')} "
            f"proxy={item.get('proxy_count', 0)} "
            f"manual={item.get('manual_count', 0)} "
            f"manual_input={(item.get('manual_injection') or {}).get('manual_inserted', 0)} "
            f"manual104={(item.get('manual_server_override') or {}).get('changed', 0)} "
            f"drop_ssr={(item.get('dropped_proxy_types') or {}).get('removed', 0)} "
            f"stable={item.get('stable_count', 0)} "
            f"smart={item.get('smart_count', 0)} "
            f"interval={tuning.get('interval', '-')} "
            f"fallback={tuning.get('fallback_interval', '-')}"
        )
        if not item.get("ok"):
            print(f"  reason: {item.get('reason')}")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

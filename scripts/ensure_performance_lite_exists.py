#!/usr/bin/env python3
"""Force-create output/SingBox/performance-lite.json for SumberYAML.

This script is intentionally defensive. It creates a small sing-box profile even
when the normal performance builder is skipped, missing, or has no complete
source profile yet.

Manual/trusted accounts from input/links.txt and input.txt are always preserved
and are never filtered, ping-tested, quarantined, or removed.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
SINGBOX = OUTPUT / "SingBox"
PERF = OUTPUT / "Performance"
V2RAYBOX = OUTPUT / "V2RayBox"
NEKOBOX = OUTPUT / "NekoBox"

DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"

SOURCE_JSON_CANDIDATES = [
    "output/SingBox/mobile-stable-safe.json",
    "output/SingBox/import-ready.json",
    "output/SingBox/best-stable-safe.json",
    "output/SingBox/latest-safe.json",
    "output/SingBox/lengkap-safe.json",
    "output/SingBox/mobile-stable.json",
    "output/SingBox/best-stable.json",
    "output/SingBox/latest.json",
    "output/SingBox/lengkap.json",
]

GROUP_TYPES = {"selector", "urltest"}
SPECIAL_TYPES = {"direct", "block", "dns", "selector", "urltest"}


def ensure_dirs() -> None:
    for path in [OUTPUT, SINGBOX, PERF, V2RAYBOX, NEKOBOX]:
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        item = str(item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def unique_outbounds(outbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        tag = str(outbound.get("tag") or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(outbound)
    return result


def b64decode_maybe(value: str) -> str:
    raw = (value or "").strip()
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode()).decode("utf-8", errors="replace")


def b64encode_json(data: dict[str, Any]) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_tag(name: str, prefix: str = "LINK") -> str:
    name = unquote(str(name or "")).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = "MANUAL"
    if not re.match(r"(?i)^(LINK|MANUAL)\b", name):
        name = f"{prefix} {name}"
    return name[:96]


def unique_tag(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while True:
        candidate = f"{base} #{idx}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        idx += 1


def read_input_links() -> list[str]:
    links: list[str] = []
    for rel in ["input/links.txt", "input.txt"]:
        path = ROOT / rel
        if not path.exists():
            continue
        for line in read_text(path).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("vmess://", "vless://", "trojan://", "ss://")):
                links.append(line)
    return unique(links)


def parse_transport(query: dict[str, list[str]]) -> dict[str, Any] | None:
    network = (query.get("type") or query.get("network") or query.get("net") or [""])[0].lower()
    host = (query.get("host") or query.get("Host") or [""])[0]
    path = (query.get("path") or [""])[0]
    service_name = (query.get("serviceName") or query.get("service_name") or [""])[0]
    if network in {"ws", "websocket"}:
        transport: dict[str, Any] = {"type": "ws"}
        if path:
            transport["path"] = unquote(path)
        if host:
            transport["headers"] = {"Host": host}
        return transport
    if network == "grpc":
        transport = {"type": "grpc"}
        if service_name:
            transport["service_name"] = service_name
        return transport
    if network in {"http", "h2"}:
        transport = {"type": "http"}
        if host:
            transport["host"] = [host]
        if path:
            transport["path"] = unquote(path)
        return transport
    if network in {"httpupgrade", "http-upgrade"}:
        transport = {"type": "httpupgrade"}
        if path:
            transport["path"] = unquote(path)
        if host:
            transport["host"] = host
        return transport
    return None


def parse_tls(query: dict[str, list[str]], default_server_name: str = "") -> dict[str, Any] | None:
    security = (query.get("security") or query.get("tls") or [""])[0].lower()
    if security not in {"tls", "reality"}:
        return None
    tls: dict[str, Any] = {"enabled": True}
    sni = (query.get("sni") or query.get("serverName") or query.get("peer") or [default_server_name])[0]
    if sni:
        tls["server_name"] = sni
    fp = (query.get("fp") or query.get("fingerprint") or [""])[0]
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    if security == "reality":
        public_key = (query.get("pbk") or query.get("publicKey") or [""])[0]
        short_id = (query.get("sid") or query.get("shortId") or [""])[0]
        reality: dict[str, Any] = {"enabled": True}
        if public_key:
            reality["public_key"] = public_key
        if short_id:
            reality["short_id"] = short_id
        tls["reality"] = reality
    return tls


def link_to_singbox_outbound(link: str, used: set[str]) -> dict[str, Any] | None:
    try:
        if link.startswith("vmess://"):
            data = json.loads(b64decode_maybe(link[len("vmess://") :]))
            tag = unique_tag(normalize_tag(data.get("ps") or data.get("name") or "VMESS"), used)
            outbound: dict[str, Any] = {
                "type": "vmess",
                "tag": tag,
                "server": str(data.get("add") or data.get("server") or ""),
                "server_port": safe_int(data.get("port"), 443),
                "uuid": str(data.get("id") or data.get("uuid") or ""),
                "security": str(data.get("scy") or data.get("security") or "auto"),
                "alter_id": safe_int(data.get("aid") or data.get("alterId"), 0),
            }
            tls = str(data.get("tls") or "").lower()
            if tls in {"tls", "true", "1"}:
                outbound["tls"] = {"enabled": True}
                sni = data.get("sni") or data.get("host")
                if sni:
                    outbound["tls"]["server_name"] = str(sni)
            network = str(data.get("net") or "").lower()
            if network == "ws":
                transport: dict[str, Any] = {"type": "ws"}
                if data.get("path"):
                    transport["path"] = str(data.get("path"))
                if data.get("host"):
                    transport["headers"] = {"Host": str(data.get("host"))}
                outbound["transport"] = transport
            return outbound if outbound.get("server") and outbound.get("uuid") else None

        parsed = urlparse(link)
        scheme = parsed.scheme.lower()
        if scheme not in {"vless", "trojan", "ss"}:
            return None
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_name = unquote(parsed.fragment or "").strip() or scheme.upper()
        tag = unique_tag(normalize_tag(raw_name), used)
        host = parsed.hostname or ""
        port = int(parsed.port or 443)
        if scheme == "vless":
            outbound = {
                "type": "vless",
                "tag": tag,
                "server": host,
                "server_port": port,
                "uuid": unquote(parsed.username or ""),
            }
            flow = (query.get("flow") or [""])[0]
            if flow:
                outbound["flow"] = flow
        elif scheme == "trojan":
            outbound = {
                "type": "trojan",
                "tag": tag,
                "server": host,
                "server_port": port,
                "password": unquote(parsed.username or ""),
            }
        else:
            # Shadowsocks userinfo can be method:password or base64(method:password)
            userinfo = unquote(parsed.username or "")
            if ":" not in userinfo:
                try:
                    userinfo = b64decode_maybe(userinfo)
                except Exception:
                    pass
            method, password = (userinfo.split(":", 1) + [""])[:2] if ":" in userinfo else ("2022-blake3-aes-128-gcm", userinfo)
            outbound = {
                "type": "shadowsocks",
                "tag": tag,
                "server": host,
                "server_port": port,
                "method": method,
                "password": password,
            }
        tls = parse_tls(query, host)
        if tls:
            outbound["tls"] = tls
        transport = parse_transport(query)
        if transport:
            outbound["transport"] = transport
        return outbound if outbound.get("server") else None
    except Exception as exc:
        print(f"[WARN] Failed to parse link: {exc}")
        return None


def outbound_is_node(outbound: dict[str, Any]) -> bool:
    typ = str(outbound.get("type") or "").lower()
    tag = str(outbound.get("tag") or "")
    if not tag or typ in SPECIAL_TYPES:
        return False
    return typ in {"vless", "vmess", "trojan", "shadowsocks", "hysteria2", "tuic", "wireguard"}


def outbound_is_manual(outbound: dict[str, Any]) -> bool:
    tag = str(outbound.get("tag") or "")
    return bool(re.match(r"(?i)^(LINK|MANUAL)\b", tag))


def normalize_tun_inbounds(inbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not inbounds:
        return [
            {
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30"],
                "auto_route": True,
                "strict_route": False,
                "sniff": True,
            },
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7893, "sniff": True},
        ]
    result: list[dict[str, Any]] = []
    has_mixed = False
    has_tun = False
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        item = deepcopy(inbound)
        typ = str(item.get("type") or "").lower()
        if typ == "tun":
            has_tun = True
            addresses: list[str] = []
            for key in ["address", "inet4_address", "inet6_address"]:
                val = item.pop(key, None)
                if isinstance(val, list):
                    addresses += [str(x) for x in val if x]
                elif val:
                    addresses.append(str(val))
            item["address"] = unique(addresses) or ["172.19.0.1/30"]
            # Remove legacy route fields that error in newer sing-box.
            for key in ["inet4_route_address", "inet6_route_address", "inet4_route_exclude_address", "inet6_route_exclude_address"]:
                item.pop(key, None)
            item.pop("dns_mode", None)
            item.setdefault("auto_route", True)
            item.setdefault("strict_route", False)
            item.setdefault("sniff", True)
        if typ == "mixed":
            has_mixed = True
            item.setdefault("listen", "127.0.0.1")
            item.setdefault("listen_port", 7893)
            item.setdefault("sniff", True)
        result.append(item)
    if not has_tun:
        result.insert(0, {"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"], "auto_route": True, "strict_route": False, "sniff": True})
    if not has_mixed:
        result.append({"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7893, "sniff": True})
    return result


def stable_dns() -> dict[str, Any]:
    # Legacy DNS format remains broadly compatible with many Android sing-box clients.
    return {
        "servers": [
            {"tag": "cloudflare", "address": "1.1.1.1"},
            {"tag": "google", "address": "8.8.8.8"},
        ],
        "final": "cloudflare",
    }


def sanitize_outbound_for_import(outbound: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(outbound)
    typ = str(item.get("type") or "").lower()
    # Legacy/compat: selector.default errors on some Android clients.
    item.pop("default", None)
    if typ in {"selector", "urltest"}:
        item["outbounds"] = unique([str(x) for x in item.get("outbounds", []) if x])
        item.setdefault("interrupt_exist_connections", False)
        if typ == "urltest":
            item.setdefault("url", DEFAULT_TEST_URL)
            item.setdefault("interval", "3m")
            item.setdefault("tolerance", 80)
            item.setdefault("idle_timeout", "2h")
    # Remove fields that often trigger unknown-field on mixed sing-box client versions.
    for key in ["tcp_fast_open", "tcp_multi_path", "udp_fragment", "domain_strategy"]:
        item.pop(key, None)
    return item


def choose_base_config() -> tuple[dict[str, Any], str]:
    for rel in SOURCE_JSON_CANDIDATES:
        path = ROOT / rel
        data = load_json(path)
        if data.get("outbounds"):
            return data, rel
    return {}, "generated-minimal"


def make_performance_config(max_nodes: int) -> dict[str, Any]:
    base, source = choose_base_config()
    used_tags: set[str] = set()
    base_outbounds = [sanitize_outbound_for_import(x) for x in base.get("outbounds", []) if isinstance(x, dict)]

    direct = next((x for x in base_outbounds if x.get("tag") == "DIRECT" and x.get("type") == "direct"), None) or {"type": "direct", "tag": "DIRECT"}
    nodes = [x for x in base_outbounds if outbound_is_node(x) and not outbound_is_manual(x)]
    manual_existing = [x for x in base_outbounds if outbound_is_node(x) and outbound_is_manual(x)]

    # Keep top N generated nodes, but keep all manual accounts.
    selected_nodes = nodes[: max(0, max_nodes)]

    manual_links = read_input_links()
    manual_from_links: list[dict[str, Any]] = []
    used_tags = {str(x.get("tag")) for x in selected_nodes + manual_existing if x.get("tag")}
    for link in manual_links:
        outbound = link_to_singbox_outbound(link, used_tags)
        if outbound:
            manual_from_links.append(outbound)

    all_nodes = unique_outbounds(selected_nodes + manual_existing + manual_from_links)
    node_tags = [str(x.get("tag")) for x in all_nodes if x.get("tag")]
    manual_tags = [str(x.get("tag")) for x in all_nodes if outbound_is_manual(x)]

    performance_group = {
        "type": "urltest",
        "tag": "PERFORMANCE-LITE",
        "outbounds": node_tags or ["DIRECT"],
        "url": DEFAULT_TEST_URL,
        "interval": "3m",
        "tolerance": 80,
        "idle_timeout": "2h",
        "interrupt_exist_connections": False,
    }
    best_link_group = None
    if manual_tags:
        best_link_group = {
            "type": "urltest",
            "tag": "best-link",
            "outbounds": manual_tags,
            "url": DEFAULT_TEST_URL,
            "interval": "3m",
            "tolerance": 80,
            "idle_timeout": "2h",
            "interrupt_exist_connections": False,
        }

    proxy_choices = ["PERFORMANCE-LITE"]
    if best_link_group:
        proxy_choices.append("best-link")
    proxy_choices.append("DIRECT")
    proxy_selector = {
        "type": "selector",
        "tag": "PROXY",
        "outbounds": unique(proxy_choices),
        "interrupt_exist_connections": False,
    }

    outbounds = unique_outbounds([direct, proxy_selector, performance_group] + ([best_link_group] if best_link_group else []) + all_nodes)
    tags = {str(x.get("tag")) for x in outbounds if x.get("tag")}
    for outbound in outbounds:
        if str(outbound.get("type")) in GROUP_TYPES:
            outbound["outbounds"] = [x for x in outbound.get("outbounds", []) if x in tags]
            if not outbound["outbounds"]:
                outbound["outbounds"] = ["DIRECT"]

    config = {
        "log": {"level": "warn", "timestamp": True},
        "dns": stable_dns(),
        "inbounds": normalize_tun_inbounds(base.get("inbounds", [])),
        "outbounds": outbounds,
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "DIRECT"},
            ],
            "final": "PROXY" if "PROXY" in tags else "DIRECT",
            "auto_detect_interface": True,
        },
        "experimental": {"cache_file": {"enabled": True}},
    }
    config.setdefault("_summary_source", source)
    return config


def extract_links_from_text_file(path: Path) -> list[str]:
    text = read_text(path)
    out: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if item.startswith(("vmess://", "vless://", "trojan://", "ss://")):
            out.append(item)
    return out


def build_subscription_outputs(max_lines: int) -> dict[str, Any]:
    links: list[str] = []
    # Trusted input links must always be kept first and unlimited.
    manual_links = read_input_links()
    links += manual_links
    for rel in [
        "output/V2RayBox/mobile-stable.txt",
        "output/V2RayBox/best-stable.txt",
        "output/V2RayBox/latest.txt",
        "output/V2RayBox/all.txt",
        "output/NekoBox/mobile-stable.txt",
        "output/NekoBox/latest.txt",
        "output/NekoBox/all.txt",
    ]:
        for link in extract_links_from_text_file(ROOT / rel):
            links.append(link)
    # Keep all manual and add up to max_lines extras.
    manual_set = set(manual_links)
    extras = [x for x in unique(links) if x not in manual_set]
    final_links = manual_links + extras[: max(0, max_lines)]
    final_text = "\n".join(unique(final_links)).strip() + ("\n" if final_links else "")
    for base in [V2RAYBOX, NEKOBOX]:
        write_text(base / "performance-lite.txt", final_text)
        encoded = base64.b64encode(final_text.encode()).decode() if final_text else ""
        write_text(base / "performance-lite_base64.txt", encoded + ("\n" if encoded else ""))
    return {"manual_links": len(manual_links), "subscription_links": len(final_links)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-nodes", type=int, default=int(__import__("os").environ.get("PERFORMANCE_LITE_MAX_NODES", "10")))
    parser.add_argument("--subscription-max-lines", type=int, default=int(__import__("os").environ.get("PERFORMANCE_SUBSCRIPTION_MAX_LINES", "30")))
    args = parser.parse_args()

    ensure_dirs()
    config = make_performance_config(max_nodes=args.max_nodes)
    source = config.pop("_summary_source", "unknown")
    dump_json(SINGBOX / "performance-lite.json", config)

    raw_url = "https://raw.githubusercontent.com/adiorany3/SumberYAML/main/output/SingBox/performance-lite.json"
    cdn_url = "https://cdn.jsdelivr.net/gh/adiorany3/SumberYAML@main/output/SingBox/performance-lite.json"
    write_text(SINGBOX / "performance-lite-raw-url.txt", raw_url + "\n")
    write_text(SINGBOX / "performance-lite-cdn-url.txt", cdn_url + "\n")

    sub_summary = build_subscription_outputs(args.subscription_max_lines)
    outbounds = config.get("outbounds", []) if isinstance(config.get("outbounds"), list) else []
    node_count = sum(1 for x in outbounds if isinstance(x, dict) and outbound_is_node(x))
    manual_count = sum(1 for x in outbounds if isinstance(x, dict) and outbound_is_manual(x))
    summary = {
        "ok": True,
        "generated_at": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"),
        "source": source,
        "path": "output/SingBox/performance-lite.json",
        "node_count": node_count,
        "manual_node_count": manual_count,
        "outbound_count": len(outbounds),
        "subscription": sub_summary,
        "note": "Trusted input/links.txt and input.txt accounts are preserved without filtering.",
    }
    dump_json(PERF / "summary_ensure_performance_lite.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

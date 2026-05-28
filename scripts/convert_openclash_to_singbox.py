#!/usr/bin/env python3
"""
Convert OpenClash/Mihomo YAML profiles into sing-box JSON profiles.

Designed for adiorany3/SumberYAML style outputs:
- input:  output/lengkap.yaml, output/lengkap_alive.yaml, output/strict_alive.yaml, etc.
- output: output/SingBox/<profile>.json

Default output targets sing-box 1.11+ without deprecated block/dns special outbounds:
- no outbound type "block"
- no outbound type "dns"
- route rules use action: route / reject / hijack-dns

It can also generate DNS/TUN compatibility variants when needed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

DEFAULT_TEST_URL = "http://www.gstatic.com/generate_204"
DEFAULT_BEST_PING_CSVS = [
    "output/BestPing/top5_indonesia_ping.csv",
    "output/BestPing/top5_best_ping.csv",
    "output/Alive/alive.csv",
    "output/Alive/check_result.csv",
]

DEFAULT_BEST_PING_SOURCE_YAMLS = [
    "output/strict_alive.yaml",
    "output/lengkap_alive.yaml",
    "output/lengkap.yaml",
]

DEFAULT_INPUTS = [
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/streaming.yaml",
    "output/social_media.yaml",
    "output/working.yaml",
    "output/general.yaml",
]

PRIVATE_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "224.0.0.0/4",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

RESERVED_TAGS = {
    "DIRECT",
    "direct",
    "REJECT",
    "reject",
    "GLOBAL",
    "GLOBAL DIRECT",
    "PASS",
    "PASSIVE",
}


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def clean_tag(value: Any, fallback: str = "proxy") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def unique_tag(name: str, used: set[str]) -> str:
    base = clean_tag(name)
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    out = f"{base} {idx}"
    used.add(out)
    return out


def read_text(path_or_url: str) -> str:
    value = str(path_or_url)
    if value.startswith(("http://", "https://")):
        if requests is None:
            raise RuntimeError("requests belum tersedia untuk membaca URL")
        response = requests.get(value, timeout=45)
        response.raise_for_status()
        return response.text
    return Path(value).read_text(encoding="utf-8")


def load_yaml(path_or_url: str) -> Dict[str, Any]:
    text = read_text(path_or_url)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root harus berupa mapping/object: {path_or_url}")
    return data


def tls_options(proxy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not as_bool(proxy.get("tls"), False):
        return None

    server_name = (
        proxy.get("servername")
        or proxy.get("sni")
        or proxy.get("peer")
        or proxy.get("host")
        or ""
    )

    tls: Dict[str, Any] = {
        "enabled": True,
    }
    if server_name:
        tls["server_name"] = str(server_name)
    if "skip-cert-verify" in proxy:
        tls["insecure"] = as_bool(proxy.get("skip-cert-verify"), False)
    elif "skip_cert_verify" in proxy:
        tls["insecure"] = as_bool(proxy.get("skip_cert_verify"), False)

    alpn = proxy.get("alpn")
    if isinstance(alpn, list) and alpn:
        tls["alpn"] = [str(item) for item in alpn if str(item).strip()]
    elif isinstance(alpn, str) and alpn.strip():
        tls["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]

    fingerprint = proxy.get("client-fingerprint") or proxy.get("fingerprint")
    if fingerprint:
        tls["utls"] = {
            "enabled": True,
            "fingerprint": str(fingerprint),
        }

    return tls


def ws_transport(proxy: Dict[str, Any]) -> Dict[str, Any]:
    ws_opts = proxy.get("ws-opts") or proxy.get("ws_opts") or {}
    if not isinstance(ws_opts, dict):
        ws_opts = {}

    headers = ws_opts.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}

    host = (
        headers.get("Host")
        or headers.get("host")
        or proxy.get("host")
        or proxy.get("servername")
        or proxy.get("sni")
        or ""
    )

    out: Dict[str, Any] = {
        "type": "ws",
        "path": str(ws_opts.get("path") or proxy.get("path") or "/"),
    }

    final_headers: Dict[str, str] = {}
    for key, value in headers.items():
        if value is not None and str(value).strip():
            final_headers[str(key)] = str(value)
    if host and "Host" not in final_headers and "host" not in final_headers:
        final_headers["Host"] = str(host)
    if final_headers:
        out["headers"] = final_headers

    early_data_header = ws_opts.get("early-data-header-name") or ws_opts.get("early_data_header_name")
    if early_data_header:
        out["early_data_header_name"] = str(early_data_header)

    return out


def grpc_transport(proxy: Dict[str, Any]) -> Dict[str, Any]:
    grpc_opts = proxy.get("grpc-opts") or proxy.get("grpc_opts") or {}
    if not isinstance(grpc_opts, dict):
        grpc_opts = {}

    service_name = (
        grpc_opts.get("grpc-service-name")
        or grpc_opts.get("grpc_service_name")
        or grpc_opts.get("serviceName")
        or grpc_opts.get("service_name")
        or proxy.get("serviceName")
        or proxy.get("service_name")
        or ""
    )

    out: Dict[str, Any] = {"type": "grpc"}
    if service_name:
        out["service_name"] = str(service_name)
    return out


def http_upgrade_transport(proxy: Dict[str, Any]) -> Dict[str, Any]:
    opts = proxy.get("http-opts") or proxy.get("http_opts") or {}
    if not isinstance(opts, dict):
        opts = {}
    out: Dict[str, Any] = {"type": "httpupgrade"}
    path = opts.get("path") or proxy.get("path")
    if isinstance(path, list):
        path = path[0] if path else "/"
    if path:
        out["path"] = str(path)
    host = opts.get("host") or proxy.get("host")
    if isinstance(host, list):
        host = host[0] if host else ""
    if host:
        out["host"] = str(host)
    return out


def transport_options(proxy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    network = str(proxy.get("network") or proxy.get("net") or "tcp").strip().lower()
    if network in {"", "tcp", "raw"}:
        return None
    if network == "ws":
        return ws_transport(proxy)
    if network == "grpc":
        return grpc_transport(proxy)
    if network in {"http", "httpupgrade", "http-upgrade"}:
        return http_upgrade_transport(proxy)
    return None


def base_proxy_common(proxy: Dict[str, Any], tag: str) -> Optional[Dict[str, Any]]:
    server = proxy.get("server")
    port = to_int(proxy.get("port"), 0)
    if not server or not port:
        return None
    return {
        "tag": tag,
        "server": str(server),
        "server_port": port,
    }


def convert_vless(proxy: Dict[str, Any], tag: str) -> Optional[Dict[str, Any]]:
    out = base_proxy_common(proxy, tag)
    if not out:
        return None
    uuid_value = proxy.get("uuid") or proxy.get("id")
    if not uuid_value:
        return None
    out.update(
        {
            "type": "vless",
            "uuid": str(uuid_value),
        }
    )
    flow = proxy.get("flow")
    if flow:
        out["flow"] = str(flow)
    packet_encoding = proxy.get("packet-encoding") or proxy.get("packet_encoding")
    if packet_encoding:
        out["packet_encoding"] = str(packet_encoding)
    tls = tls_options(proxy)
    if tls:
        out["tls"] = tls
    transport = transport_options(proxy)
    if transport:
        out["transport"] = transport
    return out


def convert_trojan(proxy: Dict[str, Any], tag: str) -> Optional[Dict[str, Any]]:
    out = base_proxy_common(proxy, tag)
    if not out:
        return None
    password = proxy.get("password")
    if password is None or str(password) == "":
        return None
    out.update(
        {
            "type": "trojan",
            "password": str(password),
        }
    )
    tls = tls_options(proxy) or {"enabled": True}
    out["tls"] = tls
    transport = transport_options(proxy)
    if transport:
        out["transport"] = transport
    return out


def convert_vmess(proxy: Dict[str, Any], tag: str) -> Optional[Dict[str, Any]]:
    out = base_proxy_common(proxy, tag)
    if not out:
        return None
    uuid_value = proxy.get("uuid") or proxy.get("id")
    if not uuid_value:
        return None
    out.update(
        {
            "type": "vmess",
            "uuid": str(uuid_value),
            "security": str(proxy.get("cipher") or "auto"),
            "alter_id": to_int(proxy.get("alterId") or proxy.get("alter-id") or proxy.get("alter_id"), 0),
        }
    )
    tls = tls_options(proxy)
    if tls:
        out["tls"] = tls
    transport = transport_options(proxy)
    if transport:
        out["transport"] = transport
    return out


def convert_shadowsocks(proxy: Dict[str, Any], tag: str) -> Optional[Dict[str, Any]]:
    out = base_proxy_common(proxy, tag)
    if not out:
        return None
    method = proxy.get("cipher") or proxy.get("method")
    password = proxy.get("password")
    if not method or password is None:
        return None
    out.update(
        {
            "type": "shadowsocks",
            "method": str(method),
            "password": str(password),
        }
    )
    return out


def convert_proxy(proxy: Dict[str, Any], used_tags: set[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(proxy, dict):
        return None
    proxy_type = str(proxy.get("type") or "").strip().lower()
    tag = unique_tag(clean_tag(proxy.get("name"), proxy_type or "proxy"), used_tags)

    if proxy_type == "vless":
        return convert_vless(proxy, tag)
    if proxy_type == "trojan":
        return convert_trojan(proxy, tag)
    if proxy_type == "vmess":
        return convert_vmess(proxy, tag)
    if proxy_type in {"ss", "shadowsocks"}:
        return convert_shadowsocks(proxy, tag)
    return None


def normalize_duration_seconds(value: Any, default_seconds: int) -> str:
    if value is None or value == "":
        return f"{default_seconds}s"
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+", text):
        return f"{int(text)}s"
    return text


def filter_tag_list(values: Any, valid_tags: set[str], include_direct: bool = True) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for value in values:
        tag = str(value).strip()
        if not tag or tag in {"REJECT", "reject", "GLOBAL"}:
            continue
        if tag in valid_tags or (include_direct and tag in {"DIRECT", "direct"}):
            if tag not in out:
                out.append(tag)
    return out


def group_type_to_singbox(group_type: str) -> str:
    value = str(group_type or "select").strip().lower().replace("_", "-")
    if value in {"url-test", "urltest", "load-balance"}:
        return "urltest"
    if value in {"fallback", "relay"}:
        # sing-box has no exact legacy Clash fallback group. urltest is the safest automatic group.
        return "urltest"
    return "selector"


def convert_group(group: Dict[str, Any], valid_tags: set[str], used_tags: set[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(group, dict):
        return None
    raw_name = clean_tag(group.get("name"), "GROUP")
    tag = unique_tag(raw_name, used_tags)
    outbounds = filter_tag_list(group.get("proxies"), valid_tags, include_direct=True)
    if not outbounds:
        return None

    sb_type = group_type_to_singbox(str(group.get("type") or "select"))
    if sb_type == "urltest":
        return {
            "type": "urltest",
            "tag": tag,
            "outbounds": outbounds,
            "url": str(group.get("url") or DEFAULT_TEST_URL),
            "interval": normalize_duration_seconds(group.get("interval"), 120),
            "tolerance": to_int(group.get("tolerance"), 30),
            "interrupt_exist_connections": False,
        }

    selector = {
        "type": "selector",
        "tag": tag,
        "outbounds": outbounds,
        "default": outbounds[0],
        "interrupt_exist_connections": False,
    }
    return selector


def convert_rule_text(rule: str, default_outbound: str, valid_outbounds: set[str]) -> Optional[Dict[str, Any]]:
    text = str(rule or "").strip()
    if not text or text.startswith("#"):
        return None

    parts = [part.strip() for part in text.split(",")]
    rule_type = parts[0].upper() if parts else ""

    def target(index: int = -1) -> str:
        if len(parts) >= abs(index):
            candidate = parts[index].strip()
        else:
            candidate = default_outbound
        if candidate in {"REJECT", "reject"}:
            return "REJECT"
        return candidate if candidate in valid_outbounds else default_outbound

    outbound = target(-1)
    action = "reject" if outbound == "REJECT" else "route"

    if rule_type == "MATCH":
        if action == "reject":
            return {"action": "reject"}
        return {"action": "route", "outbound": outbound}

    if len(parts) < 3 and rule_type not in {"IP-CIDR", "IP-CIDR6"}:
        return None

    if rule_type == "DOMAIN-SUFFIX" and len(parts) >= 3:
        item = {"domain_suffix": [parts[1]]}
    elif rule_type == "DOMAIN" and len(parts) >= 3:
        item = {"domain": [parts[1]]}
    elif rule_type == "DOMAIN-KEYWORD" and len(parts) >= 3:
        item = {"domain_keyword": [parts[1]]}
    elif rule_type in {"IP-CIDR", "IP-CIDR6"} and len(parts) >= 3:
        item = {"ip_cidr": [parts[1]]}
    elif rule_type == "DST-PORT" and len(parts) >= 3:
        item = {"port": [to_int(parts[1], 0)]}
    else:
        return None

    if action == "reject":
        item["action"] = "reject"
    else:
        item["action"] = "route"
        item["outbound"] = outbound
    return item


def build_dns(dns_mode: str) -> Dict[str, Any]:
    """Build DNS config with Cloudflare 1.1.1.1 only.

    Catatan:
    - Tidak memakai 8.8.8.8 atau resolver lain.
    - Mode legacy dipakai untuk client lama yang menolak dns.servers[].type.
    - Mode new dipakai untuk sing-box 1.14+ yang menerima type/server.
    """
    if dns_mode == "new":
        return {
            "servers": [
                {
                    "type": "udp",
                    "tag": "cloudflare",
                    "server": "1.1.1.1",
                },
            ],
            "final": "cloudflare",
        }

    return {
        "servers": [
            {
                "tag": "cloudflare",
                "address": "1.1.1.1",
            },
        ],
        "final": "cloudflare",
    }


def build_inbounds(tun_mode: str, mixed_port: int) -> List[Dict[str, Any]]:
    inbounds: List[Dict[str, Any]] = []
    if tun_mode != "off":
        tun: Dict[str, Any] = {
            "type": "tun",
            "tag": "tun-in",
            "auto_route": True,
            "strict_route": True,
        }
        if tun_mode == "legacy":
            tun["inet4_address"] = "172.19.0.1/30"
        else:
            tun["address"] = ["172.19.0.1/30"]
        inbounds.append(tun)

    inbounds.append(
        {
            "type": "mixed",
            "tag": "mixed-in",
            "listen": "127.0.0.1",
            "listen_port": mixed_port,
        }
    )
    return inbounds


def build_route(default_outbound: str, yaml_rules: Iterable[Any], valid_outbounds: set[str]) -> Dict[str, Any]:
    rules: List[Dict[str, Any]] = [
        {
            "action": "sniff",
        },
        {
            "protocol": "dns",
            "action": "hijack-dns",
        },
        {
            "ip_cidr": PRIVATE_CIDRS,
            "action": "route",
            "outbound": "DIRECT",
        },
    ]

    for rule in yaml_rules or []:
        parsed = convert_rule_text(str(rule), default_outbound, valid_outbounds)
        if parsed:
            # Avoid duplicating the final MATCH when it is the same as final.
            if parsed == {"action": "route", "outbound": default_outbound}:
                continue
            rules.append(parsed)

    return {
        "rules": rules,
        "final": default_outbound,
        "auto_detect_interface": True,
    }


def convert_config(
    clash: Dict[str, Any],
    *,
    dns_mode: str = "legacy",
    tun_mode: str = "modern",
    mixed_port: int = 7893,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    used_tags: set[str] = set()
    proxy_outbounds: List[Dict[str, Any]] = []
    skipped = 0

    for proxy in clash.get("proxies") or []:
        outbound = convert_proxy(proxy, used_tags)
        if outbound:
            proxy_outbounds.append(outbound)
        else:
            skipped += 1

    valid_tags = {item["tag"] for item in proxy_outbounds}

    group_outbounds: List[Dict[str, Any]] = []
    group_tags: set[str] = set()
    # Allow groups to reference previously converted groups by gradually extending valid_tags.
    for group in clash.get("proxy-groups") or clash.get("proxy_groups") or []:
        group_outbound = convert_group(group, valid_tags | group_tags | {"DIRECT"}, used_tags)
        if group_outbound:
            group_outbounds.append(group_outbound)
            group_tags.add(group_outbound["tag"])

    outbounds: List[Dict[str, Any]] = [
        {
            "type": "direct",
            "tag": "DIRECT",
        }
    ]
    outbounds.extend(proxy_outbounds)
    outbounds.extend(group_outbounds)

    # Prefer OpenClash PROXY group as the final outbound when available.
    all_tags = {item["tag"] for item in outbounds}
    default_outbound = "PROXY" if "PROXY" in all_tags else (group_outbounds[0]["tag"] if group_outbounds else "DIRECT")

    config = {
        "log": {
            "level": "info",
            "timestamp": True,
        },
        "dns": build_dns(dns_mode),
        "inbounds": build_inbounds(tun_mode, mixed_port),
        "outbounds": outbounds,
        "route": build_route(default_outbound, clash.get("rules") or [], all_tags | {"REJECT"}),
    }

    summary = {
        "proxy_count": len(proxy_outbounds),
        "group_count": len(group_outbounds),
        "outbound_count": len(outbounds),
        "skipped_proxy_count": skipped,
        "dns_mode": dns_mode,
        "tun_mode": tun_mode,
        "default_outbound": default_outbound,
        "deprecated_special_outbounds": False,
        "contains_block_outbound": False,
        "contains_dns_outbound": False,
    }
    return config, summary


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_delay_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


def read_csv_rows(path: str) -> List[Dict[str, Any]]:
    raw = read_text(path)
    return list(csv.DictReader(io.StringIO(raw or "")))


def normalize_best_ping_row(row: Dict[str, Any], source_path: str) -> Optional[Dict[str, Any]]:
    name = str(row.get("name") or row.get("proxy") or row.get("tag") or "").strip()
    delay = parse_delay_ms(row.get("delay_ms") or row.get("delay") or row.get("latency") or row.get("ping"))
    if not name or delay is None:
        return None
    return {
        "name": name,
        "delay_ms": delay,
        "country": str(row.get("country") or "").strip().upper(),
        "status": str(row.get("status") or "").strip().lower(),
        "protocol": str(row.get("protocol") or "").strip().lower(),
        "server": str(row.get("server") or "").strip(),
        "port": str(row.get("port") or "").strip(),
        "source_csv": source_path,
    }


def collect_best_ping_rows(csv_paths: List[str], limit: int, country_filter: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Collect Top-N ping rows from generated CSV reports.

    Priority:
    1. output/BestPing/top5_indonesia_ping.csv
    2. output/BestPing/top5_best_ping.csv
    3. output/Alive/alive.csv
    4. output/Alive/check_result.csv

    BestPing CSV files are treated as pre-filtered. Alive/check_result files are filtered by status=alive
    and optionally by country_filter.
    """
    selected: List[Dict[str, Any]] = []
    tried: List[Dict[str, Any]] = []
    country_filter = str(country_filter or "").strip().upper()

    for path in csv_paths:
        if not Path(path).exists() and not str(path).startswith(("http://", "https://")):
            tried.append({"path": path, "status": "missing"})
            continue

        try:
            raw_rows = read_csv_rows(path)
            rows: List[Dict[str, Any]] = []
            for row in raw_rows:
                normalized = normalize_best_ping_row(row, path)
                if not normalized:
                    continue

                prefiltered = "BestPing" in path or "top5" in Path(path).name.lower()
                if not prefiltered:
                    if normalized.get("status") and normalized.get("status") != "alive":
                        continue
                    if country_filter and normalized.get("country") != country_filter:
                        continue
                rows.append(normalized)

            rows.sort(key=lambda item: item.get("delay_ms") or 999999)
            if rows:
                selected = rows[:limit]
                tried.append({"path": path, "status": "used", "row_count": len(rows)})
                break
            tried.append({"path": path, "status": "empty", "row_count": len(raw_rows)})
        except Exception as exc:
            tried.append({"path": path, "status": "error", "error": str(exc)})

    summary = {
        "csv_paths_tried": tried,
        "selected_count": len(selected),
        "country_filter": country_filter,
        "limit": limit,
    }
    return selected, summary


def pick_best_ping_source_yaml(preferred: str = "") -> Optional[str]:
    candidates = [preferred] if preferred else []
    candidates.extend(DEFAULT_BEST_PING_SOURCE_YAMLS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def select_proxies_by_names(clash: Dict[str, Any], names: List[str], limit: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    proxies = [item for item in (clash.get("proxies") or []) if isinstance(item, dict)]
    by_name = {str(item.get("name") or "").strip(): item for item in proxies}
    selected: List[Dict[str, Any]] = []
    missing: List[str] = []
    seen: set[str] = set()

    for name in names:
        clean_name = str(name or "").strip()
        if not clean_name or clean_name in seen:
            continue
        proxy = by_name.get(clean_name)
        if proxy:
            selected.append(proxy)
            seen.add(clean_name)
        else:
            missing.append(clean_name)

    if not selected:
        # Safe fallback: use the first proxies from the source YAML so the workflow does not fail.
        selected = proxies[:limit]

    return selected[:limit], missing


def build_best_ping_config(
    clash: Dict[str, Any],
    selected_proxies: List[Dict[str, Any]],
    *,
    dns_mode: str = "legacy",
    tun_mode: str = "modern",
    mixed_port: int = 7893,
    test_url: str = DEFAULT_TEST_URL,
    interval: str = "3m",
    tolerance: int = 50,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    used_tags: set[str] = set()
    proxy_outbounds: List[Dict[str, Any]] = []
    selected_names: List[str] = []
    skipped = 0

    for proxy in selected_proxies:
        selected_names.append(clean_tag(proxy.get("name"), "proxy"))
        outbound = convert_proxy(proxy, used_tags)
        if outbound:
            proxy_outbounds.append(outbound)
        else:
            skipped += 1

    proxy_tags = [item["tag"] for item in proxy_outbounds]
    outbounds: List[Dict[str, Any]] = [
        {
            "type": "direct",
            "tag": "DIRECT",
        }
    ]
    outbounds.extend(proxy_outbounds)

    if proxy_tags:
        outbounds.append(
            {
                "type": "urltest",
                "tag": "AUTO-BEST-PING",
                "outbounds": proxy_tags,
                "url": test_url,
                "interval": interval,
                "tolerance": tolerance,
                "interrupt_exist_connections": False,
            }
        )
        outbounds.append(
            {
                "type": "selector",
                "tag": "PROXY",
                "outbounds": ["AUTO-BEST-PING", "DIRECT"] + proxy_tags,
                "default": "AUTO-BEST-PING",
                "interrupt_exist_connections": False,
            }
        )
        default_outbound = "PROXY"
    else:
        default_outbound = "DIRECT"

    all_tags = {item["tag"] for item in outbounds}
    config = {
        "log": {
            "level": "info",
            "timestamp": True,
        },
        "dns": build_dns(dns_mode),
        "inbounds": build_inbounds(tun_mode, mixed_port),
        "outbounds": outbounds,
        "route": build_route(default_outbound, clash.get("rules") or [], all_tags | {"REJECT"}),
    }

    summary = {
        "profile": "best-ping",
        "proxy_count": len(proxy_outbounds),
        "group_count": 2 if proxy_tags else 0,
        "outbound_count": len(outbounds),
        "selected_names": selected_names,
        "skipped_proxy_count": skipped,
        "dns_mode": dns_mode,
        "tun_mode": tun_mode,
        "default_outbound": default_outbound,
        "urltest_tag": "AUTO-BEST-PING" if proxy_tags else "",
        "deprecated_special_outbounds": False,
        "contains_block_outbound": False,
        "contains_dns_outbound": False,
    }
    return config, summary


def generate_best_ping_profile(args: argparse.Namespace, output_dir: Path) -> List[Dict[str, Any]]:
    if not getattr(args, "also_best_ping", True):
        return []

    csv_paths = args.best_ping_csv or DEFAULT_BEST_PING_CSVS
    limit = max(1, int(args.best_ping_limit or 5))
    rows, rows_summary = collect_best_ping_rows(csv_paths, limit, args.best_ping_country_filter)
    if not rows:
        print("SKIP: best-ping.json tidak dibuat karena CSV BestPing/Alive belum memiliki data delay.")
        write_json(output_dir / "summary_best_ping_skipped.json", rows_summary)
        return []

    source_yaml = pick_best_ping_source_yaml(args.best_ping_source_yaml)
    if not source_yaml:
        print("SKIP: best-ping.json tidak dibuat karena source YAML tidak ditemukan.")
        rows_summary["error"] = "source YAML not found"
        write_json(output_dir / "summary_best_ping_skipped.json", rows_summary)
        return []

    clash = load_yaml(source_yaml)
    names = [str(row.get("name") or "").strip() for row in rows]
    selected_proxies, missing_names = select_proxies_by_names(clash, names, limit)

    summaries: List[Dict[str, Any]] = []

    def build_variant(output_path: Path, dns_mode: str, tun_mode: str, label: str = "") -> Dict[str, Any]:
        config, summary = build_best_ping_config(
            clash,
            selected_proxies,
            dns_mode=dns_mode,
            tun_mode=tun_mode,
            mixed_port=args.mixed_port,
            test_url=args.best_ping_test_url,
            interval=args.best_ping_interval,
            tolerance=args.best_ping_tolerance,
        )
        write_json(output_path, config)
        summary.update(
            {
                "input": source_yaml,
                "output": str(output_path),
                "source_csv": rows[0].get("source_csv") if rows else "",
                "selected_from_csv": rows,
                "missing_names_from_yaml": missing_names,
                "csv_summary": rows_summary,
                "variant": label or "default",
            }
        )
        print(f"OK: best ping -> {output_path} ({summary['proxy_count']} proxy, DNS={dns_mode}, TUN={tun_mode})")
        return summary

    main_output = output_dir / "best-ping.json"
    summaries.append(build_variant(main_output, args.dns_mode, args.tun_mode))

    if args.also_new_dns and args.dns_mode != "new":
        summaries.append(build_variant(output_dir / "best-ping-new-dns.json", "new", args.tun_mode, "new-dns"))

    if args.also_legacy_tun and args.tun_mode != "legacy":
        summaries.append(build_variant(output_dir / "best-ping-legacy-tun.json", args.dns_mode, "legacy", "legacy-tun"))

    # Stable aliases for QR/import convenience.
    shutil.copyfile(main_output, output_dir / "best.json")
    print(f"OK: {main_output} -> {output_dir / 'best.json'}")

    write_json(output_dir / "summary_best_ping.json", {"files": summaries})
    return summaries


def convert_one(input_path: str, output_path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    clash = load_yaml(input_path)
    config, summary = convert_config(
        clash,
        dns_mode=args.dns_mode,
        tun_mode=args.tun_mode,
        mixed_port=args.mixed_port,
    )
    write_json(output_path, config)
    summary.update(
        {
            "input": input_path,
            "output": str(output_path),
        }
    )
    return summary


def batch_inputs(values: List[str]) -> List[str]:
    if values:
        return values
    return [item for item in DEFAULT_INPUTS if Path(item).exists()]


def build_output_path(input_path: str, output_dir: Path, suffix: str = "") -> Path:
    stem = Path(input_path).stem
    if suffix:
        stem = f"{stem}{suffix}"
    return output_dir / f"{stem}.json"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert OpenClash/Mihomo YAML to sing-box JSON",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input YAML path/URL. Bisa dipakai berulang. Jika kosong, batch default output/*.yaml akan dipakai.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path. Dipakai hanya ketika input tunggal.",
    )
    parser.add_argument(
        "--output-dir",
        default="output/SingBox",
        help="Folder output untuk batch mode.",
    )
    parser.add_argument(
        "--dns-mode",
        choices=["legacy", "new"],
        default=os.getenv("SINGBOX_DNS_MODE", "legacy"),
        help="legacy untuk client lama; new untuk sing-box 1.14+.",
    )
    parser.add_argument(
        "--tun-mode",
        choices=["modern", "legacy", "off"],
        default=os.getenv("SINGBOX_TUN_MODE", "modern"),
        help="modern=address, legacy=inet4_address, off=tanpa TUN.",
    )
    parser.add_argument(
        "--mixed-port",
        type=int,
        default=int(os.getenv("SINGBOX_MIXED_PORT", "7893")),
    )
    parser.add_argument(
        "--also-new-dns",
        action="store_true",
        help="Selain output utama, buat varian -new-dns.json untuk sing-box 1.14+.",
    )
    parser.add_argument(
        "--also-legacy-tun",
        action="store_true",
        help="Selain output utama, buat varian -legacy-tun.json untuk client lama.",
    )
    parser.add_argument(
        "--also-best-ping",
        action=argparse.BooleanOptionalAction,
        default=as_bool(os.getenv("SINGBOX_CREATE_BEST_PING", "true"), True),
        help="Buat output/SingBox/best-ping.json dari output/BestPing atau output/Alive. Default aktif.",
    )
    parser.add_argument(
        "--best-ping-limit",
        type=int,
        default=int(os.getenv("SINGBOX_BEST_PING_LIMIT", "5")),
        help="Jumlah node terbaik untuk best-ping.json.",
    )
    parser.add_argument(
        "--best-ping-country-filter",
        default=os.getenv("SINGBOX_BEST_PING_COUNTRY_FILTER", "ID"),
        help="Filter country untuk CSV Alive/check_result. Kosongkan untuk semua negara. CSV BestPing dianggap sudah pre-filtered.",
    )
    parser.add_argument(
        "--best-ping-csv",
        action="append",
        default=[],
        help="CSV sumber best ping. Bisa dipakai berulang. Jika kosong, pakai output/BestPing lalu fallback output/Alive.",
    )
    parser.add_argument(
        "--best-ping-source-yaml",
        default=os.getenv("SINGBOX_BEST_PING_SOURCE_YAML", ""),
        help="YAML sumber proxy detail untuk best-ping.json. Jika kosong, fallback strict_alive -> lengkap_alive -> lengkap.",
    )
    parser.add_argument(
        "--best-ping-test-url",
        default=os.getenv("SINGBOX_BEST_PING_TEST_URL", DEFAULT_TEST_URL),
        help="URL test untuk urltest AUTO-BEST-PING.",
    )
    parser.add_argument(
        "--best-ping-interval",
        default=os.getenv("SINGBOX_BEST_PING_INTERVAL", "3m"),
        help="Interval urltest AUTO-BEST-PING.",
    )
    parser.add_argument(
        "--best-ping-tolerance",
        type=int,
        default=int(os.getenv("SINGBOX_BEST_PING_TOLERANCE", "50")),
        help="Tolerance ms untuk urltest AUTO-BEST-PING.",
    )
    parser.add_argument(
        "--make-latest",
        action="store_true",
        help="Copy hasil lengkap.json menjadi latest.json jika ada.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    inputs = batch_inputs(args.input)
    if not inputs:
        print("Tidak ada file input YAML yang ditemukan.", file=sys.stderr)
        return 1

    summaries: List[Dict[str, Any]] = []
    single_input = len(inputs) == 1

    for input_path in inputs:
        output_path = Path(args.output) if args.output and single_input else build_output_path(input_path, output_dir)
        summary = convert_one(input_path, output_path, args)
        summaries.append(summary)
        print(f"OK: {input_path} -> {output_path} ({summary['proxy_count']} proxy, {summary['group_count']} group)")

        if args.also_new_dns and args.dns_mode != "new":
            variant_args = argparse.Namespace(**vars(args))
            variant_args.dns_mode = "new"
            variant_output = output_path.with_name(output_path.stem + "-new-dns" + output_path.suffix)
            summaries.append(convert_one(input_path, variant_output, variant_args))
            print(f"OK: {input_path} -> {variant_output} [new dns]")

        if args.also_legacy_tun and args.tun_mode != "legacy":
            variant_args = argparse.Namespace(**vars(args))
            variant_args.tun_mode = "legacy"
            variant_output = output_path.with_name(output_path.stem + "-legacy-tun" + output_path.suffix)
            summaries.append(convert_one(input_path, variant_output, variant_args))
            print(f"OK: {input_path} -> {variant_output} [legacy tun]")

    best_summaries = generate_best_ping_profile(args, output_dir)
    summaries.extend(best_summaries)

    write_json(output_dir / "summary_singbox.json", {"files": summaries})

    if args.make_latest:
        main_file = output_dir / "lengkap.json"
        if main_file.exists():
            shutil.copyfile(main_file, output_dir / "latest.json")
            print(f"OK: {main_file} -> {output_dir / 'latest.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

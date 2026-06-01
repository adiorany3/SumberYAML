#!/usr/bin/env python3
"""Build lightweight performance profiles for SumberYAML.

Outputs:
- output/openclash-lite-ready.yaml
- output/SingBox/performance-lite.json
- output/V2RayBox/performance-lite.txt
- output/NekoBox/performance-lite.txt
- output/Performance/summary_performance_lite.json

Manual/trusted accounts from input/links.txt and input.txt are always kept.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import shutil
import sys
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"PyYAML is required: {exc}", file=sys.stderr)
    raise

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
PERF = OUTPUT / "Performance"
SINGBOX = OUTPUT / "SingBox"
V2RAYBOX = OUTPUT / "V2RayBox"
NEKOBOX = OUTPUT / "NekoBox"

DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"
LOCAL_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
    "IP-CIDR,255.255.255.255/32,DIRECT,no-resolve",
]

# Domain inti yang tidak boleh masuk blocklist/performance trim.
PROTECTED_CORE_DOMAINS = {
    "youtube.com",
    "googlevideo.com",
    "ytimg.com",
    "youtubei.googleapis.com",
    "googleapis.com",
    "gstatic.com",
    "github.com",
    "raw.githubusercontent.com",
    "whatsapp.com",
    "telegram.org",
    "t.me",
    "shopee.co.id",
    "shopee.com",
    "susercontent.com",
    "tokopedia.com",
    "lazada.co.id",
}


def now_jakarta_date() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")


def ensure_dirs() -> None:
    for p in [OUTPUT, PERF, SINGBOX, V2RAYBOX, NEKOBOX]:
        p.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(read_text(path)) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[WARN] Failed to read YAML {path}: {exc}")
        return {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"[WARN] Failed to read JSON {path}: {exc}")
        return {}


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_delay(value: Any) -> int | None:
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def read_csv_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                for row in csv.DictReader(f):
                    rows.append({str(k or ""): str(v or "") for k, v in row.items()})
        except Exception as exc:
            print(f"[WARN] Failed to read CSV {path}: {exc}")
    return rows


def read_input_links() -> list[str]:
    links: list[str] = []
    for name in ["input/links.txt", "input.txt"]:
        path = ROOT / name
        if not path.exists():
            continue
        for line in read_text(path).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("vmess://", "vless://", "trojan://", "ss://")):
                links.append(line)
    return unique_keep_order(links)


def b64decode_maybe(data: str) -> str:
    raw = data.strip()
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode()).decode("utf-8", errors="replace")


def normalize_name(name: str, prefix: str = "LINK") -> str:
    name = unquote(str(name or "")).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = "MANUAL"
    # Manual account name is not renamed with date, but prefix helps identify trusted links.
    if not re.match(r"(?i)^(LINK|MANUAL)\b", name):
        name = f"{prefix} {name}"
    return name[:96]


def make_unique_name(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        name = f"{base} #{i}"
        if name not in used:
            used.add(name)
            return name
        i += 1


def link_to_openclash_proxy(link: str, used: set[str]) -> dict[str, Any] | None:
    try:
        if link.startswith("vmess://"):
            payload = link[len("vmess://") :]
            data = json.loads(b64decode_maybe(payload))
            name = make_unique_name(normalize_name(data.get("ps") or data.get("name") or "VMESS"), used)
            proxy: dict[str, Any] = {
                "name": name,
                "type": "vmess",
                "server": str(data.get("add") or data.get("server") or ""),
                "port": safe_int(data.get("port"), 443),
                "uuid": str(data.get("id") or data.get("uuid") or ""),
                "alterId": safe_int(data.get("aid") or data.get("alterId"), 0),
                "cipher": str(data.get("scy") or data.get("cipher") or "auto"),
            }
            network = str(data.get("net") or data.get("network") or "").lower()
            tls = str(data.get("tls") or "").lower()
            if tls in {"tls", "true", "1"}:
                proxy["tls"] = True
            sni = data.get("sni") or data.get("host")
            if sni:
                proxy["servername"] = str(sni)
            if network:
                proxy["network"] = network
            if network == "ws":
                proxy["ws-opts"] = {
                    "path": str(data.get("path") or "/"),
                    "headers": {"Host": str(data.get("host") or data.get("sni") or data.get("add") or "")},
                }
            return proxy if proxy.get("server") and proxy.get("uuid") else None

        if link.startswith(("vless://", "trojan://")):
            parsed = urlparse(link)
            scheme = parsed.scheme
            params = {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}
            password_or_uuid = unquote(parsed.username or "")
            server = parsed.hostname or ""
            port = parsed.port or 443
            frag = parsed.fragment or scheme.upper()
            name = make_unique_name(normalize_name(frag), used)
            proxy = {
                "name": name,
                "type": scheme,
                "server": server,
                "port": port,
            }
            if scheme == "vless":
                proxy["uuid"] = password_or_uuid
            else:
                proxy["password"] = password_or_uuid
            security = str(params.get("security") or params.get("tls") or "").lower()
            if security in {"tls", "reality", "true", "1"} or port == 443:
                proxy["tls"] = True
            if security == "reality":
                proxy["reality-opts"] = {
                    k: params[k]
                    for k in ["public-key", "short-id"]
                    if params.get(k)
                }
                if params.get("pbk"):
                    proxy["reality-opts"]["public-key"] = params["pbk"]
                if params.get("sid"):
                    proxy["reality-opts"]["short-id"] = params["sid"]
            sni = params.get("sni") or params.get("servername") or params.get("peer") or params.get("host")
            if sni:
                proxy["servername"] = sni
            network = (params.get("type") or params.get("network") or "").lower()
            if network:
                proxy["network"] = network
            if params.get("flow"):
                proxy["flow"] = params["flow"]
            if network == "ws":
                proxy["ws-opts"] = {
                    "path": unquote(params.get("path") or "/"),
                    "headers": {"Host": params.get("host") or sni or server},
                }
            if network == "grpc":
                proxy["grpc-opts"] = {"grpc-service-name": params.get("serviceName") or params.get("service-name") or ""}
            return proxy if server and password_or_uuid else None
    except Exception as exc:
        print(f"[WARN] Failed to parse manual link: {exc}")
        return None
    return None


def link_to_singbox_outbound(link: str, used: set[str]) -> dict[str, Any] | None:
    p = link_to_openclash_proxy(link, used)
    if not p:
        return None
    typ = p.get("type")
    out: dict[str, Any] = {
        "type": typ,
        "tag": p.get("name"),
        "server": p.get("server"),
        "server_port": safe_int(p.get("port"), 443),
    }
    if typ == "vmess":
        out["uuid"] = p.get("uuid")
        out["security"] = p.get("cipher", "auto")
        out["alter_id"] = safe_int(p.get("alterId"), 0)
    elif typ == "vless":
        out["uuid"] = p.get("uuid")
        if p.get("flow"):
            out["flow"] = p.get("flow")
    elif typ == "trojan":
        out["password"] = p.get("password")
    else:
        return None
    if p.get("tls"):
        out["tls"] = {"enabled": True}
        if p.get("servername"):
            out["tls"]["server_name"] = p.get("servername")
    if p.get("network") == "ws":
        ws = p.get("ws-opts", {})
        out["transport"] = {
            "type": "ws",
            "path": ws.get("path", "/"),
            "headers": ws.get("headers", {}),
        }
    elif p.get("network") == "grpc":
        grpc = p.get("grpc-opts", {})
        out["transport"] = {
            "type": "grpc",
            "service_name": grpc.get("grpc-service-name", ""),
        }
    return out


def build_manual_openclash_proxies(existing_names: set[str]) -> list[dict[str, Any]]:
    used = set(existing_names)
    proxies: list[dict[str, Any]] = []
    for link in read_input_links():
        p = link_to_openclash_proxy(link, used)
        if p:
            proxies.append(p)
    return proxies


def build_manual_singbox_outbounds(existing_tags: set[str]) -> list[dict[str, Any]]:
    used = set(existing_tags)
    outs: list[dict[str, Any]] = []
    for link in read_input_links():
        o = link_to_singbox_outbound(link, used)
        if o:
            outs.append(o)
    return outs


def is_manual_name(name: str) -> bool:
    text = str(name or "")
    return bool(re.match(r"(?i)^(LINK|MANUAL)\b", text)) or "input.txt" in text.lower() or "input/links" in text.lower()


def pick_source_yaml() -> Path | None:
    for name in [
        "output/openclash-ready.yaml",
        "output/lite.yaml",
        "output/fast.yaml",
        "output/lengkap_alive.yaml",
        "output/lengkap.yaml",
    ]:
        p = ROOT / name
        if p.exists():
            return p
    return None


def get_proxy_names_from_groups(data: dict[str, Any], group_names: list[str]) -> list[str]:
    out: list[str] = []
    groups = data.get("proxy-groups") or []
    if not isinstance(groups, list):
        return out
    wanted = {g.lower() for g in group_names}
    group_name_set = {str(g.get("name", "")) for g in groups if isinstance(g, dict)}
    for g in groups:
        if not isinstance(g, dict):
            continue
        if str(g.get("name", "")).lower() not in wanted:
            continue
        for item in g.get("proxies") or []:
            item = str(item)
            if item and item not in {"DIRECT", "REJECT"} and item not in group_name_set:
                out.append(item)
    return unique_keep_order(out)


def stable_candidates_from_csv(proxy_set: set[str], max_count: int) -> list[str]:
    rows = read_csv_rows([
        OUTPUT / "BestPing/top5_indonesia_ping.csv",
        OUTPUT / "BestPing/top5_best_ping.csv",
        OUTPUT / "Alive/alive.csv",
        OUTPUT / "Alive/check_result.csv",
    ])
    candidates: list[tuple[int, str]] = []
    for row in rows:
        name = row.get("name") or row.get("proxy") or row.get("Proxy") or ""
        if not name or name not in proxy_set or is_manual_name(name):
            continue
        status = (row.get("status") or row.get("Status") or "").lower()
        if status and status not in {"alive", "ok", "success", ""}:
            continue
        delay = parse_delay(row.get("delay_ms") or row.get("delay") or row.get("Delay") or row.get("latency"))
        if delay is None:
            delay = 999999
        candidates.append((delay, name))
    candidates.sort(key=lambda x: x[0])
    return unique_keep_order([name for _, name in candidates])[:max_count]


def indonesia_candidates(proxy_set: set[str], max_count: int) -> list[str]:
    rows = read_csv_rows([
        OUTPUT / "BestPing/top5_indonesia_ping.csv",
        OUTPUT / "Alive/alive.csv",
        OUTPUT / "Alive/check_result.csv",
    ])
    candidates: list[tuple[int, str]] = []
    for row in rows:
        name = row.get("name") or ""
        country = (row.get("country") or row.get("Country") or "").upper()
        if not name or name not in proxy_set or is_manual_name(name):
            continue
        text = f"{name} {country}".lower()
        if country == "ID" or "indonesia" in text or "🇮🇩" in text or "jakarta" in text or "id " in text:
            delay = parse_delay(row.get("delay_ms") or row.get("delay")) or 999999
            candidates.append((delay, name))
    if not candidates:
        for name in proxy_set:
            text = name.lower()
            if any(k in text for k in ["indonesia", "jakarta", "id", "🇮🇩", "telkom", "biznet"]):
                candidates.append((999999, name))
    candidates.sort(key=lambda x: x[0])
    return unique_keep_order([name for _, name in candidates])[:max_count]


def build_openclash_lite(max_nodes: int, max_manual: int, keep_security_providers: bool) -> dict[str, Any]:
    source = pick_source_yaml()
    if not source:
        print("[WARN] No OpenClash source YAML found.")
        return {"ok": False, "reason": "no_source_yaml"}
    data = load_yaml(source)
    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        proxies = []
    name_to_proxy: dict[str, dict[str, Any]] = {
        str(p.get("name")): p for p in proxies if isinstance(p, dict) and p.get("name")
    }
    existing_names = set(name_to_proxy)
    manual_extra = build_manual_openclash_proxies(existing_names)
    for p in manual_extra:
        name_to_proxy[str(p.get("name"))] = p
    proxy_set = set(name_to_proxy)
    manual_names = [name for name in name_to_proxy if is_manual_name(name)]
    # Tidak batasi manual kecuali diminta nilai >0; default 0 artinya semua.
    if max_manual > 0:
        manual_names = manual_names[:max_manual]
    stable_names = stable_candidates_from_csv(proxy_set, max_nodes)
    if len(stable_names) < max_nodes:
        from_groups = get_proxy_names_from_groups(
            data,
            ["BEST-STABLE", "ANTI-BENGONG", "URL-TEST", "URL-TEST TOP 10 INDONESIA", "INDONESIA-BEST"],
        )
        stable_names = unique_keep_order(stable_names + [n for n in from_groups if n in proxy_set and not is_manual_name(n)])[:max_nodes]
    if len(stable_names) < max_nodes:
        fallback = [n for n in name_to_proxy if not is_manual_name(n)]
        stable_names = unique_keep_order(stable_names + fallback)[:max_nodes]
    id_names = indonesia_candidates(proxy_set, min(max_nodes, 15))
    if not id_names:
        id_names = stable_names[: min(10, len(stable_names))]
    selected_names = unique_keep_order(stable_names + manual_names + id_names)
    selected_proxies = [deepcopy(name_to_proxy[n]) for n in selected_names if n in name_to_proxy]

    group_names = [str(g.get("name")) for g in data.get("proxy-groups") or [] if isinstance(g, dict)]
    direct = "DIRECT"
    best_stable_items = stable_names or manual_names or [direct]
    manual_items = manual_names or stable_names or [direct]
    id_items = id_names or stable_names or manual_names or [direct]

    groups: list[dict[str, Any]] = [
        {
            "name": "PROXY",
            "type": "select",
            "proxies": unique_keep_order(["ANTI-BENGONG", "BEST-STABLE", "INDONESIA-BEST", "fallback-link", "best-link", direct]),
        },
        {
            "name": "ANTI-BENGONG",
            "type": "fallback",
            "proxies": unique_keep_order(["BEST-STABLE", "INDONESIA-BEST", "fallback-link", "best-link", direct]),
            "url": DEFAULT_TEST_URL,
            "interval": 300,
            "lazy": True,
        },
        {
            "name": "BEST-STABLE",
            "type": "url-test",
            "proxies": best_stable_items,
            "url": DEFAULT_TEST_URL,
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        },
        {
            "name": "INDONESIA-BEST",
            "type": "url-test",
            "proxies": id_items,
            "url": DEFAULT_TEST_URL,
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        },
        {
            "name": "fallback-link",
            "type": "fallback",
            "proxies": manual_items,
            "url": DEFAULT_TEST_URL,
            "interval": 300,
            "lazy": True,
        },
        {
            "name": "best-link",
            "type": "url-test",
            "proxies": manual_items,
            "url": DEFAULT_TEST_URL,
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        },
    ]

    rules = []
    # Pertahankan marketplace protect dan rule Indonesia jika ada, lalu LAN direct + MATCH.
    source_rules = data.get("rules") or []
    if isinstance(source_rules, list):
        for rule in source_rules:
            text = str(rule)
            if "marketplace-protect" in text or text.startswith("GEOIP,ID") or ",INDONESIA-BEST" in text:
                rules.append(text)
    for r in LOCAL_RULES:
        if r not in rules:
            rules.append(r)
    if keep_security_providers:
        for rule in source_rules if isinstance(source_rules, list) else []:
            text = str(rule)
            if text.startswith("RULE-SET,") and text not in rules:
                rules.append(text)
    rules = [r for r in rules if not str(r).startswith("MATCH,")]
    rules.append("MATCH,PROXY")

    lite: dict[str, Any] = {
        "mixed-port": data.get("mixed-port", 7890),
        "allow-lan": data.get("allow-lan", True),
        "mode": "rule",
        "log-level": data.get("log-level", "warning"),
        "unified-delay": True,
        "tcp-concurrent": True,
        "profile": {"store-selected": True, "store-fake-ip": True},
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "nameserver": ["1.1.1.1"],
            "fallback": ["8.8.8.8"],
        },
        "proxies": selected_proxies,
        "proxy-groups": groups,
        "rules": rules,
    }
    if keep_security_providers and isinstance(data.get("rule-providers"), dict):
        lite["rule-providers"] = data.get("rule-providers")
    out = OUTPUT / "openclash-lite-ready.yaml"
    dump_yaml(out, lite)
    return {
        "ok": True,
        "source": str(source),
        "output": str(out),
        "proxy_count": len(selected_proxies),
        "manual_count": len(manual_names),
        "stable_count": len(stable_names),
        "indonesia_count": len(id_names),
        "keep_security_providers": keep_security_providers,
    }


def is_singbox_proxy_outbound(out: dict[str, Any]) -> bool:
    return isinstance(out, dict) and out.get("type") in {"vmess", "vless", "trojan", "shadowsocks", "hysteria2"} and out.get("tag")


def build_singbox_lite(max_nodes: int, max_manual: int) -> dict[str, Any]:
    source = None
    for name in [
        "output/SingBox/mobile-stable-safe.json",
        "output/SingBox/best-stable-safe.json",
        "output/SingBox/import-ready.json",
        "output/SingBox/lengkap-safe.json",
        "output/SingBox/latest-safe.json",
        "output/SingBox/lengkap.json",
    ]:
        p = ROOT / name
        if p.exists():
            source = p
            break
    data = load_json(source) if source else {}
    outbounds = data.get("outbounds") if isinstance(data.get("outbounds"), list) else []
    tag_to_out: dict[str, dict[str, Any]] = {
        str(o.get("tag")): o for o in outbounds if is_singbox_proxy_outbound(o)
    }
    manual_extra = build_manual_singbox_outbounds(set(tag_to_out))
    for o in manual_extra:
        tag_to_out[str(o.get("tag"))] = o
    tags = set(tag_to_out)
    manual_tags = [t for t in tags if is_manual_name(t)]
    if max_manual > 0:
        manual_tags = manual_tags[:max_manual]
    stable_tags = stable_candidates_from_csv(tags, max_nodes)
    if len(stable_tags) < max_nodes:
        # Ambil dari group source.
        group_tags: list[str] = []
        for o in outbounds:
            if not isinstance(o, dict):
                continue
            if o.get("type") in {"selector", "urltest"} and str(o.get("tag", "")).lower() in {
                "best-stable", "auto-best-ping", "mobile-stable", "anti-bengong", "best-link"
            }:
                for t in o.get("outbounds") or []:
                    if t in tags and not is_manual_name(t):
                        group_tags.append(t)
        stable_tags = unique_keep_order(stable_tags + group_tags)[:max_nodes]
    if len(stable_tags) < max_nodes:
        stable_tags = unique_keep_order(stable_tags + [t for t in tags if not is_manual_name(t)])[:max_nodes]
    id_tags = indonesia_candidates(tags, min(max_nodes, 15)) or stable_tags[: min(10, len(stable_tags))]
    selected_tags = unique_keep_order(stable_tags + manual_tags + id_tags)
    selected_outbounds = [deepcopy(tag_to_out[t]) for t in selected_tags if t in tag_to_out]
    for o in selected_outbounds:
        # Runtime aman untuk HP.
        if isinstance(o, dict):
            o.pop("tcp_fast_open", None)
            o.setdefault("connect_timeout", "15s")
    best_items = stable_tags or manual_tags or ["direct"]
    manual_items = manual_tags or stable_tags or ["direct"]
    id_items = id_tags or stable_tags or manual_tags or ["direct"]
    groups = [
        {"type": "selector", "tag": "PROXY", "outbounds": ["ANTI-BENGONG", "BEST-STABLE", "INDONESIA-BEST", "fallback-link", "best-link", "direct"]},
        {"type": "urltest", "tag": "BEST-STABLE", "outbounds": best_items, "url": DEFAULT_TEST_URL, "interval": "3m", "tolerance": 80, "idle_timeout": "2h", "interrupt_exist_connections": False},
        {"type": "urltest", "tag": "INDONESIA-BEST", "outbounds": id_items, "url": DEFAULT_TEST_URL, "interval": "3m", "tolerance": 80, "idle_timeout": "2h", "interrupt_exist_connections": False},
        {"type": "urltest", "tag": "best-link", "outbounds": manual_items, "url": DEFAULT_TEST_URL, "interval": "3m", "tolerance": 80, "idle_timeout": "2h", "interrupt_exist_connections": False},
        {"type": "urltest", "tag": "fallback-link", "outbounds": manual_items, "url": DEFAULT_TEST_URL, "interval": "3m", "tolerance": 120, "idle_timeout": "2h", "interrupt_exist_connections": False},
        {"type": "urltest", "tag": "ANTI-BENGONG", "outbounds": ["BEST-STABLE", "INDONESIA-BEST", "fallback-link", "best-link", "direct"], "url": DEFAULT_TEST_URL, "interval": "3m", "tolerance": 100, "idle_timeout": "2h", "interrupt_exist_connections": False},
    ]
    dns = {
        "servers": [
            {"tag": "cloudflare", "address": "1.1.1.1"},
            {"tag": "google", "address": "8.8.8.8"},
        ],
        "final": "cloudflare",
    }
    inbounds = data.get("inbounds") if isinstance(data.get("inbounds"), list) else []
    if not inbounds:
        inbounds = [
            {"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"], "auto_route": True, "strict_route": False},
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7890},
        ]
    else:
        inbounds = deepcopy(inbounds[:2])
        for ib in inbounds:
            if isinstance(ib, dict) and ib.get("type") == "tun":
                if "inet4_address" in ib and "address" not in ib:
                    ib["address"] = ib.pop("inet4_address")
                ib.pop("inet6_address", None)
                ib.pop("dns_mode", None)
    profile = {
        "log": {"level": "warn"},
        "dns": dns,
        "inbounds": inbounds,
        "outbounds": selected_outbounds + groups + [{"type": "direct", "tag": "direct"}],
        "route": {
            "rules": [
                {"ip_cidr": ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"], "outbound": "direct"}
            ],
            "final": "PROXY",
            "auto_detect_interface": True,
        },
    }
    out = SINGBOX / "performance-lite.json"
    dump_json(out, profile)
    return {
        "ok": True,
        "source": str(source) if source else "manual_links_only",
        "output": str(out),
        "outbound_proxy_count": len(selected_outbounds),
        "manual_count": len(manual_tags),
        "stable_count": len(stable_tags),
        "indonesia_count": len(id_tags),
    }


def write_subscription_outputs(max_lines: int) -> dict[str, Any]:
    links = read_input_links()
    # Tambahkan dari output mobile-stable/all jika ada, tapi manual selalu di depan dan tidak disaring.
    candidates: list[str] = []
    for p in [
        V2RAYBOX / "mobile-stable.txt",
        V2RAYBOX / "best-stable.txt",
        V2RAYBOX / "all.txt",
        NEKOBOX / "mobile-stable.txt",
        NEKOBOX / "all.txt",
    ]:
        if not p.exists():
            continue
        for line in read_text(p).splitlines():
            line = line.strip()
            if line.startswith(("vmess://", "vless://", "trojan://", "ss://")):
                candidates.append(line)
    final = unique_keep_order(links + candidates)
    if max_lines > 0:
        # manual tetap semua; trim hanya kandidat tambahan.
        manual_set = set(links)
        extras = [x for x in final if x not in manual_set]
        final = links + extras[: max(0, max_lines - len(links))]
    text = "\n".join(final).strip() + ("\n" if final else "")
    for folder in [V2RAYBOX, NEKOBOX]:
        write_text(folder / "performance-lite.txt", text)
        b64 = base64.b64encode(text.encode()).decode() if text else ""
        write_text(folder / "performance-lite_base64.txt", b64 + ("\n" if b64 else ""))
    return {
        "ok": True,
        "manual_link_count": len(links),
        "subscription_count": len(final),
        "outputs": [str(V2RAYBOX / "performance-lite.txt"), str(NEKOBOX / "performance-lite.txt")],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-nodes", type=int, default=int(os.getenv("PERFORMANCE_LITE_MAX_NODES", "10")))
    parser.add_argument("--max-manual", type=int, default=int(os.getenv("PERFORMANCE_LITE_MAX_MANUAL", "0")), help="0 means keep all manual links")
    parser.add_argument("--subscription-max-lines", type=int, default=int(os.getenv("PERFORMANCE_SUBSCRIPTION_MAX_LINES", "30")))
    parser.add_argument("--keep-security-providers", action="store_true", default=os.getenv("PERFORMANCE_KEEP_SECURITY_PROVIDERS", "false").lower() in {"1", "true", "yes"})
    args = parser.parse_args()
    ensure_dirs()
    summary = {
        "ok": True,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date_jakarta": now_jakarta_date(),
        "limits": {
            "max_nodes": args.max_nodes,
            "max_manual": args.max_manual,
            "subscription_max_lines": args.subscription_max_lines,
            "keep_security_providers": bool(args.keep_security_providers),
        },
        "openclash": build_openclash_lite(args.max_nodes, args.max_manual, args.keep_security_providers),
        "singbox": build_singbox_lite(args.max_nodes, args.max_manual),
        "subscriptions": write_subscription_outputs(args.subscription_max_lines),
    }
    summary["ok"] = all(
        bool(summary.get(k, {}).get("ok", False))
        for k in ["openclash", "singbox", "subscriptions"]
    )
    dump_json(PERF / "summary_performance_lite.json", summary)
    md = [
        "# Performance Lite Summary",
        "",
        f"Built at: `{summary['built_at']}`",
        f"OpenClash: `{summary['openclash'].get('output')}` proxies={summary['openclash'].get('proxy_count')}",
        f"sing-box: `{summary['singbox'].get('output')}` outbounds={summary['singbox'].get('outbound_proxy_count')}",
        f"Manual links: `{summary['subscriptions'].get('manual_link_count')}`",
        "",
        "Manual accounts from `input.txt` / `input/links.txt` are kept trusted and are not filtered.",
    ]
    write_text(PERF / "summary_performance_lite.md", "\n".join(md) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

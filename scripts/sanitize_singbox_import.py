#!/usr/bin/env python3
"""Sanitize generated sing-box JSON profiles so they are safer to import.

This script is intentionally conservative because some mobile sing-box clients
lag behind the latest core schema. It performs two actions:

1. Clean the original JSON files in place:
   - deduplicate outbound tags
   - remove group references to missing outbounds
   - remove broken regular outbounds
   - normalize DNS/route/inbounds enough to avoid obvious decode errors

2. Generate *-safe.json variants for import:
   - legacy DNS format by default
   - legacy TUN field by default
   - minimal route rules
   - no deprecated special outbounds such as block/dns
   - no risky shared dial fields that often break older clients

The goal is to prevent import/decode errors while keeping the original profiles
available. For QR import, point Streamlit to best-stable-safe.json.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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

REGULAR_TYPES = {
    "vless",
    "vmess",
    "trojan",
    "shadowsocks",
}
GROUP_TYPES = {"selector", "urltest"}
SPECIAL_TYPES = {"direct"}
SKIP_FILE_PREFIXES = (
    "summary_",
    "health_",
)
SKIP_FILE_NAMES = {
    "summary.json",
    "summary_best_stable.json",
    "summary_from_links.json",
    "summary_merge_links_into_singbox.json",
    "summary_mobile_idle_reconnect_fix.json",
    "summary_dns_fallback_stable.json",
    "summary_import_sanitize.json",
    "summary_clear_quarantine.json",
}
ALLOWED_UTLS_FINGERPRINTS = {
    "chrome",
    "firefox",
    "edge",
    "safari",
    "360",
    "qq",
    "ios",
    "android",
    "random",
    "randomized",
}
ALLOWED_PACKET_ENCODINGS = {"xudp", "packetaddr", "none"}


def read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_tag(value: Any, fallback: str = "proxy") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def unique_tag(value: Any, used: set[str], fallback: str = "proxy") -> str:
    base = clean_tag(value, fallback)
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    tag = f"{base} {idx}"
    used.add(tag)
    return tag


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(str(value).strip())
    except Exception:
        return default


def valid_port(value: Any) -> Optional[int]:
    port = to_int(value, 0)
    if 1 <= port <= 65535:
        return port
    return None


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "enabled", "enable"}


def ensure_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def normalize_duration(value: Any, default: str) -> str:
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+", text):
        return f"{text}s"
    if re.fullmatch(r"\d+(ms|s|m|h|d)", text):
        return text
    return default


def clean_tls(tls: Any, *, safe: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(tls, dict):
        return None
    enabled = as_bool(tls.get("enabled"), True)
    if not enabled:
        return None

    out: Dict[str, Any] = {"enabled": True}
    server_name = tls.get("server_name") or tls.get("servername") or tls.get("sni")
    if server_name:
        out["server_name"] = str(server_name).strip()
    if "insecure" in tls:
        out["insecure"] = as_bool(tls.get("insecure"), False)

    alpn = tls.get("alpn")
    if isinstance(alpn, str):
        alpn_values = [item.strip() for item in re.split(r"[,|]", alpn) if item.strip()]
    elif isinstance(alpn, list):
        alpn_values = [str(item).strip() for item in alpn if str(item).strip()]
    else:
        alpn_values = []
    if alpn_values:
        out["alpn"] = alpn_values

    # Keep uTLS/reality in normal cleaned files. In *-safe profiles we still keep
    # valid reality because removing it makes Reality accounts unusable. uTLS is
    # also broadly supported, but fingerprints are normalized.
    utls = tls.get("utls")
    if isinstance(utls, dict):
        fp = str(utls.get("fingerprint") or "").strip().lower()
        if fp in ALLOWED_UTLS_FINGERPRINTS:
            out["utls"] = {"enabled": True, "fingerprint": fp}

    reality = tls.get("reality")
    if isinstance(reality, dict):
        public_key = str(reality.get("public_key") or reality.get("publicKey") or "").strip()
        if public_key:
            cleaned_reality: Dict[str, Any] = {"enabled": True, "public_key": public_key}
            short_id = str(reality.get("short_id") or reality.get("shortId") or "").strip()
            spider_x = str(reality.get("spider_x") or reality.get("spiderX") or "").strip()
            if short_id:
                cleaned_reality["short_id"] = short_id
            if spider_x:
                cleaned_reality["spider_x"] = spider_x
            out["reality"] = cleaned_reality

    return out


def clean_transport(transport: Any, *, safe: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(transport, dict):
        return None
    t = str(transport.get("type") or "").strip().lower()
    if t in {"", "tcp", "raw", "none"}:
        return None

    if t in {"ws", "websocket"}:
        out: Dict[str, Any] = {"type": "ws"}
        path = str(transport.get("path") or "/").strip() or "/"
        out["path"] = path
        headers = transport.get("headers")
        if isinstance(headers, dict):
            clean_headers: Dict[str, str] = {}
            for key, value in headers.items():
                if key is None or value is None:
                    continue
                k = str(key).strip()
                v = str(value).strip()
                if k and v:
                    clean_headers[k] = v
            if clean_headers:
                out["headers"] = clean_headers
        # Early data is useful but older clients may reject it. Do not include in
        # safe profiles.
        if not safe:
            edh = transport.get("early_data_header_name") or transport.get("early-data-header-name")
            if edh:
                out["early_data_header_name"] = str(edh)
        return out

    if t == "grpc":
        out = {"type": "grpc"}
        service_name = transport.get("service_name") or transport.get("serviceName")
        if service_name:
            out["service_name"] = str(service_name)
        return out

    if t in {"httpupgrade", "http-upgrade"}:
        # sing-box supports httpupgrade in newer releases. Keep it in normal files,
        # but remove from safe profiles to avoid import failure on old clients.
        if safe:
            return None
        out = {"type": "httpupgrade"}
        path = transport.get("path")
        host = transport.get("host")
        if path:
            out["path"] = str(path)
        if host:
            out["host"] = str(host)
        return out

    if t in {"http", "h2"}:
        # HTTP transport is often represented differently across tools. For safe
        # import, drop it instead of failing the entire profile.
        if safe:
            return None
        out = {"type": "http"}
        path = transport.get("path")
        host = transport.get("host")
        if path:
            out["path"] = str(path)
        if host:
            out["host"] = [str(host)] if not isinstance(host, list) else [str(item) for item in host]
        return out

    return None


def base_regular(item: Dict[str, Any], used: set[str], tag_map: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], str]:
    old_tag = clean_tag(item.get("tag"), "proxy")
    tag = unique_tag(old_tag, used, "proxy")
    tag_map[old_tag] = tag
    server = str(item.get("server") or "").strip()
    port = valid_port(item.get("server_port") or item.get("port"))
    if not server or not port:
        return None, tag
    return {"type": str(item.get("type")).strip().lower(), "tag": tag, "server": server, "server_port": port}, tag


def clean_regular_outbound(item: Dict[str, Any], used: set[str], tag_map: Dict[str, str], *, safe: bool) -> Optional[Dict[str, Any]]:
    typ = str(item.get("type") or "").strip().lower()
    if typ not in REGULAR_TYPES:
        return None
    out, tag = base_regular(item, used, tag_map)
    if out is None:
        return None

    if typ in {"vless", "vmess"}:
        uuid = str(item.get("uuid") or item.get("id") or "").strip()
        if not uuid:
            return None
        out["uuid"] = uuid

    if typ == "vless":
        flow = str(item.get("flow") or "").strip()
        if flow:
            out["flow"] = flow
        if not safe:
            pe = str(item.get("packet_encoding") or item.get("packet-encoding") or "").strip().lower()
            if pe in ALLOWED_PACKET_ENCODINGS and pe != "none":
                out["packet_encoding"] = pe

    elif typ == "vmess":
        security = str(item.get("security") or item.get("cipher") or "auto").strip().lower()
        if security not in {"auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305"}:
            security = "auto"
        out["security"] = security
        out["alter_id"] = max(0, to_int(item.get("alter_id") or item.get("alterId") or item.get("alter-id"), 0))

    elif typ == "trojan":
        password = str(item.get("password") or "").strip()
        if not password:
            return None
        out["password"] = password

    elif typ == "shadowsocks":
        method = str(item.get("method") or item.get("cipher") or "").strip()
        password = str(item.get("password") or "").strip()
        if not method or not password:
            return None
        out["method"] = method
        out["password"] = password

    tls = clean_tls(item.get("tls"), safe=safe)
    if tls:
        out["tls"] = tls
    elif typ == "trojan":
        out["tls"] = {"enabled": True}

    transport = clean_transport(item.get("transport"), safe=safe)
    if transport:
        out["transport"] = transport

    # Avoid fields that are frequent import-error sources in older clients.
    if not safe:
        connect_timeout = item.get("connect_timeout")
        if connect_timeout:
            out["connect_timeout"] = normalize_duration(connect_timeout, "15s")

    return out


def clean_dns(dns: Any, *, safe: bool, new_dns: bool = False) -> Dict[str, Any]:
    # Safe profiles use legacy DNS because this user's client previously rejected
    # dns.servers[].type.
    if safe or not new_dns:
        return {
            "servers": [
                {"tag": "cloudflare", "address": "1.1.1.1"},
                {"tag": "google", "address": "8.8.8.8"},
            ],
            "final": "cloudflare",
        }
    return {
        "servers": [
            {"type": "udp", "tag": "cloudflare", "server": "1.1.1.1"},
            {"type": "udp", "tag": "google", "server": "8.8.8.8"},
        ],
        "final": "cloudflare",
    }


def clean_inbounds(inbounds: Any, *, safe: bool) -> List[Dict[str, Any]]:
    # Keep a minimal compatible TUN + mixed inbound for mobile import. The safe
    # profile uses inet4_address because older sing-box accepted it when address
    # could be rejected.
    if safe:
        return [
            {
                "type": "tun",
                "tag": "tun-in",
                "inet4_address": "172.19.0.1/30",
                "auto_route": True,
                "strict_route": True,
                "stack": "system",
            },
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 7893,
            },
        ]

    cleaned: List[Dict[str, Any]] = []
    for item in ensure_list(inbounds):
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").lower()
        tag = clean_tag(item.get("tag"), f"{typ}-in")
        if typ == "tun":
            out: Dict[str, Any] = {"type": "tun", "tag": tag}
            if "address" in item:
                out["address"] = ensure_list(item.get("address")) or ["172.19.0.1/30"]
            elif "inet4_address" in item:
                out["inet4_address"] = str(item.get("inet4_address") or "172.19.0.1/30")
            else:
                out["address"] = ["172.19.0.1/30"]
            out["auto_route"] = as_bool(item.get("auto_route"), True)
            out["strict_route"] = as_bool(item.get("strict_route"), True)
            if item.get("stack"):
                out["stack"] = str(item.get("stack"))
            cleaned.append(out)
        elif typ == "mixed":
            cleaned.append(
                {
                    "type": "mixed",
                    "tag": tag,
                    "listen": str(item.get("listen") or "127.0.0.1"),
                    "listen_port": valid_port(item.get("listen_port")) or 7893,
                }
            )
    return cleaned or clean_inbounds([], safe=True)


def remap_tag(tag: Any, tag_map: Dict[str, str]) -> str:
    text = clean_tag(tag, "")
    return tag_map.get(text, text)


def clean_groups(raw_groups: List[Dict[str, Any]], valid_tags: set[str], used: set[str], tag_map: Dict[str, str], *, safe: bool) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    for item in raw_groups:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "selector").strip().lower()
        if typ not in GROUP_TYPES:
            continue
        old_tag = clean_tag(item.get("tag"), "GROUP")
        tag = unique_tag(old_tag, used, "GROUP")
        tag_map[old_tag] = tag
        raw_outbounds = ensure_list(item.get("outbounds"))
        outs: List[str] = []
        for value in raw_outbounds:
            candidate = remap_tag(value, tag_map)
            if candidate in valid_tags or candidate == "DIRECT":
                if candidate not in outs:
                    outs.append(candidate)
        if not outs:
            continue
        if typ == "urltest" and len([x for x in outs if x != "DIRECT"]) >= 1:
            out: Dict[str, Any] = {
                "type": "urltest",
                "tag": tag,
                "outbounds": [x for x in outs if x != "DIRECT"] or outs,
                "url": str(item.get("url") or "https://www.gstatic.com/generate_204"),
                "interval": normalize_duration(item.get("interval"), "3m"),
                "tolerance": max(0, to_int(item.get("tolerance"), 80)),
            }
            if not safe:
                out["idle_timeout"] = normalize_duration(item.get("idle_timeout"), "2h")
                out["interrupt_exist_connections"] = as_bool(item.get("interrupt_exist_connections"), False)
            groups.append(out)
        else:
            default = remap_tag(item.get("default") or outs[0], tag_map)
            if default not in outs:
                default = outs[0]
            out = {"type": "selector", "tag": tag, "outbounds": outs, "default": default}
            if not safe:
                out["interrupt_exist_connections"] = as_bool(item.get("interrupt_exist_connections"), False)
            groups.append(out)
    return groups


def build_route(final_tag: str, valid_tags: set[str], *, safe: bool) -> Dict[str, Any]:
    final = final_tag if final_tag in valid_tags or final_tag == "DIRECT" else ("PROXY" if "PROXY" in valid_tags else "DIRECT")
    route: Dict[str, Any] = {
        "auto_detect_interface": True,
        "rules": [
            {
                "ip_cidr": PRIVATE_CIDRS,
                "outbound": "DIRECT",
            }
        ],
        "final": final,
    }
    return route


def sanitize_config(config: Dict[str, Any], *, safe: bool, prefer_final: str = "PROXY") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    outbounds = config.get("outbounds")
    if not isinstance(outbounds, list):
        outbounds = []

    used: set[str] = set()
    tag_map: Dict[str, str] = {}
    regular: List[Dict[str, Any]] = []
    raw_groups: List[Dict[str, Any]] = []
    dropped: List[Dict[str, str]] = []

    for item in outbounds:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").strip().lower()
        if typ in REGULAR_TYPES:
            cleaned = clean_regular_outbound(item, used, tag_map, safe=safe)
            if cleaned:
                regular.append(cleaned)
            else:
                dropped.append({"tag": str(item.get("tag") or "-"), "type": typ, "reason": "invalid_regular_outbound"})
        elif typ in GROUP_TYPES:
            raw_groups.append(item)
        elif typ == "direct":
            # DIRECT is added once at the end.
            old_tag = clean_tag(item.get("tag"), "DIRECT")
            tag_map[old_tag] = "DIRECT"
        else:
            if typ:
                dropped.append({"tag": str(item.get("tag") or "-"), "type": typ, "reason": "unsupported_or_deprecated_type"})

    valid_regular_tags = {item["tag"] for item in regular}

    # Prefer a stable automatic group when regular proxies exist.
    groups = clean_groups(raw_groups, valid_regular_tags | {"DIRECT"}, used, tag_map, safe=safe)
    group_tags = {item["tag"] for item in groups}

    # Ensure PROXY and AUTO-BEST-STABLE exist if possible.
    regular_tags = [item["tag"] for item in regular]
    if regular_tags:
        auto_tag = "AUTO-BEST-STABLE" if "AUTO-BEST-STABLE" not in group_tags and "AUTO-BEST-PING" not in group_tags else None
        if auto_tag:
            used.add(auto_tag)
            groups.insert(
                0,
                {
                    "type": "urltest",
                    "tag": auto_tag,
                    "outbounds": regular_tags,
                    "url": "https://www.gstatic.com/generate_204",
                    "interval": "3m",
                    "tolerance": 80,
                    **({} if safe else {"idle_timeout": "2h", "interrupt_exist_connections": False}),
                },
            )
            group_tags.add(auto_tag)

        if "PROXY" not in group_tags:
            default_auto = "AUTO-BEST-STABLE" if "AUTO-BEST-STABLE" in group_tags else ("AUTO-BEST-PING" if "AUTO-BEST-PING" in group_tags else regular_tags[0])
            proxy_outs = [default_auto] + regular_tags + ["DIRECT"]
            groups.insert(
                0,
                {
                    "type": "selector",
                    "tag": "PROXY",
                    "outbounds": list(dict.fromkeys(proxy_outs)),
                    "default": default_auto,
                    **({} if safe else {"interrupt_exist_connections": False}),
                },
            )
            used.add("PROXY")
            group_tags.add("PROXY")

    final_outbounds: List[Dict[str, Any]] = []
    final_outbounds.extend(groups)
    final_outbounds.extend(regular)
    final_outbounds.append({"type": "direct", "tag": "DIRECT"})

    valid_final_tags = {item["tag"] for item in final_outbounds if item.get("tag")}

    # Final pass to remove invalid references created by earlier duplicate remaps.
    for item in final_outbounds:
        if item.get("type") in GROUP_TYPES:
            outs = [x for x in item.get("outbounds", []) if x in valid_final_tags and x != item.get("tag")]
            if not outs:
                fallback = regular_tags[0] if regular_tags else "DIRECT"
                outs = [fallback]
            item["outbounds"] = list(dict.fromkeys(outs))
            if item.get("default") not in item["outbounds"]:
                item["default"] = item["outbounds"][0]

    route_final = prefer_final
    original_final = clean_tag((config.get("route") or {}).get("final") if isinstance(config.get("route"), dict) else "", "")
    if original_final in valid_final_tags:
        route_final = original_final
    elif prefer_final not in valid_final_tags:
        route_final = "PROXY" if "PROXY" in valid_final_tags else "DIRECT"

    new_config: Dict[str, Any] = {
        "log": {
            "level": str((config.get("log") or {}).get("level") if isinstance(config.get("log"), dict) else "info" or "info"),
            "timestamp": True,
        },
        "dns": clean_dns(config.get("dns"), safe=safe, new_dns=False),
        "inbounds": clean_inbounds(config.get("inbounds"), safe=safe),
        "outbounds": final_outbounds,
        "route": build_route(route_final, valid_final_tags, safe=safe),
    }

    report = {
        "regular_count": len(regular),
        "group_count": len(groups),
        "dropped_count": len(dropped),
        "dropped": dropped[:100],
        "safe": safe,
        "final": new_config["route"].get("final"),
    }
    return new_config, report


def is_profile_json(path: Path) -> bool:
    name = path.name
    if name in SKIP_FILE_NAMES:
        return False
    if name.startswith(SKIP_FILE_PREFIXES):
        return False
    if not name.endswith(".json"):
        return False
    if name.endswith("-safe.json"):
        return False
    return True


def safe_path_for(path: Path) -> Path:
    return path.with_name(f"{path.stem}-safe.json")


def pick_latest_safe(output_dir: Path, preferred: str) -> Optional[Path]:
    candidates = [
        output_dir / preferred,
        output_dir / "best-stable-safe.json",
        output_dir / "mobile-stable-safe.json",
        output_dir / "best-ping-safe.json",
        output_dir / "lengkap-safe.json",
        output_dir / "latest-safe.json",
    ]
    for path in candidates:
        if path.exists() and read_json(path):
            return path
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sanitize sing-box JSON outputs for safer import.")
    parser.add_argument("--dir", default="output/SingBox")
    parser.add_argument("--write-safe", action="store_true", default=True)
    parser.add_argument("--no-write-safe", dest="write_safe", action="store_false")
    parser.add_argument("--overwrite-clean", action="store_true", default=True)
    parser.add_argument("--no-overwrite-clean", dest="overwrite_clean", action="store_false")
    parser.add_argument("--preferred-latest-safe", default="best-stable-safe.json")
    args = parser.parse_args(argv)

    output_dir = Path(args.dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in output_dir.glob("*.json") if is_profile_json(path))
    summary: Dict[str, Any] = {
        "ok": True,
        "processed_count": 0,
        "safe_created_count": 0,
        "files": [],
    }

    for path in files:
        data = read_json(path)
        if not data:
            continue
        try:
            clean_config, clean_report = sanitize_config(data, safe=False)
            safe_config, safe_report = sanitize_config(data, safe=True)
            if args.overwrite_clean:
                write_json(path, clean_config)
            safe_path = safe_path_for(path)
            if args.write_safe:
                write_json(safe_path, safe_config)
                summary["safe_created_count"] += 1
            summary["processed_count"] += 1
            summary["files"].append(
                {
                    "source": str(path),
                    "safe": str(safe_path) if args.write_safe else "",
                    "clean": clean_report,
                    "safe_report": safe_report,
                }
            )
            print(f"[OK] sanitized {path.name} -> {safe_path.name}")
        except Exception as exc:
            summary["ok"] = False
            summary["files"].append({"source": str(path), "error": str(exc)})
            print(f"[ERROR] {path}: {exc}")

    latest_safe = pick_latest_safe(output_dir, args.preferred_latest_safe)
    if latest_safe and latest_safe.name != "latest-safe.json":
        shutil.copyfile(latest_safe, output_dir / "latest-safe.json")
        summary["latest_safe"] = str(output_dir / "latest-safe.json")
        print(f"[OK] latest-safe.json -> {latest_safe.name}")

    write_json(output_dir / "summary_import_sanitize.json", summary)
    print(f"Summary: {output_dir / 'summary_import_sanitize.json'}")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

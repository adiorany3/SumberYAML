#!/usr/bin/env python3
"""Build V2RayBox/V2Box compatible subscription outputs.

Outputs are subscription text files containing vmess://, vless://, and trojan://
links. Manual accounts from input/links.txt or input.txt are treated as trusted:
they are copied first and are never filtered by health/ping/quarantine logic.
"""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

SUPPORTED_SCHEMES = ("vmess://", "vless://", "trojan://")
DEFAULT_ROOT = Path(".")
DEFAULT_OUTPUT_DIR = Path("output/V2RayBox")
GROUP_OUTPUTS = {
    "INDONESIA-BEST": "indonesia-best.txt",
    "STREAMING-BEST": "streaming-best.txt",
    "GAMING-BEST": "gaming-best.txt",
    "SOCIAL-BEST": "social-best.txt",
    "WORKING-BEST": "working-best.txt",
    "GENERAL-BEST": "general-best.txt",
    "ANTI-BENGONG": "anti-bengong.txt",
    "best-link": "best-link.txt",
    "fallback-link": "fallback-link.txt",
    "BEST-STABLE": "best-stable-openclash.txt",
}

SINGBOX_PROFILE_INPUTS = {
    "mobile-stable.txt": [
        "output/SingBox/mobile-stable-safe.json",
        "output/SingBox/mobile-stable.json",
        "output/SingBox/import-ready.json",
    ],
    "best-stable.txt": [
        "output/SingBox/best-stable-safe.json",
        "output/SingBox/best-stable.json",
        "output/SingBox/import-ready.json",
    ],
    "manual-links-from-json.txt": [
        "output/SingBox/manual-links-safe.json",
        "output/SingBox/manual-links.json",
        "output/SingBox/from-links.json",
    ],
}

YAML_INPUTS = [
    "output/openclash-ready.yaml",
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/fast.yaml",
    "output/lite.yaml",
    "output/gaming.yaml",
    "output/streaming.yaml",
    "output/social_media.yaml",
    "output/working.yaml",
    "output/general.yaml",
]

SINGBOX_ALL_INPUTS = [
    "output/SingBox/import-ready.json",
    "output/SingBox/mobile-stable-safe.json",
    "output/SingBox/best-stable-safe.json",
    "output/SingBox/lengkap-safe.json",
    "output/SingBox/latest-safe.json",
    "output/SingBox/manual-links-safe.json",
    "output/SingBox/from-links.json",
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def unique_preserve(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        clean = (item or "").strip()
        if not clean:
            continue
        key = clean.strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def safe_name(value: Any, fallback: str = "proxy") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:120] or fallback


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "tls"}


def parse_port(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def b64_urlsafe_decode_text(value: str) -> str:
    data = value.strip()
    data += "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def b64_std_encode_text(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def read_manual_links(root: Path) -> List[str]:
    links: List[str] = []
    for rel in ["input/links.txt", "input.txt"]:
        text = read_text(root / rel)
        for line in text.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            if clean.startswith(SUPPORTED_SCHEMES):
                links.append(clean)
    return unique_preserve(links)


def yaml_load(path: Path) -> Dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def json_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clean_query(params: Dict[str, Any]) -> str:
    filtered = []
    for key, value in params.items():
        if value is None:
            continue
        text = str(value)
        if text == "":
            continue
        filtered.append((key, text))
    return urlencode(filtered, doseq=True, safe="/:,.;_-~")


def outbound_tls_from_clash(proxy: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    tls_enabled = as_bool(proxy.get("tls")) or str(proxy.get("security", "")).lower() in {"tls", "reality"}
    security = str(proxy.get("security") or ("tls" if tls_enabled else "none")).lower()
    if security not in {"tls", "reality", "none"}:
        security = "tls" if tls_enabled else "none"
    sni = proxy.get("servername") or proxy.get("sni")
    fp = proxy.get("client-fingerprint") or proxy.get("fingerprint")
    alpn_value = proxy.get("alpn")
    if isinstance(alpn_value, list):
        alpn = ",".join(str(x) for x in alpn_value if x)
    else:
        alpn = str(alpn_value or "")
    extra = {
        "sni": sni,
        "fp": fp,
        "alpn": alpn,
        "pbk": proxy.get("reality-opts", {}).get("public-key") if isinstance(proxy.get("reality-opts"), dict) else proxy.get("public-key"),
        "sid": proxy.get("reality-opts", {}).get("short-id") if isinstance(proxy.get("reality-opts"), dict) else proxy.get("short-id"),
    }
    return security, extra


def clash_transport(proxy: Dict[str, Any]) -> Dict[str, Any]:
    network = str(proxy.get("network") or proxy.get("net") or "tcp").lower()
    result: Dict[str, Any] = {"type": network}
    if network == "ws":
        ws_opts = proxy.get("ws-opts") if isinstance(proxy.get("ws-opts"), dict) else {}
        headers = ws_opts.get("headers") if isinstance(ws_opts.get("headers"), dict) else {}
        result["path"] = ws_opts.get("path") or proxy.get("path") or "/"
        result["host"] = headers.get("Host") or headers.get("host") or proxy.get("host")
    elif network in {"grpc", "gun"}:
        grpc_opts = proxy.get("grpc-opts") if isinstance(proxy.get("grpc-opts"), dict) else {}
        result["type"] = "grpc"
        result["serviceName"] = grpc_opts.get("grpc-service-name") or proxy.get("serviceName") or proxy.get("service-name")
    elif network in {"h2", "http"}:
        h2_opts = proxy.get("h2-opts") if isinstance(proxy.get("h2-opts"), dict) else {}
        result["type"] = "http"
        result["path"] = h2_opts.get("path") or proxy.get("path")
        hosts = h2_opts.get("host") or proxy.get("host")
        if isinstance(hosts, list):
            result["host"] = hosts[0] if hosts else ""
        else:
            result["host"] = hosts
    elif network in {"httpupgrade", "http-upgrade"}:
        result["type"] = "httpupgrade"
        http_opts = proxy.get("httpupgrade-opts") if isinstance(proxy.get("httpupgrade-opts"), dict) else {}
        result["path"] = http_opts.get("path") or proxy.get("path") or "/"
        result["host"] = http_opts.get("host") or proxy.get("host")
    return result


def clash_vmess_to_uri(proxy: Dict[str, Any]) -> Optional[str]:
    server = proxy.get("server")
    port = parse_port(proxy.get("port"))
    uuid = proxy.get("uuid")
    if not server or not port or not uuid:
        return None
    name = safe_name(proxy.get("name"), "vmess")
    transport = clash_transport(proxy)
    security, tls_extra = outbound_tls_from_clash(proxy)
    vmess = {
        "v": "2",
        "ps": name,
        "add": str(server),
        "port": str(port),
        "id": str(uuid),
        "aid": str(proxy.get("alterId", proxy.get("alter-id", 0)) or 0),
        "scy": str(proxy.get("cipher") or "auto"),
        "net": "h2" if transport.get("type") == "http" else transport.get("type", "tcp"),
        "type": "none",
        "host": transport.get("host") or "",
        "path": transport.get("path") or transport.get("serviceName") or "",
        "tls": "tls" if security in {"tls", "reality"} else "",
        "sni": tls_extra.get("sni") or "",
        "alpn": tls_extra.get("alpn") or "",
        "fp": tls_extra.get("fp") or "",
    }
    return "vmess://" + b64_std_encode_text(json.dumps(vmess, ensure_ascii=False, separators=(",", ":")))


def clash_vless_to_uri(proxy: Dict[str, Any]) -> Optional[str]:
    server = proxy.get("server")
    port = parse_port(proxy.get("port"))
    uuid = proxy.get("uuid")
    if not server or not port or not uuid:
        return None
    name = safe_name(proxy.get("name"), "vless")
    transport = clash_transport(proxy)
    security, tls_extra = outbound_tls_from_clash(proxy)
    params: Dict[str, Any] = {
        "encryption": proxy.get("encryption") or "none",
        "security": security,
        "type": transport.get("type") or "tcp",
        "flow": proxy.get("flow"),
        "sni": tls_extra.get("sni"),
        "fp": tls_extra.get("fp"),
        "alpn": tls_extra.get("alpn"),
        "pbk": tls_extra.get("pbk"),
        "sid": tls_extra.get("sid"),
    }
    if transport.get("type") == "ws":
        params["path"] = transport.get("path")
        params["host"] = transport.get("host")
    elif transport.get("type") == "grpc":
        params["serviceName"] = transport.get("serviceName")
    elif transport.get("type") in {"http", "h2"}:
        params["path"] = transport.get("path")
        params["host"] = transport.get("host")
    elif transport.get("type") == "httpupgrade":
        params["path"] = transport.get("path")
        params["host"] = transport.get("host")
    return f"vless://{quote(str(uuid), safe='')}@{server}:{port}?{clean_query(params)}#{quote(name)}"


def clash_trojan_to_uri(proxy: Dict[str, Any]) -> Optional[str]:
    server = proxy.get("server")
    port = parse_port(proxy.get("port"))
    password = proxy.get("password")
    if not server or not port or password is None:
        return None
    name = safe_name(proxy.get("name"), "trojan")
    transport = clash_transport(proxy)
    security, tls_extra = outbound_tls_from_clash(proxy)
    params: Dict[str, Any] = {
        "security": "tls" if security == "none" else security,
        "type": transport.get("type") or "tcp",
        "sni": tls_extra.get("sni"),
        "fp": tls_extra.get("fp"),
        "alpn": tls_extra.get("alpn"),
    }
    if transport.get("type") == "ws":
        params["path"] = transport.get("path")
        params["host"] = transport.get("host")
    elif transport.get("type") == "grpc":
        params["serviceName"] = transport.get("serviceName")
    elif transport.get("type") in {"http", "h2", "httpupgrade"}:
        params["path"] = transport.get("path")
        params["host"] = transport.get("host")
    return f"trojan://{quote(str(password), safe='')}@{server}:{port}?{clean_query(params)}#{quote(name)}"


def clash_proxy_to_uri(proxy: Dict[str, Any]) -> Optional[str]:
    if not isinstance(proxy, dict):
        return None
    ptype = str(proxy.get("type") or "").lower()
    if ptype == "vmess":
        return clash_vmess_to_uri(proxy)
    if ptype == "vless":
        return clash_vless_to_uri(proxy)
    if ptype == "trojan":
        return clash_trojan_to_uri(proxy)
    return None


def singbox_transport(outbound: Dict[str, Any]) -> Dict[str, Any]:
    transport = outbound.get("transport") if isinstance(outbound.get("transport"), dict) else {}
    ttype = str(transport.get("type") or "tcp").lower()
    result = {"type": ttype}
    if ttype == "ws":
        headers = transport.get("headers") if isinstance(transport.get("headers"), dict) else {}
        result["path"] = transport.get("path") or "/"
        result["host"] = headers.get("Host") or headers.get("host") or transport.get("host")
    elif ttype == "grpc":
        result["serviceName"] = transport.get("service_name") or transport.get("serviceName")
    elif ttype in {"http", "h2"}:
        result["type"] = "http"
        result["path"] = transport.get("path")
        hosts = transport.get("host") or []
        if isinstance(hosts, list):
            result["host"] = hosts[0] if hosts else ""
        else:
            result["host"] = hosts
    elif ttype == "httpupgrade":
        result["path"] = transport.get("path") or "/"
        result["host"] = transport.get("host")
    return result


def singbox_tls(outbound: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    tls = outbound.get("tls") if isinstance(outbound.get("tls"), dict) else {}
    if not tls.get("enabled"):
        return "none", {}
    security = "reality" if isinstance(tls.get("reality"), dict) and tls.get("reality", {}).get("enabled") else "tls"
    alpn_value = tls.get("alpn")
    alpn = ",".join(alpn_value) if isinstance(alpn_value, list) else str(alpn_value or "")
    reality = tls.get("reality") if isinstance(tls.get("reality"), dict) else {}
    utls = tls.get("utls") if isinstance(tls.get("utls"), dict) else {}
    return security, {
        "sni": tls.get("server_name"),
        "alpn": alpn,
        "fp": utls.get("fingerprint"),
        "pbk": reality.get("public_key"),
        "sid": reality.get("short_id"),
    }


def singbox_outbound_to_uri(outbound: Dict[str, Any]) -> Optional[str]:
    if not isinstance(outbound, dict):
        return None
    ptype = str(outbound.get("type") or "").lower()
    if ptype not in {"vmess", "vless", "trojan"}:
        return None
    server = outbound.get("server")
    port = parse_port(outbound.get("server_port"))
    tag = safe_name(outbound.get("tag"), ptype)
    if not server or not port:
        return None
    transport = singbox_transport(outbound)
    security, tls_extra = singbox_tls(outbound)
    if ptype == "vmess":
        uuid = outbound.get("uuid")
        if not uuid:
            return None
        vmess = {
            "v": "2",
            "ps": tag,
            "add": str(server),
            "port": str(port),
            "id": str(uuid),
            "aid": str(outbound.get("alter_id", 0) or 0),
            "scy": str(outbound.get("security") or "auto"),
            "net": "h2" if transport.get("type") == "http" else transport.get("type", "tcp"),
            "type": "none",
            "host": transport.get("host") or "",
            "path": transport.get("path") or transport.get("serviceName") or "",
            "tls": "tls" if security in {"tls", "reality"} else "",
            "sni": tls_extra.get("sni") or "",
            "alpn": tls_extra.get("alpn") or "",
            "fp": tls_extra.get("fp") or "",
        }
        return "vmess://" + b64_std_encode_text(json.dumps(vmess, ensure_ascii=False, separators=(",", ":")))
    if ptype == "vless":
        uuid = outbound.get("uuid")
        if not uuid:
            return None
        params: Dict[str, Any] = {
            "encryption": "none",
            "security": security,
            "type": transport.get("type") or "tcp",
            "flow": outbound.get("flow"),
            "sni": tls_extra.get("sni"),
            "fp": tls_extra.get("fp"),
            "alpn": tls_extra.get("alpn"),
            "pbk": tls_extra.get("pbk"),
            "sid": tls_extra.get("sid"),
        }
        if transport.get("type") == "ws":
            params["path"] = transport.get("path")
            params["host"] = transport.get("host")
        elif transport.get("type") == "grpc":
            params["serviceName"] = transport.get("serviceName")
        elif transport.get("type") in {"http", "h2", "httpupgrade"}:
            params["path"] = transport.get("path")
            params["host"] = transport.get("host")
        return f"vless://{quote(str(uuid), safe='')}@{server}:{port}?{clean_query(params)}#{quote(tag)}"
    if ptype == "trojan":
        password = outbound.get("password")
        if password is None:
            return None
        params = {
            "security": "tls" if security == "none" else security,
            "type": transport.get("type") or "tcp",
            "sni": tls_extra.get("sni"),
            "fp": tls_extra.get("fp"),
            "alpn": tls_extra.get("alpn"),
        }
        if transport.get("type") == "ws":
            params["path"] = transport.get("path")
            params["host"] = transport.get("host")
        elif transport.get("type") == "grpc":
            params["serviceName"] = transport.get("serviceName")
        elif transport.get("type") in {"http", "h2", "httpupgrade"}:
            params["path"] = transport.get("path")
            params["host"] = transport.get("host")
        return f"trojan://{quote(str(password), safe='')}@{server}:{port}?{clean_query(params)}#{quote(tag)}"
    return None


def extract_yaml_links(root: Path, rel_paths: Sequence[str]) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    all_links: List[str] = []
    by_proxy: Dict[str, Dict[str, Any]] = {}
    for rel in rel_paths:
        data = yaml_load(root / rel)
        proxies = data.get("proxies") or []
        if not isinstance(proxies, list):
            continue
        for proxy in proxies:
            if not isinstance(proxy, dict):
                continue
            name = str(proxy.get("name") or "").strip()
            if name:
                by_proxy[name] = proxy
            uri = clash_proxy_to_uri(proxy)
            if uri:
                all_links.append(uri)
    return unique_preserve(all_links), by_proxy


def extract_group_links_from_yaml(root: Path, rel: str, group_name: str) -> List[str]:
    data = yaml_load(root / rel)
    proxies = data.get("proxies") or []
    proxy_map = {str(item.get("name")): item for item in proxies if isinstance(item, dict) and item.get("name")}
    groups = data.get("proxy-groups") or []
    names: List[str] = []
    for group in groups:
        if isinstance(group, dict) and str(group.get("name")) == group_name:
            raw = group.get("proxies") or []
            if isinstance(raw, list):
                names = [str(x) for x in raw if str(x) in proxy_map]
            break
    links = []
    for name in names:
        uri = clash_proxy_to_uri(proxy_map.get(name, {}))
        if uri:
            links.append(uri)
    return unique_preserve(links)


def extract_singbox_links(root: Path, rel_paths: Sequence[str]) -> List[str]:
    links: List[str] = []
    for rel in rel_paths:
        data = json_load(root / rel)
        outbounds = data.get("outbounds") or []
        if not isinstance(outbounds, list):
            continue
        for outbound in outbounds:
            uri = singbox_outbound_to_uri(outbound)
            if uri:
                links.append(uri)
    return unique_preserve(links)


def write_subscription_files(output_dir: Path, name: str, links: Sequence[str]) -> Dict[str, Any]:
    clean = unique_preserve(links)
    txt_path = output_dir / name
    write_text(txt_path, "\n".join(clean) + ("\n" if clean else ""))
    b64_name = name.rsplit(".", 1)[0] + "_base64.txt"
    write_text(output_dir / b64_name, b64_std_encode_text("\n".join(clean)) + "\n")
    return {"file": str(txt_path), "base64_file": str(output_dir / b64_name), "count": len(clean)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V2RayBox subscription outputs from YAML, sing-box JSON, and trusted input links.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-all", type=int, default=0, help="Optional max links for all.txt; 0 means unlimited.")
    parser.add_argument("--prefer-manual", action="store_true", default=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    manual_links = read_manual_links(root)
    yaml_links, _ = extract_yaml_links(root, YAML_INPUTS)
    singbox_links = extract_singbox_links(root, SINGBOX_ALL_INPUTS)

    all_links = unique_preserve(manual_links + yaml_links + singbox_links)
    if args.max_all and len(all_links) > args.max_all:
        manual_set = set(manual_links)
        manual_first = [x for x in all_links if x in manual_set]
        rest = [x for x in all_links if x not in manual_set]
        all_links = unique_preserve(manual_first + rest)[: args.max_all]

    summary: Dict[str, Any] = {
        "ok": True,
        "manual_trusted_count": len(manual_links),
        "yaml_converted_count": len(yaml_links),
        "singbox_converted_count": len(singbox_links),
        "outputs": {},
        "notes": [
            "input/links.txt and input.txt are trusted manual accounts and are copied first without filtering.",
            "These outputs are V2RayBox/V2Box compatible subscription text/base64 files, not sing-box JSON profiles.",
        ],
    }

    summary["outputs"]["manual-links.txt"] = write_subscription_files(output_dir, "manual-links.txt", manual_links)
    summary["outputs"]["all.txt"] = write_subscription_files(output_dir, "all.txt", all_links)
    summary["outputs"]["subscription_base64.txt"] = {
        "file": str(output_dir / "subscription_base64.txt"),
        "count": len(all_links),
    }
    write_text(output_dir / "subscription_base64.txt", b64_std_encode_text("\n".join(all_links)) + "\n")

    for out_name, rel_paths in SINGBOX_PROFILE_INPUTS.items():
        profile_links = unique_preserve(manual_links + extract_singbox_links(root, rel_paths))
        if not profile_links and manual_links:
            profile_links = manual_links
        summary["outputs"][out_name] = write_subscription_files(output_dir, out_name, profile_links)

    # Group-specific OpenClash outputs, useful for rule/purpose based imports.
    for group, out_name in GROUP_OUTPUTS.items():
        links = extract_group_links_from_yaml(root, "output/openclash-ready.yaml", group)
        if not links:
            links = extract_group_links_from_yaml(root, "output/lengkap.yaml", group)
        if group in {"best-link", "fallback-link"}:
            # Always preserve trusted manual links for manual groups.
            links = unique_preserve(manual_links + links)
        if links:
            summary["outputs"][out_name] = write_subscription_files(output_dir, out_name, links)

    # Common aliases expected by Android clients/users.
    mobile_links = []
    if "mobile-stable.txt" in summary["outputs"]:
        mobile_links = read_text(output_dir / "mobile-stable.txt").splitlines()
    if not mobile_links:
        mobile_links = all_links
    write_subscription_files(output_dir, "latest.txt", mobile_links)

    raw_url_hint = "https://raw.githubusercontent.com/<owner>/<repo>/main/output/V2RayBox/mobile-stable.txt"
    cdn_url_hint = "https://cdn.jsdelivr.net/gh/<owner>/<repo>@main/output/V2RayBox/mobile-stable.txt"
    write_text(output_dir / "README_V2RAYBOX.txt", "\n".join([
        "SumberYAML V2RayBox outputs",
        "",
        "Recommended for Android V2RayBox/V2Box:",
        "- output/V2RayBox/mobile-stable.txt",
        "- output/V2RayBox/mobile-stable_base64.txt",
        "",
        "Manual trusted links are preserved first from input/links.txt and input.txt.",
        "",
        f"Raw URL pattern: {raw_url_hint}",
        f"CDN URL pattern: {cdn_url_hint}",
        "",
    ]))

    summary_path = output_dir / "summary_v2raybox.json"
    write_text(summary_path, json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Convert vmess://, vless://, and trojan:// share links into sing-box JSON profiles.

Designed for SumberYAML-style GitHub Actions usage.

Default input candidates:
- input/links.txt
- input/vmess.txt
- input/vless.txt
- input/trojan.txt
- links.txt

Default outputs:
- output/SingBox/from-links.json
- output/SingBox/from-links-new-dns.json
- output/SingBox/from-links-legacy-tun.json
- output/SingBox/vmess-links.json
- output/SingBox/vless-links.json
- output/SingBox/trojan-links.json
- output/SingBox/summary_from_links.json

Notes:
- DNS defaults to 1.1.1.1 only.
- No deprecated special outbounds type "block" or "dns" are generated.
- Invalid lines are skipped and reported in summary JSON.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urlparse

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

DEFAULT_INPUTS = [
    "input/links.txt",
    "input/vmess.txt",
    "input/vless.txt",
    "input/trojan.txt",
    "links.txt",
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

SUPPORTED_SCHEMES = {"vmess", "vless", "trojan"}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def b64decode_text(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("\n", "").replace("\r", "")
    value = value.replace("-", "+").replace("_", "/")
    missing = len(value) % 4
    if missing:
        value += "=" * (4 - missing)
    return base64.b64decode(value).decode("utf-8", errors="replace")


def maybe_decode_subscription(text: str) -> str:
    """If text looks like a base64 subscription blob, decode it.

    A normal file may already contain links line-by-line, so this function only
    replaces text when decoded content contains at least one supported link.
    """
    raw = (text or "").strip()
    if not raw:
        return text
    if any(f"{scheme}://" in raw for scheme in SUPPORTED_SCHEMES):
        return text
    compact = re.sub(r"\s+", "", raw)
    if not compact or len(compact) < 24:
        return text
    try:
        decoded = b64decode_text(compact)
    except Exception:
        return text
    if any(f"{scheme}://" in decoded for scheme in SUPPORTED_SCHEMES):
        return decoded
    return text


def read_text_source(source: str) -> str:
    source = str(source).strip()
    if source.startswith(("http://", "https://")):
        if requests is None:
            raise RuntimeError("Package requests belum tersedia untuk membaca URL.")
        response = requests.get(source, timeout=60)
        response.raise_for_status()
        return response.text
    return Path(source).read_text(encoding="utf-8")


def split_links(text: str) -> List[str]:
    text = maybe_decode_subscription(text)
    links: List[str] = []
    # Split whitespace but keep full URL fragments. Most share links don't contain
    # spaces; comments/names should be URL-encoded. This is robust for subscription files.
    for token in re.split(r"\s+", text or ""):
        token = token.strip().strip('"').strip("'")
        if not token or token.startswith("#"):
            continue
        if any(token.lower().startswith(f"{scheme}://") for scheme in SUPPORTED_SCHEMES):
            links.append(token)
    return links


def clean_tag(value: Any, fallback: str = "proxy") -> str:
    text = unquote(str(value or fallback)).strip()
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


def first_query(query: Dict[str, List[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in query and query[key]:
            return str(query[key][0])
    return default


def first_bool(query: Dict[str, List[str]], *keys: str, default: bool = False) -> bool:
    value = first_query(query, *keys, default="")
    if value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "allow", "enabled"}


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(str(value).strip())
    except Exception:
        return default


def normalize_security(value: str, default: str = "auto") -> str:
    value = (value or default or "auto").strip().lower()
    if value in {"aes-128-gcm", "chacha20-poly1305", "auto", "none", "zero", "aes-128-ctr"}:
        return value
    return default


def normalize_network(value: str) -> str:
    value = (value or "tcp").strip().lower()
    if value in {"tcp", "udp"}:
        return value
    return "tcp"


def build_tls_from_query(
    query: Dict[str, List[str]],
    server: str,
    default_enabled: bool,
) -> Optional[Dict[str, Any]]:
    security = first_query(query, "security", "tls", default="")
    enabled = default_enabled
    if security:
        enabled = security.lower() not in {"none", "false", "0", "off", "disable", "disabled"}
    if not enabled:
        return None

    server_name = first_query(query, "sni", "servername", "serverName", "peer", default=server)
    insecure = first_bool(query, "allowInsecure", "allow_insecure", "insecure", "skip-cert-verify", "skip_cert_verify", default=False)
    alpn_text = first_query(query, "alpn", default="")
    fingerprint = first_query(query, "fp", "fingerprint", "client-fingerprint", "client_fingerprint", default="")

    tls: Dict[str, Any] = {"enabled": True}
    if server_name:
        tls["server_name"] = server_name
    if insecure:
        tls["insecure"] = True
    if alpn_text:
        tls["alpn"] = [part.strip() for part in re.split(r"[,|]", alpn_text) if part.strip()]
    if fingerprint:
        tls["utls"] = {
            "enabled": True,
            "fingerprint": fingerprint,
        }

    # Reality support for common Xray URL params.
    public_key = first_query(query, "pbk", "publicKey", "public_key", default="")
    short_id = first_query(query, "sid", "shortId", "short_id", default="")
    spider_x = first_query(query, "spx", "spiderX", "spider_x", default="")
    if security.lower() == "reality" or public_key:
        reality: Dict[str, Any] = {
            "enabled": True,
        }
        if public_key:
            reality["public_key"] = public_key
        if short_id:
            reality["short_id"] = short_id
        if spider_x:
            reality["spider_x"] = spider_x
        tls["reality"] = reality

    return tls


def build_transport_from_query(query: Dict[str, List[str]], fallback_host: str = "") -> Optional[Dict[str, Any]]:
    transport_type = first_query(query, "type", "net", default="tcp").strip().lower()
    if transport_type in {"", "tcp", "none"}:
        return None

    host = first_query(query, "host", "Host", default=fallback_host)
    path = unquote(first_query(query, "path", default="/")) or "/"

    if transport_type in {"ws", "websocket"}:
        out: Dict[str, Any] = {
            "type": "ws",
            "path": path,
        }
        headers: Dict[str, str] = {}
        if host:
            headers["Host"] = host
        if headers:
            out["headers"] = headers
        return out

    if transport_type in {"grpc", "gun"}:
        service_name = first_query(query, "serviceName", "service_name", "path", default="")
        out = {"type": "grpc"}
        if service_name:
            out["service_name"] = unquote(service_name).lstrip("/")
        return out

    if transport_type in {"http", "h2"}:
        out = {
            "type": "http",
            "path": path,
        }
        if host:
            out["host"] = [host]
        return out

    if transport_type in {"httpupgrade", "http-upgrade", "http_upgrade"}:
        out = {
            "type": "httpupgrade",
            "path": path,
        }
        headers = {}
        if host:
            headers["Host"] = host
        if headers:
            out["headers"] = headers
        return out

    # Keep unknown V2Ray transport types as-is, without extra fields.
    return {"type": transport_type}


def build_transport_from_vmess(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    net = str(data.get("net") or data.get("type") or "tcp").strip().lower()
    if net in {"", "tcp", "none"}:
        return None
    host = str(data.get("host") or "").strip()
    path = str(data.get("path") or "/").strip() or "/"

    if net in {"ws", "websocket"}:
        out: Dict[str, Any] = {
            "type": "ws",
            "path": path,
        }
        if host:
            out["headers"] = {"Host": host}
        return out

    if net in {"grpc", "gun"}:
        service_name = str(data.get("path") or data.get("serviceName") or data.get("service_name") or "").strip()
        out = {"type": "grpc"}
        if service_name:
            out["service_name"] = service_name.lstrip("/")
        return out

    if net in {"http", "h2"}:
        out = {"type": "http", "path": path}
        if host:
            out["host"] = [host]
        return out

    if net in {"httpupgrade", "http-upgrade", "http_upgrade"}:
        out = {"type": "httpupgrade", "path": path}
        if host:
            out["headers"] = {"Host": host}
        return out

    return {"type": net}


def build_tls_from_vmess(data: Dict[str, Any], server: str) -> Optional[Dict[str, Any]]:
    tls_flag = str(data.get("tls") or "").strip().lower()
    if tls_flag not in {"tls", "true", "1"}:
        return None
    server_name = str(data.get("sni") or data.get("servername") or data.get("serverName") or data.get("host") or server).strip()
    tls: Dict[str, Any] = {"enabled": True}
    if server_name:
        tls["server_name"] = server_name

    insecure = str(data.get("allowInsecure") or data.get("allow_insecure") or "").strip().lower()
    if insecure in {"1", "true", "yes", "y", "on"}:
        tls["insecure"] = True

    alpn = str(data.get("alpn") or "").strip()
    if alpn:
        tls["alpn"] = [part.strip() for part in re.split(r"[,|]", alpn) if part.strip()]

    fp = str(data.get("fp") or data.get("fingerprint") or "").strip()
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    return tls


def parse_vmess(link: str, used_tags: set[str]) -> Dict[str, Any]:
    payload = link[len("vmess://"):].strip()
    data_text = b64decode_text(payload)
    data = json.loads(data_text)
    if not isinstance(data, dict):
        raise ValueError("VMess payload bukan JSON object")

    server = str(data.get("add") or data.get("server") or "").strip()
    port = to_int(data.get("port"), 0)
    uuid = str(data.get("id") or data.get("uuid") or "").strip()
    if not server or not port or not uuid:
        raise ValueError("VMess wajib punya add/server, port, dan id/uuid")

    tag = unique_tag(str(data.get("ps") or data.get("name") or f"vmess-{server}-{port}"), used_tags)
    outbound: Dict[str, Any] = {
        "type": "vmess",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": normalize_security(str(data.get("scy") or data.get("security") or "auto"), default="auto"),
        "alter_id": to_int(data.get("aid") or data.get("alterId") or data.get("alter_id"), 0),
        "network": "tcp",
    }

    tls = build_tls_from_vmess(data, server)
    if tls:
        outbound["tls"] = tls

    transport = build_transport_from_vmess(data)
    if transport:
        outbound["transport"] = transport

    return outbound


def parse_vless(link: str, used_tags: set[str]) -> Dict[str, Any]:
    parsed = urlparse(link)
    query = parse_qs(parsed.query, keep_blank_values=True)
    server = parsed.hostname or ""
    port = int(parsed.port or 0)
    uuid = unquote(parsed.username or "")
    if not server or not port or not uuid:
        raise ValueError("VLESS wajib punya uuid@server:port")

    tag = unique_tag(unquote(parsed.fragment or f"vless-{server}-{port}"), used_tags)
    outbound: Dict[str, Any] = {
        "type": "vless",
        "tag": tag,
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "network": normalize_network(first_query(query, "network", default="tcp")),
    }

    flow = first_query(query, "flow", default="")
    if flow:
        outbound["flow"] = flow

    tls = build_tls_from_query(query, server, default_enabled=False)
    if tls:
        outbound["tls"] = tls

    transport = build_transport_from_query(query, fallback_host="")
    if transport:
        outbound["transport"] = transport

    packet_encoding = first_query(query, "packetEncoding", "packet_encoding", default="")
    if packet_encoding:
        outbound["packet_encoding"] = packet_encoding

    return outbound


def parse_trojan(link: str, used_tags: set[str]) -> Dict[str, Any]:
    parsed = urlparse(link)
    query = parse_qs(parsed.query, keep_blank_values=True)
    server = parsed.hostname or ""
    port = int(parsed.port or 0)
    password = unquote(parsed.username or "")
    if not server or not port or not password:
        raise ValueError("Trojan wajib punya password@server:port")

    tag = unique_tag(unquote(parsed.fragment or f"trojan-{server}-{port}"), used_tags)
    outbound: Dict[str, Any] = {
        "type": "trojan",
        "tag": tag,
        "server": server,
        "server_port": port,
        "password": password,
        "network": normalize_network(first_query(query, "network", default="tcp")),
    }

    tls = build_tls_from_query(query, server, default_enabled=True)
    if tls:
        outbound["tls"] = tls

    transport = build_transport_from_query(query, fallback_host="")
    if transport:
        outbound["transport"] = transport

    return outbound


def parse_link(link: str, used_tags: set[str]) -> Dict[str, Any]:
    scheme = link.split("://", 1)[0].lower()
    if scheme == "vmess":
        return parse_vmess(link, used_tags)
    if scheme == "vless":
        return parse_vless(link, used_tags)
    if scheme == "trojan":
        return parse_trojan(link, used_tags)
    raise ValueError(f"Unsupported scheme: {scheme}")


def build_dns(new_dns: bool = False) -> Dict[str, Any]:
    if new_dns:
        return {
            "servers": [
                {
                    "type": "udp",
                    "tag": "cloudflare",
                    "server": "1.1.1.1",
                }
            ],
            "final": "cloudflare",
        }
    return {
        "servers": [
            {
                "tag": "cloudflare",
                "address": "1.1.1.1",
            }
        ],
        "final": "cloudflare",
    }


def build_inbounds(legacy_tun: bool = False, include_tun: bool = True, mixed_port: int = 7893) -> List[Dict[str, Any]]:
    inbounds: List[Dict[str, Any]] = []
    if include_tun:
        if legacy_tun:
            inbounds.append(
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "inet4_address": "172.19.0.1/30",
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system",
                }
            )
        else:
            inbounds.append(
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "address": ["172.19.0.1/30"],
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system",
                }
            )
    inbounds.append(
        {
            "type": "mixed",
            "tag": "mixed-in",
            "listen": "127.0.0.1",
            "listen_port": mixed_port,
        }
    )
    return inbounds


def build_profile(
    outbounds_raw: Sequence[Dict[str, Any]],
    profile_tag: str = "PROXY",
    new_dns: bool = False,
    legacy_tun: bool = False,
    include_tun: bool = True,
    mixed_port: int = 7893,
    urltest: bool = True,
    test_url: str = "http://www.gstatic.com/generate_204",
) -> Dict[str, Any]:
    proxy_tags = [item["tag"] for item in outbounds_raw if item.get("tag")]
    final_outbounds: List[Dict[str, Any]] = []

    if proxy_tags:
        selector_choices = ["AUTO-BEST-PING"] + proxy_tags + ["DIRECT"] if urltest and len(proxy_tags) >= 2 else proxy_tags + ["DIRECT"]
        final_outbounds.append(
            {
                "type": "selector",
                "tag": profile_tag,
                "outbounds": selector_choices,
                "default": selector_choices[0],
            }
        )
        if urltest and len(proxy_tags) >= 2:
            final_outbounds.append(
                {
                    "type": "urltest",
                    "tag": "AUTO-BEST-PING",
                    "outbounds": proxy_tags,
                    "url": test_url,
                    "interval": "3m",
                    "tolerance": 50,
                }
            )
        final_outbounds.extend(outbounds_raw)
    else:
        profile_tag = "DIRECT"

    final_outbounds.append({"type": "direct", "tag": "DIRECT"})

    return {
        "log": {
            "level": "info",
            "timestamp": True,
        },
        "dns": build_dns(new_dns=new_dns),
        "inbounds": build_inbounds(legacy_tun=legacy_tun, include_tun=include_tun, mixed_port=mixed_port),
        "outbounds": final_outbounds,
        "route": {
            "auto_detect_interface": True,
            "rules": [
                {
                    "ip_cidr": PRIVATE_CIDRS,
                    "outbound": "DIRECT",
                }
            ],
            "final": profile_tag,
        },
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_links(inputs: Sequence[str], urls: Sequence[str]) -> Tuple[List[str], List[str]]:
    links: List[str] = []
    errors: List[str] = []
    sources = list(inputs) + list(urls)
    for source in sources:
        source = str(source).strip()
        if not source:
            continue
        if not source.startswith(("http://", "https://")) and not Path(source).exists():
            errors.append(f"SKIP missing: {source}")
            continue
        try:
            text = read_text_source(source)
            found = split_links(text)
            links.extend(found)
            print(f"[OK] {source}: {len(found)} link")
        except Exception as exc:
            errors.append(f"ERROR {source}: {exc}")
    return links, errors


def dedupe_links(links: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert vmess/vless/trojan share links to sing-box JSON.")
    parser.add_argument("--input", "-i", action="append", default=[], help="Input .txt file containing share links. Can be repeated.")
    parser.add_argument("--url", action="append", default=[], help="Remote subscription/raw URL containing links. Can be repeated.")
    parser.add_argument("--output-dir", default="output/SingBox", help="Output directory.")
    parser.add_argument("--name", default="from-links", help="Base output profile name.")
    parser.add_argument("--mixed-port", type=int, default=7893, help="Mixed inbound local port.")
    parser.add_argument("--no-tun", action="store_true", help="Do not include TUN inbound.")
    parser.add_argument("--no-urltest", action="store_true", help="Do not generate AUTO-BEST-PING urltest group.")
    parser.add_argument("--test-url", default="http://www.gstatic.com/generate_204", help="URLTest URL.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if no valid links are found or any parse errors occur.")
    args = parser.parse_args()

    input_candidates = args.input or [path for path in DEFAULT_INPUTS if Path(path).exists()]
    links, source_errors = collect_links(input_candidates, args.url)
    links = dedupe_links(links)

    used_tags: set[str] = set()
    outbounds: List[Dict[str, Any]] = []
    parse_errors: List[Dict[str, str]] = []

    for idx, link in enumerate(links, start=1):
        try:
            outbounds.append(parse_link(link, used_tags))
        except Exception as exc:
            parse_errors.append({
                "index": str(idx),
                "link_preview": link[:160],
                "error": str(exc),
            })

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    by_type: Dict[str, List[Dict[str, Any]]] = {"vmess": [], "vless": [], "trojan": []}
    for outbound in outbounds:
        if outbound.get("type") in by_type:
            by_type[outbound["type"]].append(outbound)

    base_profile = build_profile(
        outbounds,
        new_dns=False,
        legacy_tun=False,
        include_tun=not args.no_tun,
        mixed_port=args.mixed_port,
        urltest=not args.no_urltest,
        test_url=args.test_url,
    )
    write_json(output_dir / f"{args.name}.json", base_profile)

    new_dns_profile = build_profile(
        outbounds,
        new_dns=True,
        legacy_tun=False,
        include_tun=not args.no_tun,
        mixed_port=args.mixed_port,
        urltest=not args.no_urltest,
        test_url=args.test_url,
    )
    write_json(output_dir / f"{args.name}-new-dns.json", new_dns_profile)

    legacy_tun_profile = build_profile(
        outbounds,
        new_dns=False,
        legacy_tun=True,
        include_tun=not args.no_tun,
        mixed_port=args.mixed_port,
        urltest=not args.no_urltest,
        test_url=args.test_url,
    )
    write_json(output_dir / f"{args.name}-legacy-tun.json", legacy_tun_profile)

    for protocol, items in by_type.items():
        if items:
            write_json(
                output_dir / f"{protocol}-links.json",
                build_profile(
                    items,
                    new_dns=False,
                    legacy_tun=False,
                    include_tun=not args.no_tun,
                    mixed_port=args.mixed_port,
                    urltest=not args.no_urltest,
                    test_url=args.test_url,
                ),
            )

    summary = {
        "ok": bool(outbounds) and not (args.strict and parse_errors),
        "input_files": input_candidates,
        "input_urls": args.url,
        "source_errors": source_errors,
        "total_links_found": len(links),
        "converted_total": len(outbounds),
        "converted_by_protocol": {key: len(value) for key, value in by_type.items()},
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "outputs": [
            str(output_dir / f"{args.name}.json"),
            str(output_dir / f"{args.name}-new-dns.json"),
            str(output_dir / f"{args.name}-legacy-tun.json"),
        ] + [str(output_dir / f"{protocol}-links.json") for protocol, items in by_type.items() if items],
        "dns": "1.1.1.1 only",
    }
    write_json(output_dir / "summary_from_links.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.strict and (not outbounds or parse_errors):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

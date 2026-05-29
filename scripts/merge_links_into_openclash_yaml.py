#!/usr/bin/env python3
"""
Merge vmess://, vless://, and trojan:// links from input/links.txt into generated OpenClash YAML outputs.

Purpose for SumberYAML:
- Keep the existing generated YAML results from sources/generator.
- Add extra user-provided accounts from input/links.txt as additional proxies.
- Add those extra proxies into proxy-groups so they are selectable/testable.
- Run after validate_openclash_outputs.py when input links are trusted/manual and should not be alive-tested or validation-gated.

Default input candidates:
- input/links.txt
- input/vmess.txt
- input/vless.txt
- input/trojan.txt
- links.txt

Default target YAML files:
- output/lengkap.yaml
- output/lengkap_alive.yaml
- output/strict_alive.yaml
- output/lite.yaml
- output/fast.yaml
- output/gaming.yaml
- output/social_media.yaml
- output/streaming.yaml
- output/working.yaml
- output/general.yaml

The script is intentionally conservative:
- It does not delete existing proxies.
- It de-duplicates by proxy name and server identity.
- It writes output/Validation/merge_links_into_openclash_yaml.json.
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
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML belum tersedia. Install dengan: pip install pyyaml") from exc

SUPPORTED_SCHEMES = {"vmess", "vless", "trojan"}
DEFAULT_INPUTS = [
    "input/links.txt",
    "input/vmess.txt",
    "input/vless.txt",
    "input/trojan.txt",
    "links.txt",
]
DEFAULT_TARGETS = [
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
]
REPORT_PATH = Path("output/Validation/merge_links_into_openclash_yaml.json")


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def b64decode_text(value: str) -> str:
    value = (value or "").strip().replace("\n", "").replace("\r", "")
    value = value.replace("-", "+").replace("_", "/")
    missing = len(value) % 4
    if missing:
        value += "=" * (4 - missing)
    return base64.b64decode(value).decode("utf-8", errors="replace")


def maybe_decode_subscription(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return text
    if any(f"{scheme}://" in raw.lower() for scheme in SUPPORTED_SCHEMES):
        return text
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 24:
        return text
    try:
        decoded = b64decode_text(compact)
    except Exception:
        return text
    if any(f"{scheme}://" in decoded.lower() for scheme in SUPPORTED_SCHEMES):
        return decoded
    return text


def read_text_inputs(paths: Sequence[str]) -> Tuple[str, List[str]]:
    chunks: List[str] = []
    used: List[str] = []
    for item in paths:
        path = Path(item)
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            chunks.append(text)
            used.append(str(path))
    return "\n".join(chunks), used


def split_links(text: str) -> List[str]:
    text = maybe_decode_subscription(text)
    links: List[str] = []
    for token in re.split(r"\s+", text or ""):
        token = token.strip().strip('"').strip("'")
        if not token or token.startswith("#"):
            continue
        if any(token.lower().startswith(f"{scheme}://") for scheme in SUPPORTED_SCHEMES):
            links.append(token)
    return links


def clean_name(value: Any, fallback: str = "proxy") -> str:
    text = unquote(str(value or fallback)).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def prefixed_name(name: str, protocol: str, prefix: str = "LINK") -> str:
    name = clean_name(name, f"{protocol.upper()} INPUT")
    # Avoid duplicated prefix after repeated runs.
    if name.upper().startswith(prefix.upper() + " "):
        return name
    return f"{prefix} {name}"


def unique_name(name: str, used: set[str]) -> str:
    base = clean_name(name)
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    final = f"{base} {idx}"
    used.add(final)
    return final


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(str(value).strip())
    except Exception:
        return default


def first_query(query: Dict[str, List[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in query and query[key]:
            return str(query[key][0])
    return default


def first_bool(query: Dict[str, List[str]], *keys: str, default: bool = False) -> bool:
    raw = first_query(query, *keys, default="")
    if raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on", "allow", "enabled"}


def normalize_network(value: str) -> str:
    value = (value or "tcp").strip().lower()
    aliases = {
        "websocket": "ws",
        "httpupgrade": "ws",  # OpenClash/Clash usually handles this closest as ws.
        "http-upgrade": "ws",
    }
    return aliases.get(value, value or "tcp")


def set_if_truthy(data: Dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value:
        return
    data[key] = value


def add_tls_common(
    proxy: Dict[str, Any],
    query: Dict[str, List[str]],
    server: str,
    default_tls: bool = False,
) -> None:
    security = first_query(query, "security", "tls", default="").strip().lower()
    tls_enabled = default_tls
    if security:
        tls_enabled = security not in {"none", "false", "0", "off", "disable", "disabled"}

    if tls_enabled:
        proxy["tls"] = True
        sni = first_query(query, "sni", "servername", "serverName", "peer", default=server)
        if sni:
            proxy["servername"] = sni
        proxy["skip-cert-verify"] = first_bool(
            query,
            "allowInsecure",
            "allow_insecure",
            "insecure",
            "skip-cert-verify",
            "skip_cert_verify",
            default=False,
        )

        alpn = first_query(query, "alpn", default="")
        if alpn:
            proxy["alpn"] = [part.strip() for part in re.split(r"[,|]", alpn) if part.strip()]

        fp = first_query(query, "fp", "fingerprint", "client-fingerprint", "client_fingerprint", default="")
        if fp:
            proxy["client-fingerprint"] = fp

    if security == "reality" or first_query(query, "pbk", "publicKey", "public_key", default=""):
        proxy["tls"] = True
        proxy.setdefault("skip-cert-verify", False)
        pbk = first_query(query, "pbk", "publicKey", "public_key", default="")
        sid = first_query(query, "sid", "shortId", "short_id", default="")
        reality_opts: Dict[str, Any] = {}
        if pbk:
            reality_opts["public-key"] = pbk
        if sid:
            reality_opts["short-id"] = sid
        if reality_opts:
            proxy["reality-opts"] = reality_opts


def add_transport_common(proxy: Dict[str, Any], query: Dict[str, List[str]], fallback_host: str = "") -> None:
    net = normalize_network(first_query(query, "type", "net", default="tcp"))
    if net in {"", "tcp", "none"}:
        return

    proxy["network"] = net
    path = first_query(query, "path", default="")
    host = first_query(query, "host", "Host", default=fallback_host)
    service_name = first_query(query, "serviceName", "service_name", "grpc-service-name", "grpc_service_name", default=path)

    if net == "ws":
        ws_opts: Dict[str, Any] = {}
        ws_opts["path"] = path or "/"
        if host:
            ws_opts["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_opts
    elif net == "grpc":
        proxy["grpc-opts"] = {"grpc-service-name": service_name or "grpc"}
    elif net in {"h2", "http"}:
        hosts = [item.strip() for item in re.split(r"[,|]", host or "") if item.strip()]
        http_opts: Dict[str, Any] = {}
        if path:
            http_opts["path"] = [path]
        if hosts:
            http_opts["host"] = hosts
        proxy["h2-opts" if net == "h2" else "http-opts"] = http_opts


def parse_vmess(link: str, used: set[str], prefix: str) -> Dict[str, Any]:
    payload = link[len("vmess://"):]
    obj = json.loads(b64decode_text(payload))
    server = str(obj.get("add") or obj.get("server") or "").strip()
    port = to_int(obj.get("port"), 443)
    uuid = str(obj.get("id") or obj.get("uuid") or "").strip()
    if not server or not uuid:
        raise ValueError("VMess link tidak memiliki server/uuid")

    name = unique_name(prefixed_name(obj.get("ps") or f"VMESS {server}", "vmess", prefix), used)
    net = normalize_network(str(obj.get("net") or obj.get("type") or "tcp"))
    tls_text = str(obj.get("tls") or "").strip().lower()
    host = str(obj.get("host") or "").strip()
    path = str(obj.get("path") or "").strip()
    sni = str(obj.get("sni") or obj.get("peer") or host or server).strip()
    fp = str(obj.get("fp") or obj.get("fingerprint") or "").strip()
    alpn_text = str(obj.get("alpn") or "").strip()

    proxy: Dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": to_int(obj.get("aid") or obj.get("alterId"), 0),
        "cipher": str(obj.get("scy") or obj.get("cipher") or "auto"),
        "udp": True,
    }
    if tls_text in {"tls", "true", "1"}:
        proxy["tls"] = True
        proxy["servername"] = sni
        proxy["skip-cert-verify"] = False
        if fp:
            proxy["client-fingerprint"] = fp
        if alpn_text:
            proxy["alpn"] = [part.strip() for part in re.split(r"[,|]", alpn_text) if part.strip()]

    if net not in {"tcp", "none", ""}:
        proxy["network"] = net
        if net == "ws":
            proxy["ws-opts"] = {
                "path": path or "/",
                "headers": {"Host": host or server},
            }
        elif net == "grpc":
            proxy["grpc-opts"] = {"grpc-service-name": path or "grpc"}
        elif net in {"h2", "http"}:
            hosts = [item.strip() for item in re.split(r"[,|]", host or "") if item.strip()]
            proxy["h2-opts" if net == "h2" else "http-opts"] = {
                "path": [path] if path else ["/"],
                "host": hosts or [server],
            }
    return proxy


def parse_vless(link: str, used: set[str], prefix: str) -> Dict[str, Any]:
    parsed = urlparse(link)
    query = parse_qs(parsed.query, keep_blank_values=True)
    uuid = unquote(parsed.username or "").strip()
    server = parsed.hostname or ""
    port = parsed.port or 443
    if not server or not uuid:
        raise ValueError("VLESS link tidak memiliki server/uuid")

    name = unique_name(prefixed_name(parsed.fragment or f"VLESS {server}", "vless", prefix), used)
    proxy: Dict[str, Any] = {
        "name": name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "udp": True,
    }
    flow = first_query(query, "flow", default="")
    if flow:
        proxy["flow"] = flow
    encryption = first_query(query, "encryption", default="")
    if encryption and encryption != "none":
        proxy["encryption"] = encryption

    add_tls_common(proxy, query, server, default_tls=False)
    add_transport_common(proxy, query, fallback_host=server)
    return proxy


def parse_trojan(link: str, used: set[str], prefix: str) -> Dict[str, Any]:
    parsed = urlparse(link)
    query = parse_qs(parsed.query, keep_blank_values=True)
    password = unquote(parsed.username or "").strip()
    server = parsed.hostname or ""
    port = parsed.port or 443
    if not server or not password:
        raise ValueError("Trojan link tidak memiliki server/password")

    name = unique_name(prefixed_name(parsed.fragment or f"TROJAN {server}", "trojan", prefix), used)
    security = first_query(query, "security", "tls", default="")
    default_tls = True if not security else security.strip().lower() not in {"none", "false", "0", "off"}
    proxy: Dict[str, Any] = {
        "name": name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "udp": True,
    }
    add_tls_common(proxy, query, server, default_tls=default_tls)
    add_transport_common(proxy, query, fallback_host=server)
    return proxy


def proxy_identity(proxy: Dict[str, Any]) -> Tuple[str, str, str, str]:
    protocol = str(proxy.get("type", "")).lower()
    server = str(proxy.get("server", "")).lower()
    port = str(proxy.get("port", ""))
    secret = str(proxy.get("uuid") or proxy.get("password") or "")
    return protocol, server, port, secret


def parse_links_to_proxies(links: Sequence[str], prefix: str = "LINK") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    used_names: set[str] = set()
    seen_identity: set[Tuple[str, str, str, str]] = set()
    proxies: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, link in enumerate(links, start=1):
        try:
            scheme = link.split(":", 1)[0].lower()
            if scheme == "vmess":
                proxy = parse_vmess(link, used_names, prefix)
            elif scheme == "vless":
                proxy = parse_vless(link, used_names, prefix)
            elif scheme == "trojan":
                proxy = parse_trojan(link, used_names, prefix)
            else:
                raise ValueError(f"Skema tidak didukung: {scheme}")

            identity = proxy_identity(proxy)
            if identity in seen_identity:
                continue
            seen_identity.add(identity)
            proxies.append(proxy)
        except Exception as exc:
            errors.append({
                "index": idx,
                "link_preview": link[:140],
                "error": str(exc),
            })
    return proxies, errors


def load_yaml_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} bukan YAML object/dict")
    return data


def dump_yaml_file(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def merge_into_yaml(path: Path, link_proxies: Sequence[Dict[str, Any]], add_to_all_groups: bool = True) -> Dict[str, Any]:
    data = load_yaml_file(path)
    proxies = data.get("proxies")
    groups = data.get("proxy-groups")
    if not isinstance(proxies, list):
        proxies = []
        data["proxies"] = proxies
    if not isinstance(groups, list):
        groups = []
        data["proxy-groups"] = groups

    existing_names = {str(item.get("name")) for item in proxies if isinstance(item, dict) and item.get("name")}
    existing_identity = {
        proxy_identity(item)
        for item in proxies
        if isinstance(item, dict) and item.get("server") and (item.get("uuid") or item.get("password"))
    }

    appended: List[str] = []
    final_link_names: List[str] = []
    used_names = set(existing_names)

    for src_proxy in link_proxies:
        proxy = json.loads(json.dumps(src_proxy, ensure_ascii=False))
        identity = proxy_identity(proxy)
        if identity in existing_identity:
            # If the same server/account already exists under another name, use the existing name for group insertion if available.
            for existing in proxies:
                if isinstance(existing, dict) and proxy_identity(existing) == identity and existing.get("name"):
                    final_link_names.append(str(existing["name"]))
                    break
            continue
        original_name = str(proxy.get("name") or "LINK PROXY")
        proxy["name"] = unique_name(original_name, used_names)
        proxies.append(proxy)
        existing_identity.add(identity)
        appended.append(proxy["name"])
        final_link_names.append(proxy["name"])

    group_updates: Dict[str, int] = {}
    if final_link_names:
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("name") or "")
            group_type = str(group.get("type") or "").lower()
            group_proxies = group.get("proxies")
            if not isinstance(group_proxies, list):
                continue
            if group_type not in {"select", "url-test", "urltest", "fallback", "load-balance", "relay"}:
                continue
            # Add to all real proxy groups by default. This keeps the extra accounts selectable in every generated profile.
            if not add_to_all_groups:
                normalized = group_name.strip().upper()
                allowed = any(keyword in normalized for keyword in ["PROXY", "URL-TEST", "FALLBACK", "STABIL", "GAMING", "STREAMING", "SOCIAL", "WORKING", "GENERAL"])
                if not allowed:
                    continue
            before = len(group_proxies)
            for name in final_link_names:
                if name and name not in group_proxies:
                    group_proxies.append(name)
            added = len(group_proxies) - before
            if added:
                group_updates[group_name] = added

    return {
        "path": str(path),
        "proxy_count_before": len(proxies) - len(appended),
        "proxy_count_after": len(proxies),
        "appended_count": len(appended),
        "appended_names": appended,
        "group_updates": group_updates,
    }


def resolve_targets(args_targets: Sequence[str], include_all_output_yaml: bool) -> List[Path]:
    targets: List[Path] = []
    if args_targets:
        candidates = [Path(item) for item in args_targets]
    else:
        candidates = [Path(item) for item in DEFAULT_TARGETS]
    for path in candidates:
        if path.exists() and path.is_file():
            targets.append(path)

    if include_all_output_yaml:
        for path in sorted(Path("output").glob("*.yaml")):
            if path.is_file() and path not in targets:
                targets.append(path)
    return targets


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Merge input vmess/vless/trojan links into OpenClash YAML outputs.")
    parser.add_argument("--input", action="append", default=[], help="Input file. Can be used multiple times. Default: input/links.txt and protocol-specific files.")
    parser.add_argument("--target", action="append", default=[], help="Target YAML file. Can be used multiple times. Default: common output/*.yaml files.")
    parser.add_argument("--prefix", default="LINK", help="Name prefix for proxies converted from links. Default: LINK")
    parser.add_argument("--all-output-yaml", action="store_true", default=True, help="Also scan output/*.yaml files. Default: true")
    parser.add_argument("--only-primary-groups", action="store_true", help="Do not add links to every proxy group; only add to primary/category groups.")
    parser.add_argument("--strict", action="store_true", help="Fail if input file exists but no valid links can be parsed.")
    parser.add_argument("--trusted", action="store_true", help="Treat input links as trusted manual accounts; never fail only because links are absent/unparseable.")
    args = parser.parse_args(argv)

    input_paths = args.input or DEFAULT_INPUTS
    input_text, used_inputs = read_text_inputs(input_paths)
    links = split_links(input_text)
    link_proxies, parse_errors = parse_links_to_proxies(links, prefix=args.prefix)
    targets = resolve_targets(args.target, include_all_output_yaml=args.all_output_yaml)

    report: Dict[str, Any] = {
        "ok": True,
        "trusted_manual_links": bool(args.trusted),
        "validation_gate": False,
        "input_paths_checked": input_paths,
        "input_paths_used": used_inputs,
        "links_found": len(links),
        "links_valid": len(link_proxies),
        "parse_errors": parse_errors,
        "targets_found": [str(path) for path in targets],
        "files": [],
        "total_appended": 0,
    }

    if not used_inputs:
        report["ok"] = True
        report["message"] = "Tidak ada input links file. Merge YAML dilewati."
    elif not links:
        report["ok"] = True if args.trusted else (not args.strict)
        report["message"] = "Input file ada, tetapi tidak ada link vmess/vless/trojan."
    elif not link_proxies:
        report["ok"] = True if args.trusted else (not args.strict)
        report["message"] = "Tidak ada link valid yang bisa dikonversi."
    elif not targets:
        report["ok"] = False
        report["message"] = "Tidak ada target YAML output yang ditemukan."
    else:
        for path in targets:
            try:
                result = merge_into_yaml(
                    path,
                    link_proxies,
                    add_to_all_groups=not args.only_primary_groups,
                )
                dump_yaml_file(path, load_yaml_file(path)) if False else None
                # Re-run actual merge and dump once: merge_into_yaml already mutated a local data object, so reload/dump handling is done below.
            except Exception as exc:
                report["ok"] = False
                report["files"].append({"path": str(path), "ok": False, "error": str(exc)})
                continue

            # The first merge_into_yaml call already saved nothing. To avoid code duplication,
            # reload, merge, dump here correctly. The dry call above validates the file.
            try:
                data = load_yaml_file(path)
                proxies = data.setdefault("proxies", [])
                groups = data.setdefault("proxy-groups", [])
                if not isinstance(proxies, list) or not isinstance(groups, list):
                    raise ValueError("proxies/proxy-groups harus berupa list")

                existing_names = {str(item.get("name")) for item in proxies if isinstance(item, dict) and item.get("name")}
                existing_identity = {
                    proxy_identity(item)
                    for item in proxies
                    if isinstance(item, dict) and item.get("server") and (item.get("uuid") or item.get("password"))
                }
                used_names = set(existing_names)
                appended: List[str] = []
                final_link_names: List[str] = []

                for src_proxy in link_proxies:
                    proxy = json.loads(json.dumps(src_proxy, ensure_ascii=False))
                    identity = proxy_identity(proxy)
                    if identity in existing_identity:
                        for existing in proxies:
                            if isinstance(existing, dict) and proxy_identity(existing) == identity and existing.get("name"):
                                final_link_names.append(str(existing["name"]))
                                break
                        continue
                    proxy["name"] = unique_name(str(proxy.get("name") or "LINK PROXY"), used_names)
                    proxies.append(proxy)
                    existing_identity.add(identity)
                    appended.append(proxy["name"])
                    final_link_names.append(proxy["name"])

                group_updates: Dict[str, int] = {}
                if final_link_names:
                    for group in groups:
                        if not isinstance(group, dict):
                            continue
                        group_name = str(group.get("name") or "")
                        group_type = str(group.get("type") or "").lower()
                        group_proxies = group.get("proxies")
                        if not isinstance(group_proxies, list):
                            continue
                        if group_type not in {"select", "url-test", "urltest", "fallback", "load-balance", "relay"}:
                            continue
                        if args.only_primary_groups:
                            normalized = group_name.strip().upper()
                            allowed = any(keyword in normalized for keyword in ["PROXY", "URL-TEST", "FALLBACK", "STABIL", "GAMING", "STREAMING", "SOCIAL", "WORKING", "GENERAL"])
                            if not allowed:
                                continue
                        before = len(group_proxies)
                        for name in final_link_names:
                            if name and name not in group_proxies:
                                group_proxies.append(name)
                        added = len(group_proxies) - before
                        if added:
                            group_updates[group_name] = added

                dump_yaml_file(path, data)
                file_report = {
                    "path": str(path),
                    "ok": True,
                    "appended_count": len(appended),
                    "appended_names": appended,
                    "proxy_count_after": len(proxies),
                    "group_updates": group_updates,
                }
                report["files"].append(file_report)
                report["total_appended"] += len(appended)
            except Exception as exc:
                report["ok"] = False
                report["files"].append({"path": str(path), "ok": False, "error": str(exc)})

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merge OpenClash links report: {REPORT_PATH}")
    print(json.dumps({
        "ok": report.get("ok"),
        "links_found": report.get("links_found"),
        "links_valid": report.get("links_valid"),
        "targets": len(report.get("targets_found", [])),
        "total_appended": report.get("total_appended", 0),
    }, ensure_ascii=False, indent=2))

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

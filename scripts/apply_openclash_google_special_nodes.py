#!/usr/bin/env python3
"""Strict-safe Google/YouTube special node router for SumberYAML OpenClash output.

Purpose:
- Route every Google-related domain, including YouTube, to a dedicated GOOGLE group.
- Populate GOOGLE from manual input nodes whose names contain Google-related keywords.
- Keep OpenClash compatibility: no load-balance, no lazy/timeout/tcp-concurrent/unified-delay,
  no direct rule target to DIRECT/REJECT, no SS/SSR injection.

Run:
    python scripts/apply_openclash_google_special_nodes.py --root .
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, unquote, urlparse

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML belum tersedia: {exc}", file=sys.stderr)
    sys.exit(2)

GOOGLE_GROUP = "GOOGLE"
GOOGLE_KEYWORDS = (
    "google",
    "youtube",
    "youtu",
    "gmail",
    "gstatic",
    "googlevideo",
    "ytimg",
)
SUPPORTED_INPUT_SCHEMES = {"vmess", "vless", "trojan"}
DROP_TYPES = {"ss", "ssr"}
CDN_NETWORKS = {"ws", "grpc", "h2", "http"}
DEFAULT_OVERRIDE_SERVER = os.environ.get("MANUAL_SERVER_OVERRIDE", "104.17.3.81").strip() or "104.17.3.81"

GOOGLE_RULES = [
    "DOMAIN-SUFFIX,google.com,GOOGLE",
    "DOMAIN-SUFFIX,google.co.id,GOOGLE",
    "DOMAIN-SUFFIX,googleusercontent.com,GOOGLE",
    "DOMAIN-SUFFIX,googleapis.com,GOOGLE",
    "DOMAIN-SUFFIX,gstatic.com,GOOGLE",
    "DOMAIN-SUFFIX,ggpht.com,GOOGLE",
    "DOMAIN-SUFFIX,gvt1.com,GOOGLE",
    "DOMAIN-SUFFIX,gvt2.com,GOOGLE",
    "DOMAIN-SUFFIX,gvt3.com,GOOGLE",
    "DOMAIN-SUFFIX,googlevideo.com,GOOGLE",
    "DOMAIN-SUFFIX,youtube.com,GOOGLE",
    "DOMAIN-SUFFIX,youtu.be,GOOGLE",
    "DOMAIN-SUFFIX,ytimg.com,GOOGLE",
    "DOMAIN-SUFFIX,youtubei.googleapis.com,GOOGLE",
    "DOMAIN-SUFFIX,youtube-nocookie.com,GOOGLE",
    "DOMAIN-SUFFIX,gmail.com,GOOGLE",
    "DOMAIN-SUFFIX,googlemail.com,GOOGLE",
    "DOMAIN-SUFFIX,googledrive.com,GOOGLE",
    "DOMAIN-SUFFIX,drive.google.com,GOOGLE",
    "DOMAIN-SUFFIX,docs.google.com,GOOGLE",
    "DOMAIN-SUFFIX,meet.google.com,GOOGLE",
    "DOMAIN-SUFFIX,googlemeet.com,GOOGLE",
    "DOMAIN-SUFFIX,blogger.com,GOOGLE",
    "DOMAIN-SUFFIX,blogspot.com,GOOGLE",
    "DOMAIN-SUFFIX,appspot.com,GOOGLE",
    "DOMAIN-SUFFIX,firebaseio.com,GOOGLE",
    "DOMAIN-SUFFIX,firebase.google.com,GOOGLE",
    "DOMAIN-SUFFIX,googleadservices.com,GOOGLE",
    "DOMAIN-SUFFIX,googlesyndication.com,GOOGLE",
    "DOMAIN-SUFFIX,googletagmanager.com,GOOGLE",
    "DOMAIN-SUFFIX,google-analytics.com,GOOGLE",
    "DOMAIN-SUFFIX,doubleclick.net,GOOGLE",
    "DOMAIN-SUFFIX,android.com,GOOGLE",
    "DOMAIN-SUFFIX,chrome.com,GOOGLE",
    "DOMAIN-SUFFIX,chromium.org,GOOGLE",
    "DOMAIN-SUFFIX,g.co,GOOGLE",
]

GOOGLE_DOMAIN_KEYS = tuple(
    rule.split(",", 2)[1].lower()
    for rule in GOOGLE_RULES
    if isinstance(rule, str) and rule.startswith("DOMAIN-SUFFIX,")
)

MAIN_OUTPUT_NAMES = {
    "fast.yaml",
    "lite.yaml",
    "lengkap.yaml",
    "lengkap_alive.yaml",
    "strict_alive.yaml",
    "manual_only.yaml",
    "openclash-ready.yaml",
    "openclash-lite-ready.yaml",
    "general.yaml",
    "gaming.yaml",
    "streaming.yaml",
    "social_media.yaml",
    "working.yaml",
}


def b64decode_maybe(value: str) -> str:
    raw = value.strip()
    raw = raw.replace("-", "+").replace("_", "/")
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.b64decode((raw + padding).encode("utf-8"), validate=False).decode("utf-8", errors="replace")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def has_google_keyword(name: str) -> bool:
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in GOOGLE_KEYWORDS)


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def first_qs(query: Dict[str, List[str]], key: str, default: str = "") -> str:
    vals = query.get(key)
    if not vals:
        return default
    return vals[0]


def is_cdn_compatible(proxy: Dict[str, Any]) -> bool:
    ptype = str(proxy.get("type") or "").lower()
    if ptype not in {"vmess", "vless", "trojan"}:
        return False
    network = str(proxy.get("network") or "").lower()
    if network not in CDN_NETWORKS:
        return False
    # Reality should not be forced to Cloudflare IP.
    security = str(proxy.get("security") or "").lower()
    if security == "reality":
        return False
    return True


def apply_server_override(proxy: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(proxy)
    if is_cdn_compatible(result):
        result["server"] = DEFAULT_OVERRIDE_SERVER
    return result


def parse_vmess(uri: str) -> Optional[Dict[str, Any]]:
    try:
        payload = uri.split("://", 1)[1].strip()
        data = json.loads(b64decode_maybe(payload))
        name = normalize_name(str(data.get("ps") or data.get("name") or "vmess-google-input"))
        if not has_google_keyword(name):
            return None
        network = str(data.get("net") or "tcp").lower()
        proxy: Dict[str, Any] = {
            "name": name,
            "type": "vmess",
            "server": str(data.get("add") or data.get("server") or "").strip(),
            "port": to_int(data.get("port"), 443),
            "uuid": str(data.get("id") or data.get("uuid") or "").strip(),
            "alterId": to_int(data.get("aid"), 0),
            "cipher": str(data.get("scy") or data.get("cipher") or "auto"),
            "udp": True,
        }
        if network and network != "tcp":
            proxy["network"] = network
        tls = str(data.get("tls") or "").lower()
        if tls in {"tls", "true", "1"}:
            proxy["tls"] = True
        sni = str(data.get("sni") or data.get("servername") or "").strip()
        if sni:
            proxy["servername"] = sni
        host = str(data.get("host") or "").strip()
        path = str(data.get("path") or "").strip()
        if network == "ws":
            ws_opts: Dict[str, Any] = {}
            if path:
                ws_opts["path"] = path
            if host:
                ws_opts["headers"] = {"Host": host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts
        elif network == "grpc":
            service_name = path.lstrip("/")
            if service_name:
                proxy["grpc-opts"] = {"grpc-service-name": service_name}
        if not proxy.get("server") or not proxy.get("uuid"):
            return None
        return apply_server_override(proxy)
    except Exception:
        return None


def parse_vless(uri: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = urlparse(uri)
        name = normalize_name(unquote(parsed.fragment or "vless-google-input"))
        if not has_google_keyword(name):
            return None
        query = parse_qs(parsed.query)
        network = first_qs(query, "type", "tcp").lower()
        security = first_qs(query, "security", "")
        proxy: Dict[str, Any] = {
            "name": name,
            "type": "vless",
            "server": parsed.hostname or "",
            "port": parsed.port or 443,
            "uuid": parsed.username or "",
            "udp": True,
        }
        if network and network != "tcp":
            proxy["network"] = network
        if security:
            proxy["security"] = security
        if security == "tls":
            proxy["tls"] = True
        flow = first_qs(query, "flow", "")
        if flow:
            proxy["flow"] = flow
        sni = first_qs(query, "sni", first_qs(query, "servername", ""))
        if sni:
            proxy["servername"] = sni
        host = first_qs(query, "host", "")
        path = first_qs(query, "path", "")
        if network == "ws":
            ws_opts: Dict[str, Any] = {}
            if path:
                ws_opts["path"] = unquote(path)
            if host:
                ws_opts["headers"] = {"Host": host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts
        elif network == "grpc":
            service_name = first_qs(query, "serviceName", first_qs(query, "service-name", ""))
            if service_name:
                proxy["grpc-opts"] = {"grpc-service-name": service_name}
        if not proxy.get("server") or not proxy.get("uuid"):
            return None
        return apply_server_override(proxy)
    except Exception:
        return None


def parse_trojan(uri: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = urlparse(uri)
        name = normalize_name(unquote(parsed.fragment or "trojan-google-input"))
        if not has_google_keyword(name):
            return None
        query = parse_qs(parsed.query)
        network = first_qs(query, "type", "tcp").lower()
        security = first_qs(query, "security", "")
        proxy: Dict[str, Any] = {
            "name": name,
            "type": "trojan",
            "server": parsed.hostname or "",
            "port": parsed.port or 443,
            "password": parsed.username or "",
            "udp": True,
        }
        if network and network != "tcp":
            proxy["network"] = network
        if security:
            proxy["security"] = security
        sni = first_qs(query, "sni", first_qs(query, "servername", ""))
        if sni:
            proxy["sni"] = sni
        host = first_qs(query, "host", "")
        path = first_qs(query, "path", "")
        if network == "ws":
            ws_opts: Dict[str, Any] = {}
            if path:
                ws_opts["path"] = unquote(path)
            if host:
                ws_opts["headers"] = {"Host": host}
            if ws_opts:
                proxy["ws-opts"] = ws_opts
        elif network == "grpc":
            service_name = first_qs(query, "serviceName", first_qs(query, "service-name", ""))
            if service_name:
                proxy["grpc-opts"] = {"grpc-service-name": service_name}
        if not proxy.get("server") or not proxy.get("password"):
            return None
        return apply_server_override(proxy)
    except Exception:
        return None


def parse_input_proxy(line: str) -> Optional[Dict[str, Any]]:
    item = line.strip()
    if not item or item.startswith("#"):
        return None
    scheme = item.split("://", 1)[0].lower() if "://" in item else ""
    if scheme in {"ss", "ssr"}:
        return None
    if scheme == "vmess":
        return parse_vmess(item)
    if scheme == "vless":
        return parse_vless(item)
    if scheme == "trojan":
        return parse_trojan(item)
    return None


def load_google_input_proxies(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    input_files = os.environ.get("MANUAL_INPUT_FILES", "input/links.txt,input.txt,links.txt")
    paths = []
    for raw in input_files.split(","):
        raw = raw.strip()
        if raw:
            paths.append(root / raw)
    seen_names = set()
    proxies: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {
        "input_files": [str(p.relative_to(root)) if p.exists() else str(p) for p in paths],
        "links_seen": 0,
        "google_links_loaded": 0,
        "skipped_ss_ssr": 0,
        "skipped_non_google_or_invalid": 0,
    }
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            if "://" in item:
                report["links_seen"] += 1
            scheme = item.split("://", 1)[0].lower() if "://" in item else ""
            if scheme in {"ss", "ssr"}:
                report["skipped_ss_ssr"] += 1
                continue
            proxy = parse_input_proxy(item)
            if not proxy:
                report["skipped_non_google_or_invalid"] += 1
                continue
            name = str(proxy.get("name") or "")
            if name and name not in seen_names:
                seen_names.add(name)
                proxies.append(proxy)
                report["google_links_loaded"] += 1
    return proxies, report


def iter_output_yaml(root: Path) -> List[Path]:
    output = root / "output"
    if not output.exists():
        return []
    files: List[Path] = []
    for path in output.rglob("*.yaml"):
        rel = path.relative_to(output)
        if "Backup" in rel.parts or "Cache" in rel.parts:
            continue
        # Prefer OpenClash full configs. Proxy-only YAML without proxy-groups are harmlessly skipped later.
        if path.name in MAIN_OUTPUT_NAMES or "OpenClash" in rel.parts or path.parent == output:
            files.append(path)
    return sorted(set(files))


def ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def remove_groups(groups: List[Dict[str, Any]], names: Iterable[str]) -> List[Dict[str, Any]]:
    name_set = set(names)
    return [g for g in groups if not (isinstance(g, dict) and str(g.get("name") or "") in name_set)]


def unique_preserve(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def remove_google_rules(rules: List[Any]) -> List[Any]:
    cleaned: List[Any] = []
    for rule in rules:
        if isinstance(rule, str):
            parts = [part.strip() for part in rule.split(",")]
            if len(parts) >= 3:
                kind = parts[0].upper()
                domain = parts[1].lower()
                target = parts[-1].upper()
                if target == GOOGLE_GROUP or (kind == "DOMAIN-SUFFIX" and domain in GOOGLE_DOMAIN_KEYS):
                    continue
        cleaned.append(rule)
    return cleaned


def insert_rules_before_match(existing: List[Any], new_rules: Sequence[str]) -> List[Any]:
    cleaned = remove_google_rules(existing)
    insert_at = len(cleaned)
    for idx, rule in enumerate(cleaned):
        if isinstance(rule, str) and rule.strip().upper().startswith("MATCH,"):
            insert_at = idx
            break
    return cleaned[:insert_at] + list(new_rules) + cleaned[insert_at:]


def add_ref_to_select_group(groups: List[Dict[str, Any]], group_name: str, ref: str, after_candidates: Sequence[str]) -> None:
    for group in groups:
        if not isinstance(group, dict) or str(group.get("name") or "") != group_name:
            continue
        if str(group.get("type") or "").lower() != "select":
            return
        proxies = ensure_list(group.get("proxies"))
        proxies = [str(p) for p in proxies if p]
        if ref in proxies:
            group["proxies"] = proxies
            return
        insert_at = 0
        for candidate in after_candidates:
            if candidate in proxies:
                insert_at = proxies.index(candidate) + 1
                break
        proxies.insert(insert_at, ref)
        group["proxies"] = unique_preserve(proxies)
        return


def sanitize_group(group: Dict[str, Any], valid_refs: set[str]) -> Dict[str, Any]:
    result = deepcopy(group)
    for risky in ("lazy", "timeout", "strategy"):
        result.pop(risky, None)
    gtype = str(result.get("type") or "").lower()
    refs = [str(ref) for ref in ensure_list(result.get("proxies"))]
    clean_refs = []
    for ref in refs:
        if ref in valid_refs and ref not in clean_refs:
            clean_refs.append(ref)
    # Keep DIRECT/REJECT only in select groups.
    if gtype != "select":
        clean_refs = [ref for ref in clean_refs if ref not in {"DIRECT", "REJECT"}]
    result["proxies"] = clean_refs
    return result


def process_yaml(path: Path, google_input_proxies: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        return {"path": str(path), "changed": False, "reason": "not_mapping"}
    proxies = ensure_list(data.get("proxies"))
    groups = ensure_list(data.get("proxy-groups"))
    if not proxies or not groups:
        return {"path": str(path), "changed": False, "reason": "not_openclash_full_config"}

    before = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    # Global strict-safe cleanup for risky keys.
    for top_key in ("tcp-concurrent", "unified-delay"):
        data.pop(top_key, None)

    # Drop SS/SSR proxies.
    clean_proxies: List[Dict[str, Any]] = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        ptype = str(proxy.get("type") or "").lower()
        if ptype in DROP_TYPES:
            continue
        name = str(proxy.get("name") or "").strip()
        if not name:
            continue
        clean_proxies.append(proxy)

    existing_names = {str(p.get("name")) for p in clean_proxies if isinstance(p, dict) and p.get("name")}
    added = 0
    for proxy in google_input_proxies:
        name = str(proxy.get("name") or "")
        if name and name not in existing_names:
            clean_proxies.append(deepcopy(proxy))
            existing_names.add(name)
            added += 1

    # Collect Google node names from input and any already-present Google-named node.
    input_names = {str(p.get("name") or "") for p in google_input_proxies if p.get("name")}
    google_node_names = []
    for proxy in clean_proxies:
        name = str(proxy.get("name") or "")
        if name in input_names or has_google_keyword(name):
            google_node_names.append(name)
    google_node_names = unique_preserve(google_node_names)

    groups = [g for g in groups if isinstance(g, dict) and g.get("name")]
    groups = remove_groups(groups, {"GOOGLE", "GOOGLE-AUTO", "GOOGLE-FALLBACK"})
    group_names_before = {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}

    if google_node_names:
        google_group: Dict[str, Any] = {
            "name": GOOGLE_GROUP,
            "type": "fallback",
            "proxies": google_node_names,
            "url": "http://www.gstatic.com/generate_204",
            "interval": 60,
        }
    else:
        fallback_refs = [ref for ref in ["UTAMA", "AUTO", "FALLBACK", "DEFAULT", "PROXY"] if ref in group_names_before]
        if not fallback_refs:
            fallback_refs = ["DIRECT"]
        google_group = {
            "name": GOOGLE_GROUP,
            "type": "select",
            "proxies": fallback_refs,
        }
    # Put GOOGLE near the top, after PROXY when possible.
    insert_at = 0
    for idx, group in enumerate(groups):
        if str(group.get("name") or "") == "PROXY":
            insert_at = idx + 1
            break
    groups.insert(insert_at, google_group)

    group_names = {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}
    valid_refs = existing_names | group_names | {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
    groups = [sanitize_group(g, valid_refs) for g in groups]
    # After sanitizing, keep GOOGLE group even if select fallback or has actual nodes. If fallback has no proxies, make safe select.
    for group in groups:
        if str(group.get("name") or "") == GOOGLE_GROUP and not group.get("proxies"):
            group["type"] = "select"
            group["proxies"] = [ref for ref in ["UTAMA", "AUTO", "FALLBACK", "DEFAULT", "PROXY", "DIRECT"] if ref in valid_refs]
            if not group["proxies"]:
                group["proxies"] = ["DIRECT"]
    add_ref_to_select_group(groups, "PROXY", GOOGLE_GROUP, after_candidates=["UTAMA", "INPUT-VMESS", "AUTO"])

    data["proxies"] = clean_proxies
    data["proxy-groups"] = groups
    data["rules"] = insert_rules_before_match(ensure_list(data.get("rules")), GOOGLE_RULES)

    after = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    changed = before != after
    if changed:
        path.write_text(after, encoding="utf-8")
    return {
        "path": str(path),
        "changed": changed,
        "added_google_input_proxies": added,
        "google_nodes": google_node_names,
        "google_node_count": len(google_node_names),
        "google_group_type": google_group.get("type"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = root / "output"
    if not output.exists():
        print("ERROR: folder output tidak ditemukan.", file=sys.stderr)
        return 1

    google_input_proxies, input_report = load_google_input_proxies(root)
    yaml_files = iter_output_yaml(root)
    results = []
    for path in yaml_files:
        try:
            results.append(process_yaml(path, google_input_proxies))
        except Exception as exc:
            results.append({"path": str(path), "changed": False, "error": str(exc)})

    validation_dir = output / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "sumberyaml.google-special-nodes.v1",
        "policy": {
            "target_group": GOOGLE_GROUP,
            "rule_target_direct_or_reject": False,
            "ss_ssr_allowed": False,
            "load_balance_used": False,
            "server_override_for_cdn_compatible_input_nodes": DEFAULT_OVERRIDE_SERVER,
        },
        "input": input_report,
        "google_input_proxy_names": [p.get("name") for p in google_input_proxies],
        "files_processed": len(results),
        "files_changed": sum(1 for item in results if item.get("changed")),
        "results": results,
    }
    (validation_dir / "google_special_nodes_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

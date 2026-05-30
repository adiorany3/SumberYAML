#!/usr/bin/env python3
"""Build final ready-to-import profiles for SumberYAML.

Creates:
- output/SingBox/import-ready.json       -> safest sing-box profile for QR/import
- output/openclash-ready.yaml            -> final OpenClash YAML
- output/Final/summary_ready_profiles.json

Design goals:
- self-healing: fix common dependency/import issues at the very end
- mobile-friendly sing-box defaults
- preserve trusted manual accounts from input/links.txt / input.txt whenever already converted
- avoid removing manual LINK accounts unless their outbound object is unparsable/missing tag
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path.cwd()
SINGBOX_DIR = ROOT / "output" / "SingBox"
FINAL_DIR = ROOT / "output" / "Final"
HEALTH_DIR = ROOT / "output" / "Health"
VALIDATION_DIR = ROOT / "output" / "Validation"

SINGBOX_CANDIDATES = [
    "mobile-stable-safe.json",
    "best-stable-safe.json",
    "latest-safe.json",
    "lengkap-safe.json",
    "fallback-stable-safe.json",
    "mobile-stable.json",
    "best-stable.json",
    "latest.json",
    "lengkap.json",
    "manual-links-safe.json",
    "manual-links.json",
]

OPENCLASH_CANDIDATES = [
    "output/lengkap.yaml",
    "output/strict_alive.yaml",
    "output/lengkap_alive.yaml",
    "output/fast.yaml",
    "output/lite.yaml",
]

LAN_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
]

GROUP_TYPES = {"selector", "urltest"}
NODE_TYPES = {
    "vmess", "vless", "trojan", "shadowsocks", "hysteria", "hysteria2",
    "tuic", "wireguard", "ssh", "http", "socks", "shadowtls",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_yaml(path: Path) -> Optional[dict]:
    if yaml is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_yaml(path: Path, data: dict) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write YAML profiles")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=120)


def clean_list(values: Iterable[Any]) -> List[str]:
    seen = set()
    out = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def is_group_outbound(item: dict) -> bool:
    return isinstance(item, dict) and item.get("type") in GROUP_TYPES and isinstance(item.get("outbounds"), list)


def is_node_outbound(item: dict) -> bool:
    return isinstance(item, dict) and str(item.get("type", "")).lower() in NODE_TYPES and bool(str(item.get("tag", "")).strip())


def node_tags(outbounds: Sequence[dict], include_manual: bool = True) -> List[str]:
    tags = []
    for item in outbounds:
        if not is_node_outbound(item):
            continue
        tag = str(item.get("tag", "")).strip()
        if not include_manual and is_manual_tag(tag):
            continue
        tags.append(tag)
    return clean_list(tags)


def is_manual_tag(tag: str) -> bool:
    t = str(tag or "").strip().lower()
    return t.startswith("link ") or t.startswith("manual ") or t.startswith("input ") or " from-links" in t


def manual_tags(outbounds: Sequence[dict]) -> List[str]:
    return [tag for tag in node_tags(outbounds, include_manual=True) if is_manual_tag(tag)]


def tag_index(outbounds: Sequence[dict]) -> Dict[str, dict]:
    result = {}
    for item in outbounds:
        if isinstance(item, dict):
            tag = str(item.get("tag", "")).strip()
            if tag and tag not in result:
                result[tag] = item
    return result


def ensure_direct(outbounds: List[dict]) -> None:
    if "DIRECT" not in {str(item.get("tag", "")) for item in outbounds if isinstance(item, dict)}:
        outbounds.append({"type": "direct", "tag": "DIRECT"})


def unique_outbound_tags(data: dict, report: dict) -> None:
    outbounds = data.setdefault("outbounds", [])
    if not isinstance(outbounds, list):
        data["outbounds"] = []
        return

    seen = {}
    renamed_by_original: Dict[str, List[str]] = {}

    for item in outbounds:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag", "")).strip()
        if not tag:
            continue
        if tag not in seen:
            seen[tag] = 1
            continue
        seen[tag] += 1
        new_tag = f"{tag}-{seen[tag]}"
        while new_tag in seen:
            seen[tag] += 1
            new_tag = f"{tag}-{seen[tag]}"
        item["tag"] = new_tag
        seen[new_tag] = 1
        renamed_by_original.setdefault(tag, []).append(new_tag)
        report.setdefault("renamed_duplicate_tags", []).append({"from": tag, "to": new_tag})

    if not renamed_by_original:
        return

    # If a group referenced a duplicated tag, append renamed siblings too so no account is lost.
    for item in outbounds:
        if not is_group_outbound(item):
            continue
        refs = clean_list(item.get("outbounds", []))
        expanded = list(refs)
        for ref in refs:
            expanded.extend(renamed_by_original.get(ref, []))
        item["outbounds"] = clean_list(expanded)


def normalize_tun_modern(data: dict, report: dict) -> None:
    inbounds = data.get("inbounds")
    if not isinstance(inbounds, list):
        return
    for inbound in inbounds:
        if not isinstance(inbound, dict) or inbound.get("type") != "tun":
            continue

        def merge_legacy(new_key: str, *old_keys: str) -> None:
            values = []
            existing = inbound.get(new_key)
            if isinstance(existing, list):
                values.extend(existing)
            elif existing:
                values.append(existing)
            for old_key in old_keys:
                old_value = inbound.pop(old_key, None)
                if isinstance(old_value, list):
                    values.extend(old_value)
                    report.setdefault("removed_legacy_tun_fields", []).append(old_key)
                elif old_value:
                    values.append(old_value)
                    report.setdefault("removed_legacy_tun_fields", []).append(old_key)
            if values:
                inbound[new_key] = clean_list(values)

        merge_legacy("address", "inet4_address", "inet6_address")
        merge_legacy("route_address", "inet4_route_address", "inet6_route_address")
        merge_legacy("route_exclude_address", "inet4_route_exclude_address", "inet6_route_exclude_address")

        if "address" not in inbound:
            inbound["address"] = ["172.19.0.1/30"]

        # Avoid very new fields that older mobile clients may reject.
        for key in ["dns_mode"]:
            if key in inbound:
                inbound.pop(key, None)
                report.setdefault("removed_risky_inbound_fields", []).append(key)


def stable_dns_legacy(data: dict) -> None:
    data["dns"] = {
        "servers": [
            {"tag": "cloudflare", "address": "1.1.1.1"},
            {"tag": "google", "address": "8.8.8.8"},
        ],
        "final": "cloudflare",
    }


def remove_selector_defaults(data: dict, report: dict) -> None:
    for item in data.get("outbounds", []) or []:
        if not isinstance(item, dict) or item.get("type") != "selector":
            continue
        default = item.pop("default", None)
        if default:
            refs = clean_list(item.get("outbounds", []))
            if default in refs:
                refs.remove(default)
                refs.insert(0, default)
            item["outbounds"] = refs
            report.setdefault("removed_selector_default", []).append({"selector": item.get("tag"), "default": default})


def ensure_urltest_group(outbounds: List[dict], tag: str, refs: List[str], *, report: dict) -> None:
    refs = clean_list([r for r in refs if r and r != tag])
    existing = None
    for item in outbounds:
        if isinstance(item, dict) and item.get("tag") == tag:
            existing = item
            break
    if not refs:
        return
    group = {
        "type": "urltest",
        "tag": tag,
        "outbounds": refs,
        "url": "https://www.gstatic.com/generate_204",
        "interval": "3m",
        "tolerance": 80,
        "idle_timeout": "2h",
        "interrupt_exist_connections": False,
    }
    if existing is None:
        outbounds.append(group)
        report.setdefault("created_groups", []).append(tag)
    else:
        existing.clear()
        existing.update(group)
        report.setdefault("updated_groups", []).append(tag)


def ensure_selector_group(outbounds: List[dict], tag: str, refs: List[str], *, report: dict) -> None:
    refs = clean_list([r for r in refs if r and r != tag])
    if not refs:
        refs = ["DIRECT"]
    existing = None
    for item in outbounds:
        if isinstance(item, dict) and item.get("tag") == tag:
            existing = item
            break
    group = {
        "type": "selector",
        "tag": tag,
        "outbounds": refs,
        "interrupt_exist_connections": False,
    }
    if existing is None:
        outbounds.append(group)
        report.setdefault("created_groups", []).append(tag)
    else:
        existing.clear()
        existing.update(group)
        report.setdefault("updated_groups", []).append(tag)


def fix_group_dependencies(data: dict, report: dict) -> None:
    outbounds = data.setdefault("outbounds", [])
    if not isinstance(outbounds, list):
        data["outbounds"] = []
        outbounds = data["outbounds"]

    ensure_direct(outbounds)
    unique_outbound_tags(data, report)

    tags = set(tag_index(outbounds))
    nodes_all = node_tags(outbounds, include_manual=True)
    manual = manual_tags(outbounds)
    non_manual = [tag for tag in nodes_all if tag not in set(manual)]

    if manual:
        ensure_urltest_group(outbounds, "best-link", manual, report=report)

    auto_candidates = clean_list(non_manual[:15] + manual[:9999])
    if auto_candidates:
        ensure_urltest_group(outbounds, "AUTO-BEST-PING", auto_candidates, report=report)

    # Prefer mobile-stable groups but keep dependencies valid.
    tags = set(tag_index(outbounds))
    preferred = []
    for candidate in ["AUTO-BEST-STABLE", "AUTO-BEST-PING", "best-link"]:
        if candidate in tags:
            preferred.append(candidate)
    preferred.extend(nodes_all[:10])
    preferred.append("DIRECT")
    ensure_selector_group(outbounds, "PROXY", preferred, report=report)

    tags = set(tag_index(outbounds))
    for item in outbounds:
        if not is_group_outbound(item):
            continue
        original = clean_list(item.get("outbounds", []))
        fixed = [ref for ref in original if ref in tags and ref != item.get("tag")]
        if not fixed:
            if nodes_all:
                fixed = [nodes_all[0]]
            else:
                fixed = ["DIRECT"]
        if fixed != original:
            report.setdefault("fixed_missing_group_refs", []).append({
                "group": item.get("tag"),
                "before": original,
                "after": fixed,
            })
        item["outbounds"] = clean_list(fixed)

    # Route final must exist.
    tags = set(tag_index(outbounds))
    route = data.setdefault("route", {})
    if not isinstance(route, dict):
        data["route"] = {"final": "PROXY"}
    else:
        final = str(route.get("final", "")).strip()
        if final not in tags:
            route["final"] = "PROXY" if "PROXY" in tags else "DIRECT"
            report.setdefault("fixed_route_final", []).append({"from": final, "to": route["final"]})


def sanitize_singbox_for_import(data: dict) -> Tuple[dict, dict]:
    data = deepcopy(data)
    report: Dict[str, Any] = {}
    data.setdefault("log", {"level": "info"})
    normalize_tun_modern(data, report)
    stable_dns_legacy(data)
    remove_selector_defaults(data, report)
    fix_group_dependencies(data, report)

    # Avoid legacy/deprecated special outbound patterns.
    cleaned = []
    removed = []
    for item in data.get("outbounds", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"block", "dns"}:
            removed.append(item.get("tag") or item.get("type"))
            continue
        cleaned.append(item)
    if removed:
        report["removed_deprecated_special_outbounds"] = removed
    data["outbounds"] = cleaned
    fix_group_dependencies(data, report)
    return data, report


def choose_singbox_source() -> Optional[Path]:
    for name in SINGBOX_CANDIDATES:
        path = SINGBOX_DIR / name
        if path.is_file() and read_json(path):
            return path
    for path in sorted(SINGBOX_DIR.glob("*.json")):
        if path.name.startswith("summary_"):
            continue
        if read_json(path):
            return path
    return None


def read_csv_rows(path: Path) -> List[dict]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def parse_delay(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def stable_yaml_candidates(proxy_set: set[str], manual_set: set[str], max_count: int = 10) -> List[str]:
    candidates = []
    for path in [
        ROOT / "output" / "BestPing" / "top5_indonesia_ping.csv",
        ROOT / "output" / "BestPing" / "top5_best_ping.csv",
        ROOT / "output" / "Alive" / "alive.csv",
        ROOT / "output" / "Alive" / "check_result.csv",
    ]:
        rows = read_csv_rows(path)
        for row in rows:
            name = str(row.get("name") or row.get("proxy") or "").strip()
            if not name or name not in proxy_set or name in manual_set:
                continue
            status = str(row.get("status") or "alive").lower()
            if status not in {"alive", "ok", "success", ""}:
                continue
            delay = parse_delay(row.get("delay_ms") or row.get("delay") or row.get("latency"))
            score = delay if delay is not None else 999999
            candidates.append((score, name))
    candidates.sort(key=lambda item: item[0])
    out = []
    for _, name in candidates:
        if name not in out:
            out.append(name)
        if len(out) >= max_count:
            break
    return out


def upsert_yaml_group(groups: List[dict], group: dict) -> None:
    name = group.get("name")
    for idx, item in enumerate(groups):
        if isinstance(item, dict) and item.get("name") == name:
            groups[idx] = group
            return
    groups.append(group)


def sanitize_yaml_group_refs(data: dict, report: dict) -> None:
    proxies = data.setdefault("proxies", [])
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(proxies, list):
        data["proxies"] = []
        proxies = data["proxies"]
    if not isinstance(groups, list):
        data["proxy-groups"] = []
        groups = data["proxy-groups"]

    proxy_set = {str(p.get("name", "")).strip() for p in proxies if isinstance(p, dict) and p.get("name")}
    group_set = {str(g.get("name", "")).strip() for g in groups if isinstance(g, dict) and g.get("name")}
    valid = proxy_set | group_set | {"DIRECT", "REJECT", "GLOBAL"}

    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("proxies"), list):
            continue
        before = clean_list(group.get("proxies", []))
        after = [ref for ref in before if ref in valid and ref != group.get("name")]
        if not after:
            if proxy_set:
                after = [next(iter(proxy_set))]
            else:
                after = ["DIRECT"]
        if after != before:
            report.setdefault("yaml_fixed_group_refs", []).append({"group": group.get("name"), "before": before, "after": after})
        group["proxies"] = clean_list(after)


def apply_yaml_responsive_defaults(data: dict, report: dict) -> None:
    proxies = data.setdefault("proxies", [])
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(proxies, list) or not isinstance(groups, list):
        return

    proxy_names = clean_list([p.get("name") for p in proxies if isinstance(p, dict) and p.get("name")])
    proxy_set = set(proxy_names)
    manual = [name for name in proxy_names if is_manual_tag(name)]
    manual_set = set(manual)
    stable = stable_yaml_candidates(proxy_set, manual_set, 10)
    if not stable:
        stable = [name for name in proxy_names if name not in manual_set][:10]
    if not stable and manual:
        stable = manual[:10]

    if stable:
        upsert_yaml_group(groups, {
            "name": "BEST-STABLE",
            "type": "url-test",
            "proxies": stable,
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        })
        report["best_stable_count"] = len(stable)

    if manual:
        upsert_yaml_group(groups, {
            "name": "best-link",
            "type": "url-test",
            "proxies": manual,
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 80,
            "lazy": True,
        })
        upsert_yaml_group(groups, {
            "name": "fallback-link",
            "type": "fallback",
            "proxies": manual,
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "lazy": True,
        })
        report["manual_link_count"] = len(manual)

    group_names = {str(g.get("name", "")).strip() for g in groups if isinstance(g, dict)}
    preferred = []
    for name in ["BEST-STABLE", "fallback-link", "best-link", "URL-TEST TOP 5 INDONESIA", "URL-TEST", "FALLBACK", "FALLBACK CEPAT", "DIRECT"]:
        if name == "DIRECT" or name in group_names or name in proxy_set:
            preferred.append(name)

    # Update PROXY or create it.
    proxy_group = None
    for group in groups:
        if isinstance(group, dict) and group.get("name") == "PROXY":
            proxy_group = group
            break
    if proxy_group is None:
        proxy_group = {"name": "PROXY", "type": "select", "proxies": preferred or ["DIRECT"]}
        groups.insert(0, proxy_group)
        report.setdefault("created_yaml_groups", []).append("PROXY")
    else:
        existing = clean_list(proxy_group.get("proxies", []))
        proxy_group["type"] = "select"
        proxy_group["proxies"] = clean_list(preferred + existing)

    # Make health-check groups less aggressive and mobile/router friendly.
    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("type") in {"url-test", "fallback", "load-balance"}:
            group.setdefault("url", "https://www.gstatic.com/generate_204")
            group["interval"] = int(group.get("interval") or 300)
            group["lazy"] = True
            if group.get("type") == "url-test":
                group["tolerance"] = int(group.get("tolerance") or 80)

    # DNS fallback stable.
    dns = data.setdefault("dns", {})
    if isinstance(dns, dict):
        dns["enable"] = True
        dns["ipv6"] = False
        dns["enhanced-mode"] = dns.get("enhanced-mode") or "fake-ip"
        dns["nameserver"] = ["1.1.1.1"]
        dns["fallback"] = ["8.8.8.8"]

    # LAN direct rules before MATCH.
    rules = data.setdefault("rules", [])
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules
    existing_rules = [str(r) for r in rules]
    insert_rules = [r for r in LAN_RULES if r not in existing_rules]
    if insert_rules:
        # Put before first MATCH if present.
        idx = next((i for i, r in enumerate(rules) if str(r).startswith("MATCH,")), len(rules))
        rules[idx:idx] = insert_rules
        report["added_lan_rules"] = len(insert_rules)
    if not any(str(r).startswith("MATCH,") for r in rules):
        rules.append("MATCH,PROXY")

    sanitize_yaml_group_refs(data, report)


def choose_openclash_source() -> Optional[Path]:
    for rel in OPENCLASH_CANDIDATES:
        path = ROOT / rel
        if path.is_file() and read_yaml(path):
            return path
    for path in sorted((ROOT / "output").glob("*.yaml")):
        if read_yaml(path):
            return path
    return None


def write_profile_urls() -> dict:
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    ref = os.getenv("GITHUB_REF_NAME", "main").strip() or "main"
    raw_url = ""
    cdn_url = ""
    if repo:
        raw_url = f"https://raw.githubusercontent.com/{repo}/{ref}/output/SingBox/import-ready.json"
        cdn_url = f"https://cdn.jsdelivr.net/gh/{repo}@{ref}/output/SingBox/import-ready.json"
        (SINGBOX_DIR / "import-ready-raw-url.txt").write_text(raw_url + "\n", encoding="utf-8")
        (SINGBOX_DIR / "import-ready-cdn-url.txt").write_text(cdn_url + "\n", encoding="utf-8")
    return {"raw_url": raw_url, "cdn_url": cdn_url}


def main() -> int:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    SINGBOX_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {
        "generated_at": now_iso(),
        "singbox": {},
        "openclash": {},
        "notes": [
            "import-ready.json is the recommended sing-box profile for public QR.",
            "openclash-ready.yaml is the recommended OpenClash YAML profile.",
            "Trusted manual LINK accounts are preserved when they already exist in generated YAML/JSON.",
        ],
    }

    source = choose_singbox_source()
    if source is not None:
        data = read_json(source) or {}
        fixed, report = sanitize_singbox_for_import(data)
        import_ready = SINGBOX_DIR / "import-ready.json"
        write_json(import_ready, fixed)
        # Keep latest-safe aligned with import-ready only if it exists or no latest-safe exists.
        if not (SINGBOX_DIR / "latest-safe.json").exists():
            write_json(SINGBOX_DIR / "latest-safe.json", fixed)
        urls = write_profile_urls()
        summary["singbox"] = {
            "ok": True,
            "source": str(source.relative_to(ROOT)),
            "output": "output/SingBox/import-ready.json",
            "outbound_count": len(fixed.get("outbounds", []) or []),
            "manual_link_count": len(manual_tags(fixed.get("outbounds", []) or [])),
            "urls": urls,
            "fix_report": report,
        }
    else:
        summary["singbox"] = {"ok": False, "error": "No valid output/SingBox/*.json source found"}

    yaml_source = choose_openclash_source()
    if yaml_source is not None:
        data = read_yaml(yaml_source) or {}
        yaml_report: Dict[str, Any] = {}
        apply_yaml_responsive_defaults(data, yaml_report)
        ready_yaml = ROOT / "output" / "openclash-ready.yaml"
        write_yaml(ready_yaml, data)
        summary["openclash"] = {
            "ok": True,
            "source": str(yaml_source.relative_to(ROOT)),
            "output": "output/openclash-ready.yaml",
            "proxy_count": len(data.get("proxies", []) or []),
            "group_count": len(data.get("proxy-groups", []) or []),
            "manual_link_count": yaml_report.get("manual_link_count", 0),
            "fix_report": yaml_report,
        }
    else:
        summary["openclash"] = {"ok": False, "error": "No valid output/*.yaml source found"}

    write_json(FINAL_DIR / "summary_ready_profiles.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("singbox", {}).get("ok") or summary.get("openclash", {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

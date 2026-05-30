#!/usr/bin/env python3
"""Add a best-link group containing all trusted manual accounts from input/links.txt/input.txt.

Purpose for SumberYAML:
- Manual accounts from input/links.txt or input.txt are trusted and must not be filtered.
- This post-process script creates a group named `best-link` in both OpenClash YAML and sing-box JSON outputs.
- The group contains every manual account currently present in the outputs.
- The script does not remove manual accounts. It only adds/updates the group and references.

OpenClash output:
- Adds/updates proxy-group:
    name: best-link
    type: url-test
    proxies: [all LINK-prefixed proxy names]
- Adds `best-link` into common selector groups when present.

sing-box output:
- Adds/updates outbound:
    {"type":"urltest", "tag":"best-link", "outbounds":[all LINK-prefixed outbound tags], ...}
- Adds `best-link` into PROXY selectors when present.
- Does not use selector.default for legacy client compatibility.

Reports:
- output/Validation/summary_best_link_group_yaml.json
- output/SingBox/summary_best_link_group.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML belum tersedia. Install dengan: pip install pyyaml") from exc

REGULAR_SINGBOX_TYPES = {
    "vless",
    "vmess",
    "trojan",
    "shadowsocks",
    "hysteria",
    "hysteria2",
    "tuic",
}
GROUP_SINGBOX_TYPES = {"selector", "urltest"}

DEFAULT_YAML_FILES = [
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

YAML_REPORT = Path("output/Validation/summary_best_link_group_yaml.json")
SINGBOX_REPORT = Path("output/SingBox/summary_best_link_group.json")

COMMON_PROXY_GROUPS = {
    "PROXY",
    "AUTO",
    "MANUAL",
    "SELECT",
    "GLOBAL",
    "URL-TEST",
    "URL-TEST TOP 5 INDONESIA",
    "FALLBACK",
    "FALLBACK CEPAT",
    "GAMING STABIL",
    "STREAMING STABIL",
    "SOCIAL MEDIA STABIL",
    "WORKING STABIL",
    "GENERAL STABIL",
}


def log(message: str) -> None:
    print(message, flush=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_manual_name(name: Any, manual_prefix: str) -> bool:
    text = clean_name(name)
    if not text:
        return False
    prefix = manual_prefix.strip().upper()
    return text.upper().startswith(prefix + " ") or text.upper() == prefix


def unique_list(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = clean_name(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"[WARN] gagal baca YAML {path}: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("proxies", [])
    data.setdefault("proxy-groups", [])
    if not isinstance(data.get("proxies"), list):
        data["proxies"] = []
    if not isinstance(data.get("proxy-groups"), list):
        data["proxy-groups"] = []
    return data


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def collect_manual_yaml_names(data: Dict[str, Any], manual_prefix: str) -> List[str]:
    proxies = data.get("proxies", [])
    names: List[str] = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        name = clean_name(proxy.get("name"))
        if is_manual_name(name, manual_prefix):
            names.append(name)
    return unique_list(names)


def ensure_yaml_group(data: Dict[str, Any], group_name: str, manual_names: List[str]) -> Tuple[bool, Dict[str, Any]]:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        groups = []
        data["proxy-groups"] = groups

    existing: Optional[Dict[str, Any]] = None
    for group in groups:
        if isinstance(group, dict) and clean_name(group.get("name")) == group_name:
            existing = group
            break

    changed = False
    if existing is None:
        existing = {
            "name": group_name,
            "type": "url-test",
            "proxies": manual_names[:],
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 80,
        }
        groups.insert(0, existing)
        changed = True
    else:
        before = json.dumps(existing, sort_keys=True, ensure_ascii=False)
        existing["type"] = "url-test"
        existing["proxies"] = manual_names[:]
        existing.setdefault("url", "https://www.gstatic.com/generate_204")
        existing.setdefault("interval", 300)
        existing.setdefault("tolerance", 80)
        after = json.dumps(existing, sort_keys=True, ensure_ascii=False)
        changed = changed or before != after

    valid_proxy_names = {
        clean_name(proxy.get("name"))
        for proxy in data.get("proxies", [])
        if isinstance(proxy, dict) and clean_name(proxy.get("name"))
    }
    group_names = {
        clean_name(group.get("name"))
        for group in groups
        if isinstance(group, dict) and clean_name(group.get("name"))
    }
    valid_targets = valid_proxy_names | group_names | {"DIRECT", "REJECT"}

    for group in groups:
        if not isinstance(group, dict):
            continue
        name = clean_name(group.get("name"))
        if name == group_name:
            continue
        proxies = group.get("proxies")
        if not isinstance(proxies, list):
            continue
        if not name:
            continue
        # Put best-link into common selector/fallback groups only. Avoid injecting into every generated url-test group.
        if name.upper() in COMMON_PROXY_GROUPS or group.get("type") in {"select", "fallback", "load-balance"}:
            if group_name not in proxies:
                group["proxies"] = [group_name] + [p for p in proxies if p != group_name]
                changed = True
        # Keep group references clean after injection.
        cleaned = [p for p in group.get("proxies", []) if p in valid_targets or p == group_name]
        if cleaned != group.get("proxies", []):
            group["proxies"] = cleaned
            changed = True

    return changed, existing


def process_yaml_files(files: Sequence[str], group_name: str, manual_prefix: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "group_name": group_name,
        "manual_prefix": manual_prefix,
        "files": [],
        "total_files": 0,
        "changed_files": 0,
        "total_manual_accounts": 0,
    }
    for item in files:
        path = Path(item)
        if not path.exists():
            continue
        data = read_yaml(path)
        if data is None:
            continue
        manual_names = collect_manual_yaml_names(data, manual_prefix)
        file_info = {
            "path": str(path),
            "manual_count": len(manual_names),
            "manual_names": manual_names,
            "changed": False,
            "status": "skipped_no_manual_accounts" if not manual_names else "ok",
        }
        report["total_files"] += 1
        report["total_manual_accounts"] += len(manual_names)
        if manual_names:
            changed, group = ensure_yaml_group(data, group_name, manual_names)
            file_info["changed"] = changed
            file_info["group_type"] = group.get("type")
            file_info["group_proxy_count"] = len(group.get("proxies", [])) if isinstance(group, dict) else 0
            if changed:
                write_yaml(path, data)
                report["changed_files"] += 1
        report["files"].append(file_info)
    YAML_REPORT.parent.mkdir(parents=True, exist_ok=True)
    write_json(YAML_REPORT, report)
    return report


def is_summary_json(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("summary") or name in {"health_state.json"}


def collect_manual_singbox_tags(data: Dict[str, Any], manual_prefix: str) -> List[str]:
    outbounds = data.get("outbounds", [])
    if not isinstance(outbounds, list):
        return []
    tags: List[str] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        typ = str(outbound.get("type") or "").lower()
        tag = clean_name(outbound.get("tag"))
        if typ in REGULAR_SINGBOX_TYPES and is_manual_name(tag, manual_prefix):
            tags.append(tag)
    return unique_list(tags)


def ensure_singbox_group(data: Dict[str, Any], group_name: str, manual_tags: List[str], interval: str, tolerance: int, idle_timeout: str) -> Tuple[bool, Dict[str, Any]]:
    outbounds = data.setdefault("outbounds", [])
    if not isinstance(outbounds, list):
        outbounds = []
        data["outbounds"] = outbounds

    existing: Optional[Dict[str, Any]] = None
    for outbound in outbounds:
        if isinstance(outbound, dict) and clean_name(outbound.get("tag")) == group_name:
            existing = outbound
            break

    desired_group = {
        "type": "urltest",
        "tag": group_name,
        "outbounds": manual_tags[:],
        "url": "https://www.gstatic.com/generate_204",
        "interval": interval,
        "tolerance": tolerance,
        "idle_timeout": idle_timeout,
        "interrupt_exist_connections": False,
    }

    changed = False
    if existing is None:
        outbounds.insert(0, desired_group)
        existing = desired_group
        changed = True
    else:
        before = json.dumps(existing, sort_keys=True, ensure_ascii=False)
        # Preserve only safe group fields. Do not add `default` for compatibility.
        existing.clear()
        existing.update(desired_group)
        after = json.dumps(existing, sort_keys=True, ensure_ascii=False)
        changed = changed or before != after

    all_tags = {
        clean_name(outbound.get("tag"))
        for outbound in outbounds
        if isinstance(outbound, dict) and clean_name(outbound.get("tag"))
    }
    all_tags.update({"DIRECT"})

    # Add best-link into PROXY selector. Keep as first choice without using selector.default.
    proxy = None
    for outbound in outbounds:
        if isinstance(outbound, dict) and clean_name(outbound.get("tag")) == "PROXY":
            proxy = outbound
            break
    if proxy is None:
        proxy = {"type": "selector", "tag": "PROXY", "outbounds": [group_name, "DIRECT"]}
        outbounds.insert(0, proxy)
        changed = True
    elif str(proxy.get("type") or "").lower() in GROUP_SINGBOX_TYPES:
        choices = proxy.get("outbounds")
        if not isinstance(choices, list):
            choices = []
        choices = [clean_name(x) for x in choices if clean_name(x)]
        if group_name not in choices:
            choices = [group_name] + choices
        else:
            choices = [group_name] + [x for x in choices if x != group_name]
        # Drop missing dependencies except group_name and DIRECT.
        choices = [x for x in choices if x in all_tags or x in {group_name, "DIRECT"}]
        if choices != proxy.get("outbounds"):
            proxy["outbounds"] = choices
            changed = True
        if "default" in proxy:
            proxy.pop("default", None)
            changed = True

    # If route.final is missing/invalid, keep PROXY.
    route = data.get("route")
    if not isinstance(route, dict):
        data["route"] = {"final": "PROXY"}
        changed = True
    else:
        final = clean_name(route.get("final"))
        current_tags = {
            clean_name(outbound.get("tag"))
            for outbound in outbounds
            if isinstance(outbound, dict) and clean_name(outbound.get("tag"))
        }
        if not final or final not in current_tags:
            route["final"] = "PROXY"
            changed = True

    # Remove `default` from every selector for legacy import compatibility.
    for outbound in outbounds:
        if isinstance(outbound, dict) and str(outbound.get("type") or "").lower() == "selector":
            if "default" in outbound:
                outbound.pop("default", None)
                changed = True

    return changed, existing


def process_singbox_dir(directory: str, group_name: str, manual_prefix: str, interval: str, tolerance: int, idle_timeout: str) -> Dict[str, Any]:
    base = Path(directory)
    report: Dict[str, Any] = {
        "group_name": group_name,
        "manual_prefix": manual_prefix,
        "dir": str(base),
        "files": [],
        "total_files": 0,
        "changed_files": 0,
        "total_manual_accounts": 0,
    }
    if not base.exists():
        write_json(SINGBOX_REPORT, report)
        return report

    for path in sorted(base.glob("*.json")):
        if is_summary_json(path):
            continue
        data = read_json(path, {})
        if not isinstance(data, dict):
            continue
        if not isinstance(data.get("outbounds"), list):
            continue
        manual_tags = collect_manual_singbox_tags(data, manual_prefix)
        file_info = {
            "path": str(path),
            "manual_count": len(manual_tags),
            "manual_tags": manual_tags,
            "changed": False,
            "status": "skipped_no_manual_accounts" if not manual_tags else "ok",
        }
        report["total_files"] += 1
        report["total_manual_accounts"] += len(manual_tags)
        if manual_tags:
            changed, group = ensure_singbox_group(data, group_name, manual_tags, interval, tolerance, idle_timeout)
            file_info["changed"] = changed
            file_info["group_type"] = group.get("type")
            file_info["group_outbound_count"] = len(group.get("outbounds", [])) if isinstance(group, dict) else 0
            if changed:
                write_json(path, data)
                report["changed_files"] += 1
        report["files"].append(file_info)

    SINGBOX_REPORT.parent.mkdir(parents=True, exist_ok=True)
    write_json(SINGBOX_REPORT, report)
    return report


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add best-link group for trusted manual input links.")
    parser.add_argument("--group-name", default="best-link", help="Group/outbound tag to create. Default: best-link")
    parser.add_argument("--manual-prefix", default="LINK", help="Manual account prefix. Default: LINK")
    parser.add_argument("--singbox-dir", default="output/SingBox", help="sing-box JSON output directory")
    parser.add_argument("--yaml-files", nargs="*", default=DEFAULT_YAML_FILES, help="OpenClash YAML files to patch")
    parser.add_argument("--interval", default="3m", help="sing-box urltest interval")
    parser.add_argument("--tolerance", type=int, default=80, help="sing-box urltest tolerance")
    parser.add_argument("--idle-timeout", default="2h", help="sing-box urltest idle timeout")
    parser.add_argument("--yaml-only", action="store_true")
    parser.add_argument("--singbox-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.yaml_only and args.singbox_only:
        raise SystemExit("Pilih salah satu saja: --yaml-only atau --singbox-only")

    yaml_report: Optional[Dict[str, Any]] = None
    singbox_report: Optional[Dict[str, Any]] = None

    if not args.singbox_only:
        yaml_report = process_yaml_files(args.yaml_files, args.group_name, args.manual_prefix)
        log(f"OpenClash best-link report: {YAML_REPORT}")
        log(json.dumps({
            "files": yaml_report.get("total_files"),
            "changed_files": yaml_report.get("changed_files"),
            "manual_refs": yaml_report.get("total_manual_accounts"),
        }, ensure_ascii=False))

    if not args.yaml_only:
        singbox_report = process_singbox_dir(args.singbox_dir, args.group_name, args.manual_prefix, args.interval, args.tolerance, args.idle_timeout)
        log(f"sing-box best-link report: {SINGBOX_REPORT}")
        log(json.dumps({
            "files": singbox_report.get("total_files"),
            "changed_files": singbox_report.get("changed_files"),
            "manual_refs": singbox_report.get("total_manual_accounts"),
        }, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

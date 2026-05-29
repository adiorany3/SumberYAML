#!/usr/bin/env python3
"""
Stabilize SumberYAML sing-box JSON profiles.

Purpose:
- reduce "bengong" / stalled internet by forcing PROXY to use AUTO-BEST-PING
- make urltest retest more often and switch active connections when needed
- remove missing outbound references from selector/urltest groups
- keep DNS as Cloudflare 1.1.1.1 only

This is a post-process step. Run it after build_singbox_final.py / merge_links_into_singbox.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REAL_PROXY_TYPES = {
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
    "hysteria",
    "hysteria2",
    "tuic",
    "anytls",
    "naive",
    "socks",
    "http",
    "ssh",
    "wireguard",
}

SPECIAL_TYPES = {
    "selector",
    "urltest",
    "direct",
    "block",
    "dns",
}

SUMMARY_NAME = "summary_stabilize_singbox_json.json"


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"SKIP {path}: bukan JSON valid: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"SKIP {path}: root bukan object")
        return None
    return data


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def is_config_json(path: Path) -> bool:
    name = path.name.lower()
    if not name.endswith(".json"):
        return False
    if name.startswith("summary"):
        return False
    if name in {SUMMARY_NAME.lower()}:
        return False
    return True


def get_outbounds(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        return []
    return [item for item in outbounds if isinstance(item, dict)]


def outbound_tags(outbounds: Iterable[Dict[str, Any]]) -> Set[str]:
    tags: Set[str] = set()
    for outbound in outbounds:
        tag = outbound.get("tag")
        if isinstance(tag, str) and tag.strip():
            tags.add(tag.strip())
    return tags


def real_proxy_tags(outbounds: Iterable[Dict[str, Any]]) -> List[str]:
    tags: List[str] = []
    for outbound in outbounds:
        tag = str(outbound.get("tag") or "").strip()
        typ = str(outbound.get("type") or "").strip().lower()
        if tag and typ in REAL_PROXY_TYPES:
            tags.append(tag)
    return tags


def unique_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def ensure_direct(outbounds: List[Dict[str, Any]]) -> bool:
    for outbound in outbounds:
        if outbound.get("tag") == "DIRECT":
            if outbound.get("type") != "direct":
                outbound["type"] = "direct"
            return False
    outbounds.append({"type": "direct", "tag": "DIRECT"})
    return True


def ensure_dns_1111(data: Dict[str, Any]) -> bool:
    dns = data.get("dns")
    changed = False
    if not isinstance(dns, dict):
        data["dns"] = {
            "servers": [
                {
                    "tag": "cloudflare",
                    "address": "1.1.1.1",
                }
            ],
            "final": "cloudflare",
        }
        return True

    servers = dns.get("servers")
    if not isinstance(servers, list):
        servers = []

    # Preserve legacy/new-dns style by looking at the first server style.
    use_new_dns = any(isinstance(item, dict) and "type" in item for item in servers)
    if use_new_dns:
        new_servers = [{"type": "udp", "tag": "cloudflare", "server": "1.1.1.1"}]
    else:
        new_servers = [{"tag": "cloudflare", "address": "1.1.1.1"}]

    if servers != new_servers:
        dns["servers"] = new_servers
        changed = True
    if dns.get("final") != "cloudflare":
        dns["final"] = "cloudflare"
        changed = True
    return changed


def apply_dial_stability(
    outbounds: List[Dict[str, Any]],
    connect_timeout: str,
    tcp_fast_open: Optional[bool],
) -> int:
    changed = 0
    for outbound in outbounds:
        typ = str(outbound.get("type") or "").lower()
        if typ not in REAL_PROXY_TYPES:
            continue
        if connect_timeout and outbound.get("connect_timeout") != connect_timeout:
            outbound["connect_timeout"] = connect_timeout
            changed += 1
        if tcp_fast_open is not None and outbound.get("tcp_fast_open") != tcp_fast_open:
            outbound["tcp_fast_open"] = tcp_fast_open
            changed += 1
    return changed


def ensure_auto_best_ping(
    outbounds: List[Dict[str, Any]],
    proxies: List[str],
    test_url: str,
    interval: str,
    tolerance: int,
    idle_timeout: str,
    interrupt: bool,
) -> Tuple[bool, str]:
    """Create/update AUTO-BEST-PING urltest and return tag."""
    auto_tag = "AUTO-BEST-PING"
    changed = False
    auto = None
    for outbound in outbounds:
        if outbound.get("tag") == auto_tag:
            auto = outbound
            break

    if auto is None:
        auto = {"type": "urltest", "tag": auto_tag}
        # Put after DIRECT if DIRECT is first, otherwise at the beginning.
        outbounds.insert(0, auto)
        changed = True

    desired = {
        "type": "urltest",
        "tag": auto_tag,
        "outbounds": proxies,
        "url": test_url,
        "interval": interval,
        "tolerance": tolerance,
        "idle_timeout": idle_timeout,
        "interrupt_exist_connections": interrupt,
    }
    for key, value in desired.items():
        if auto.get(key) != value:
            auto[key] = value
            changed = True
    return changed, auto_tag


def clean_group_refs(outbound: Dict[str, Any], existing_tags: Set[str]) -> bool:
    typ = str(outbound.get("type") or "").lower()
    if typ not in {"selector", "urltest"}:
        return False
    items = outbound.get("outbounds")
    if not isinstance(items, list):
        outbound["outbounds"] = []
        return True
    cleaned = unique_order(str(item) for item in items if str(item) in existing_tags)
    if cleaned != items:
        outbound["outbounds"] = cleaned
        return True
    return False


def stabilize_groups(
    outbounds: List[Dict[str, Any]],
    test_url: str,
    interval: str,
    tolerance: int,
    idle_timeout: str,
    interrupt: bool,
) -> int:
    changed = 0
    ensure_direct(outbounds)
    proxies = real_proxy_tags(outbounds)
    if not proxies:
        return changed

    created_or_changed, auto_tag = ensure_auto_best_ping(
        outbounds,
        proxies,
        test_url,
        interval,
        tolerance,
        idle_timeout,
        interrupt,
    )
    if created_or_changed:
        changed += 1

    existing = outbound_tags(outbounds)

    # Clean missing refs first.
    for outbound in outbounds:
        if clean_group_refs(outbound, existing):
            changed += 1

    # Update all urltest groups to behave consistently, but preserve their members when valid.
    for outbound in outbounds:
        if str(outbound.get("type") or "").lower() != "urltest":
            continue
        members = outbound.get("outbounds")
        if not isinstance(members, list) or not members:
            members = proxies
        desired_members = unique_order(str(item) for item in members if str(item) in existing and str(item) not in {"DIRECT", auto_tag})
        if not desired_members:
            desired_members = proxies
        desired = {
            "url": test_url,
            "interval": interval,
            "tolerance": tolerance,
            "idle_timeout": idle_timeout,
            "interrupt_exist_connections": interrupt,
            "outbounds": desired_members,
        }
        for key, value in desired.items():
            if outbound.get(key) != value:
                outbound[key] = value
                changed += 1

    # Force PROXY selector to prefer AUTO-BEST-PING but keep manual node choices.
    proxy_selector = None
    for outbound in outbounds:
        if outbound.get("tag") == "PROXY" and str(outbound.get("type") or "").lower() == "selector":
            proxy_selector = outbound
            break
    if proxy_selector is None:
        proxy_selector = {"type": "selector", "tag": "PROXY"}
        outbounds.insert(0, proxy_selector)
        changed += 1

    desired_proxy_outbounds = unique_order([auto_tag, "DIRECT"] + proxies)
    if proxy_selector.get("outbounds") != desired_proxy_outbounds:
        proxy_selector["outbounds"] = desired_proxy_outbounds
        changed += 1
    if proxy_selector.get("default") != auto_tag:
        proxy_selector["default"] = auto_tag
        changed += 1
    if proxy_selector.get("interrupt_exist_connections") != interrupt:
        proxy_selector["interrupt_exist_connections"] = interrupt
        changed += 1

    # Other selector groups: remove missing refs and enable connection interruption.
    existing = outbound_tags(outbounds)
    for outbound in outbounds:
        if str(outbound.get("type") or "").lower() != "selector":
            continue
        if clean_group_refs(outbound, existing):
            changed += 1
        if outbound.get("tag") != "PROXY" and outbound.get("interrupt_exist_connections") != interrupt:
            outbound["interrupt_exist_connections"] = interrupt
            changed += 1
        members = outbound.get("outbounds")
        if isinstance(members, list) and not members:
            outbound["outbounds"] = desired_proxy_outbounds
            outbound["default"] = auto_tag
            changed += 1

    return changed


def ensure_route_final(data: Dict[str, Any]) -> bool:
    route = data.get("route")
    if not isinstance(route, dict):
        data["route"] = {"final": "PROXY"}
        return True
    if route.get("final") != "PROXY":
        route["final"] = "PROXY"
        return True
    return False


def stabilize_file(path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    data = load_json(path)
    if data is None:
        return {"file": str(path), "ok": False, "changed": False, "reason": "not_config_json"}

    outbounds = get_outbounds(data)
    if not outbounds:
        return {"file": str(path), "ok": False, "changed": False, "reason": "no_outbounds"}

    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    dns_changed = ensure_dns_1111(data)
    dial_changes = apply_dial_stability(outbounds, args.connect_timeout, args.tcp_fast_open)
    group_changes = stabilize_groups(
        outbounds,
        args.test_url,
        args.interval,
        args.tolerance,
        args.idle_timeout,
        args.interrupt,
    )
    route_changed = ensure_route_final(data)

    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    changed = before != after
    if changed:
        save_json(path, data)

    real_count = len(real_proxy_tags(outbounds))
    return {
        "file": str(path),
        "ok": True,
        "changed": changed,
        "real_proxy_count": real_count,
        "dns_changed": dns_changed,
        "dial_changes": dial_changes,
        "group_changes": group_changes,
        "route_changed": route_changed,
        "test_url": args.test_url,
        "interval": args.interval,
        "tolerance": args.tolerance,
        "idle_timeout": args.idle_timeout,
        "connect_timeout": args.connect_timeout,
        "interrupt_exist_connections": args.interrupt,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stabilize sing-box JSON profiles to reduce stalled connections.")
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON files")
    parser.add_argument("--test-url", default="https://www.gstatic.com/generate_204")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--tolerance", type=int, default=30)
    parser.add_argument("--idle-timeout", default="5m")
    parser.add_argument("--connect-timeout", default="8s")
    parser.add_argument("--interrupt", action="store_true", default=True)
    parser.add_argument("--no-interrupt", dest="interrupt", action="store_false")
    parser.add_argument("--tcp-fast-open", dest="tcp_fast_open", action="store_true", default=None)
    parser.add_argument("--disable-tcp-fast-open", dest="tcp_fast_open", action="store_false")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in base.glob("*.json") if is_config_json(path))
    if not files:
        print(f"Tidak ada JSON sing-box di {base}")
        return 0

    reports = [stabilize_file(path, args) for path in files]
    summary = {
        "ok": True,
        "processed": len(reports),
        "changed": sum(1 for item in reports if item.get("changed")),
        "files": reports,
    }
    summary_path = base / SUMMARY_NAME
    save_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

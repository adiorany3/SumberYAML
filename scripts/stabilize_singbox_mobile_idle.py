#!/usr/bin/env python3
"""
Mobile idle/reconnect stabilizer for SumberYAML sing-box JSON profiles.

Why this exists:
- Some mobile clients connect successfully at first, but after the phone/network is idle
  for a while, the selected urltest outbound can become stale or hard to reconnect.
- Previous aggressive settings such as idle_timeout=5m and interrupt_exist_connections=true
  can make switching too frequent and can break existing mobile sessions.

What it does:
- Keeps URLTest groups alive longer: idle_timeout=2h by default.
- Uses a calmer URLTest interval/tolerance: 3m / 80ms by default.
- Disables interrupt_exist_connections on selector/urltest groups by default.
- Uses a more patient connect_timeout=15s for real proxy outbounds.
- Removes tcp_fast_open by default, because some mobile networks/ISPs handle it poorly.
- Keeps DNS as 1.1.1.1 only, preserving legacy/new DNS style already used by the file.
- Cleans missing selector/urltest references.

Run after the final sing-box JSON is built and after input/links.txt is merged.
"""

from __future__ import annotations

import argparse
import json
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

GROUP_TYPES = {"selector", "urltest"}
SUMMARY_NAME = "summary_mobile_idle_reconnect_fix.json"


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"SKIP {path}: invalid JSON: {exc}")
        return None
    return data if isinstance(data, dict) else None


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_config_json(path: Path) -> bool:
    name = path.name.lower()
    if not name.endswith(".json"):
        return False
    if name.startswith("summary"):
        return False
    return True


def get_outbounds(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        return []
    return [item for item in outbounds if isinstance(item, dict)]


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


def outbound_tags(outbounds: Iterable[Dict[str, Any]]) -> Set[str]:
    tags: Set[str] = set()
    for outbound in outbounds:
        tag = str(outbound.get("tag") or "").strip()
        if tag:
            tags.add(tag)
    return tags


def real_proxy_tags(outbounds: Iterable[Dict[str, Any]]) -> List[str]:
    result: List[str] = []
    for outbound in outbounds:
        tag = str(outbound.get("tag") or "").strip()
        typ = str(outbound.get("type") or "").strip().lower()
        if tag and typ in REAL_PROXY_TYPES:
            result.append(tag)
    return result


def ensure_direct(outbounds: List[Dict[str, Any]]) -> bool:
    for outbound in outbounds:
        if outbound.get("tag") == "DIRECT":
            changed = False
            if outbound.get("type") != "direct":
                outbound["type"] = "direct"
                changed = True
            return changed
    outbounds.append({"type": "direct", "tag": "DIRECT"})
    return True


def ensure_dns_1111(data: Dict[str, Any]) -> bool:
    dns = data.get("dns")
    changed = False
    if not isinstance(dns, dict):
        data["dns"] = {
            "servers": [{"tag": "cloudflare", "address": "1.1.1.1"}],
            "final": "cloudflare",
        }
        return True

    servers = dns.get("servers")
    if not isinstance(servers, list):
        servers = []

    # Preserve current DNS schema style. Older SFI clients need legacy address style,
    # newer profiles may intentionally use type/server style.
    use_new_dns = any(isinstance(item, dict) and "type" in item for item in servers)
    desired_servers = (
        [{"type": "udp", "tag": "cloudflare", "server": "1.1.1.1"}]
        if use_new_dns
        else [{"tag": "cloudflare", "address": "1.1.1.1"}]
    )

    if dns.get("servers") != desired_servers:
        dns["servers"] = desired_servers
        changed = True
    if dns.get("final") != "cloudflare":
        dns["final"] = "cloudflare"
        changed = True
    return changed


def apply_mobile_dial_defaults(outbounds: List[Dict[str, Any]], connect_timeout: str, remove_tcp_fast_open: bool) -> int:
    changes = 0
    for outbound in outbounds:
        typ = str(outbound.get("type") or "").lower()
        if typ not in REAL_PROXY_TYPES:
            continue
        if connect_timeout and outbound.get("connect_timeout") != connect_timeout:
            outbound["connect_timeout"] = connect_timeout
            changes += 1
        if remove_tcp_fast_open and "tcp_fast_open" in outbound:
            outbound.pop("tcp_fast_open", None)
            changes += 1
    return changes


def clean_group_refs(outbound: Dict[str, Any], existing_tags: Set[str], fallback_members: List[str]) -> bool:
    typ = str(outbound.get("type") or "").lower()
    if typ not in GROUP_TYPES:
        return False
    members = outbound.get("outbounds")
    if not isinstance(members, list):
        outbound["outbounds"] = fallback_members
        return True
    cleaned = unique_order(item for item in members if str(item) in existing_tags)
    if not cleaned:
        cleaned = fallback_members
    if cleaned != members:
        outbound["outbounds"] = cleaned
        return True
    return False


def ensure_auto_best_ping(
    outbounds: List[Dict[str, Any]],
    proxy_tags: List[str],
    test_url: str,
    interval: str,
    tolerance: int,
    idle_timeout: str,
    interrupt: bool,
) -> int:
    changes = 0
    auto = None
    for outbound in outbounds:
        if outbound.get("tag") == "AUTO-BEST-PING":
            auto = outbound
            break

    if auto is None:
        auto = {"type": "urltest", "tag": "AUTO-BEST-PING"}
        outbounds.insert(0, auto)
        changes += 1

    desired = {
        "type": "urltest",
        "tag": "AUTO-BEST-PING",
        "outbounds": proxy_tags,
        "url": test_url,
        "interval": interval,
        "tolerance": tolerance,
        "idle_timeout": idle_timeout,
        "interrupt_exist_connections": interrupt,
    }
    for key, value in desired.items():
        if auto.get(key) != value:
            auto[key] = value
            changes += 1
    return changes


def apply_group_mobile_defaults(
    outbounds: List[Dict[str, Any]],
    test_url: str,
    interval: str,
    tolerance: int,
    idle_timeout: str,
    interrupt: bool,
) -> int:
    changes = 0
    if ensure_direct(outbounds):
        changes += 1

    proxies = real_proxy_tags(outbounds)
    if not proxies:
        return changes

    changes += ensure_auto_best_ping(outbounds, proxies, test_url, interval, tolerance, idle_timeout, interrupt)
    existing = outbound_tags(outbounds)
    fallback = proxies

    for outbound in outbounds:
        typ = str(outbound.get("type") or "").lower()
        if typ not in GROUP_TYPES:
            continue

        if clean_group_refs(outbound, existing, fallback):
            changes += 1

        if typ == "urltest":
            desired = {
                "url": test_url,
                "interval": interval,
                "tolerance": tolerance,
                "idle_timeout": idle_timeout,
                "interrupt_exist_connections": interrupt,
            }
            for key, value in desired.items():
                if outbound.get(key) != value:
                    outbound[key] = value
                    changes += 1

        if typ == "selector":
            if outbound.get("interrupt_exist_connections") != interrupt:
                outbound["interrupt_exist_connections"] = interrupt
                changes += 1

    # Make PROXY choose AUTO-BEST-PING, but keep DIRECT and all manual choices available.
    proxy_selector = None
    for outbound in outbounds:
        if outbound.get("tag") == "PROXY" and str(outbound.get("type") or "").lower() == "selector":
            proxy_selector = outbound
            break
    if proxy_selector is None:
        proxy_selector = {"type": "selector", "tag": "PROXY"}
        outbounds.insert(0, proxy_selector)
        changes += 1

    desired_proxy_members = unique_order(["AUTO-BEST-PING", "DIRECT"] + proxies)
    if proxy_selector.get("outbounds") != desired_proxy_members:
        proxy_selector["outbounds"] = desired_proxy_members
        changes += 1
    if proxy_selector.get("default") != "AUTO-BEST-PING":
        proxy_selector["default"] = "AUTO-BEST-PING"
        changes += 1
    if proxy_selector.get("interrupt_exist_connections") != interrupt:
        proxy_selector["interrupt_exist_connections"] = interrupt
        changes += 1

    return changes


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
        return {"file": str(path), "ok": False, "changed": False, "reason": "invalid_json"}

    outbounds = get_outbounds(data)
    if not outbounds:
        return {"file": str(path), "ok": False, "changed": False, "reason": "no_outbounds"}

    before = json.dumps(data, ensure_ascii=False, sort_keys=True)

    dns_changed = ensure_dns_1111(data)
    dial_changes = apply_mobile_dial_defaults(outbounds, args.connect_timeout, args.remove_tcp_fast_open)
    group_changes = apply_group_mobile_defaults(
        outbounds=outbounds,
        test_url=args.test_url,
        interval=args.interval,
        tolerance=args.tolerance,
        idle_timeout=args.idle_timeout,
        interrupt=args.interrupt,
    )
    route_changed = ensure_route_final(data)

    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    changed = before != after
    if changed:
        save_json(path, data)

    return {
        "file": str(path),
        "ok": True,
        "changed": changed,
        "real_proxy_count": len(real_proxy_tags(outbounds)),
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
        "remove_tcp_fast_open": args.remove_tcp_fast_open,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix mobile idle/reconnect behavior in sing-box JSON profiles.")
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON files")
    parser.add_argument("--test-url", default="https://www.gstatic.com/generate_204")
    parser.add_argument("--interval", default="3m", help="URLTest interval. Conservative default: 3m")
    parser.add_argument("--tolerance", type=int, default=80, help="URLTest tolerance in ms. Conservative default: 80")
    parser.add_argument("--idle-timeout", default="2h", help="URLTest idle timeout. Conservative default: 2h")
    parser.add_argument("--connect-timeout", default="15s", help="Proxy outbound connect timeout. Conservative default: 15s")
    parser.add_argument("--interrupt", action="store_true", default=False, help="Interrupt existing connections when group selection changes")
    parser.add_argument("--no-interrupt", dest="interrupt", action="store_false")
    parser.add_argument("--keep-tcp-fast-open", dest="remove_tcp_fast_open", action="store_false")
    parser.add_argument("--remove-tcp-fast-open", dest="remove_tcp_fast_open", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in base.glob("*.json") if is_config_json(path))
    reports = [stabilize_file(path, args) for path in files]

    summary = {
        "ok": True,
        "mode": "mobile_idle_reconnect_fix",
        "processed": len(reports),
        "changed": sum(1 for item in reports if item.get("changed")),
        "settings": {
            "test_url": args.test_url,
            "interval": args.interval,
            "tolerance": args.tolerance,
            "idle_timeout": args.idle_timeout,
            "connect_timeout": args.connect_timeout,
            "interrupt_exist_connections": args.interrupt,
            "remove_tcp_fast_open": args.remove_tcp_fast_open,
            "dns": "1.1.1.1 only",
        },
        "files": reports,
    }
    summary_path = base / SUMMARY_NAME
    save_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

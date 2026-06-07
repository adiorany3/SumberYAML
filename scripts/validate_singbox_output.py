#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, pathlib, sys

LEGACY_INBOUND_FIELDS = {"sniff", "sniff_override_destination", "sniff_timeout"}
LEGACY_DNS_KEYS = {"address", "address_resolver", "address_strategy", "detour"}
REMOVED_ROUTE_KEYS = {"geoip", "geosite"}
SUPPORTED_PROXY_TYPES = {"vmess", "vless", "trojan", "selector", "urltest", "direct", "block"}


def validate(path: pathlib.Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"invalid JSON {path}: {e}"]

    dns = data.get("dns") or {}
    servers = dns.get("servers") or []
    if not isinstance(servers, list) or not servers:
        errors.append("dns.servers is empty or missing")
    for srv in servers:
        if not isinstance(srv, dict):
            errors.append("dns server item is not object")
            continue
        if LEGACY_DNS_KEYS & set(srv):
            errors.append(f"legacy DNS server keys found in {srv.get('tag', '<untagged>')}: {sorted(LEGACY_DNS_KEYS & set(srv))}")
        if not srv.get("type"):
            errors.append(f"DNS server {srv.get('tag', '<untagged>')} missing new-format type")
        if srv.get("type") in {"tls", "https", "quic", "h3", "tcp", "udp"} and not srv.get("server"):
            errors.append(f"DNS server {srv.get('tag', '<untagged>')} missing server")

    for ib in data.get("inbounds", []) or []:
        if not isinstance(ib, dict):
            errors.append("inbound item is not object")
            continue
        legacy = LEGACY_INBOUND_FIELDS & set(ib)
        if legacy:
            errors.append(f"legacy inbound fields found in {ib.get('tag', '<untagged>')}: {sorted(legacy)}")

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        errors.append("outbounds is empty or missing")
        return errors
    tags = []
    for ob in outbounds:
        if not isinstance(ob, dict):
            errors.append("outbound item is not object")
            continue
        tag = ob.get("tag")
        typ = ob.get("type")
        if not tag:
            errors.append("outbound without tag")
        if not typ:
            errors.append(f"outbound {tag!r} without type")
        if typ in {"ss", "ssr", "shadowsocks"}:
            errors.append(f"unsupported outbound type: {typ}")
        if typ and typ not in SUPPORTED_PROXY_TYPES:
            errors.append(f"unexpected outbound type for this generator: {typ}")
        tags.append(tag)
    if len(tags) != len(set(tags)):
        errors.append("duplicate outbound tags")
    tagset = set(tags)
    for ob in outbounds:
        if ob.get("type") in {"selector", "urltest"}:
            members = ob.get("outbounds")
            if not isinstance(members, list) or not members:
                errors.append(f"group {ob.get('tag')} has empty outbounds")
                continue
            for m in members:
                if m not in tagset:
                    errors.append(f"group {ob.get('tag')} references missing {m}")

    route = data.get("route") or {}
    if REMOVED_ROUTE_KEYS & set(route):
        errors.append(f"removed route keys found: {sorted(REMOVED_ROUTE_KEYS & set(route))}")
    for rule in route.get("rules", []) or []:
        if not isinstance(rule, dict):
            errors.append("route rule item is not object")
            continue
        if "geosite" in rule or "geoip" in rule:
            errors.append("route rule uses deprecated/removed geosite/geoip")
        action = rule.get("action", "route")
        if action == "route":
            target = rule.get("outbound")
            if not target:
                errors.append("route rule missing outbound")
            elif target not in tagset:
                errors.append(f"route references missing outbound {target}")
    for required in ["select", "sb-auto", "direct", "block"]:
        if required not in tagset:
            errors.append(f"required outbound missing: {required}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*", default=["output/SingBox/sing-box.json"])
    ns = ap.parse_args()
    root = pathlib.Path(ns.root)
    all_errors = []
    for p in ns.paths:
        errs = validate(root / p)
        if errs:
            all_errors.extend([f"{p}: {e}" for e in errs])
        else:
            print("SING-BOX OK:", p)
    if all_errors:
        for e in all_errors:
            print("ERROR:", e, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

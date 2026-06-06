#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import yaml

SPECIAL = {"DIRECT", "REJECT"}
BLOCKED_TYPES = {"ss", "ssr"}
AUTO_TYPES = {"url-test", "fallback"}
BLOCKED_GROUP_TYPES = {"load-balance"}
RISKY_GROUP_KEYS = {"timeout", "lazy", "strategy", "disable-udp", "interface-name", "routing-mark"}


def target(rule: str) -> Optional[str]:
    parts = [p.strip() for p in str(rule).split(",")]
    if not parts:
        return None
    if parts[0].upper() == "MATCH" and len(parts) >= 2:
        return parts[1]
    if len(parts) >= 3:
        return parts[2]
    return None


def validate(path: Path) -> List[str]:
    if not path.exists():
        return []
    errors: List[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception as exc:
        return [f"{path}: YAML parse failed: {exc}"]
    if not isinstance(data, dict):
        return [f"{path}: YAML root is not a map"]

    proxies = data.get("proxies") or []
    groups = data.get("proxy-groups") or []
    rules = data.get("rules") or []
    pnames = {str(p.get("name")) for p in proxies if isinstance(p, dict) and p.get("name")}
    gnames = {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}
    allowed = pnames | gnames | SPECIAL

    if not pnames:
        errors.append(f"{path}: no proxy nodes found")
    if not gnames:
        errors.append(f"{path}: no proxy-groups found")

    for p in proxies:
        if not isinstance(p, dict):
            errors.append(f"{path}: non-map proxy entry")
            continue
        ptype = str(p.get("type") or "").lower()
        if ptype in BLOCKED_TYPES:
            errors.append(f"{path}: blocked proxy type still exists: {p.get('name')} ({ptype})")
        if not p.get("server") or not p.get("port"):
            errors.append(f"{path}: proxy missing server/port: {p.get('name')}")

    for g in groups:
        if not isinstance(g, dict):
            errors.append(f"{path}: non-map proxy group entry")
            continue
        name = str(g.get("name") or "")
        gtype = str(g.get("type") or "")
        refs = [str(x) for x in (g.get("proxies") or [])]
        if gtype in BLOCKED_GROUP_TYPES:
            errors.append(f"{path}: blocked group type {gtype}: {name}")
        if not refs:
            errors.append(f"{path}: empty proxy group: {name}")
        for key in RISKY_GROUP_KEYS:
            if key in g:
                errors.append(f"{path}: risky group key {key}: {name}")
        for ref in refs:
            if ref == name:
                errors.append(f"{path}: group self-reference: {name}")
            if ref not in allowed:
                errors.append(f"{path}: invalid group reference: {name} -> {ref}")
            if gtype in AUTO_TYPES and ref in SPECIAL:
                errors.append(f"{path}: {ref} appears in automatic group: {name}")

    for rule in rules:
        text = str(rule)
        tgt = target(text)
        if tgt and tgt.upper() in {"DIRECT", "REJECT"}:
            errors.append(f"{path}: DIRECT/REJECT used as rule target: {text}")
        if tgt and tgt not in allowed:
            errors.append(f"{path}: rule target not found: {text}")
    return errors


def main() -> int:
    paths = [Path(arg) for arg in sys.argv[1:]] or [
        Path("output/lengkap.yaml"),
        Path("output/lengkap_alive.yaml"),
        Path("output/strict_alive.yaml"),
        Path("output/lite.yaml"),
        Path("output/fast.yaml"),
        Path("output/manual_only.yaml"),
    ]
    all_errors: List[str] = []
    for path in paths:
        all_errors.extend(validate(path))
    if all_errors:
        for err in all_errors:
            print(err)
        return 1
    print("OpenClash strict-safe validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

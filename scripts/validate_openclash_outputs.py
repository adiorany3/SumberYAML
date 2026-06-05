#!/usr/bin/env python3
"""Strict but OpenClash-safe YAML validator for SumberYAML outputs."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

SPECIAL_REFS = {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
BLOCKED_TYPES = {"ss", "ssr"}
RISKY_ROOT_KEYS = {"unified-delay", "tcp-concurrent"}
RISKY_GROUP_KEYS = {"lazy", "timeout"}


def read_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML root is not a mapping")
    return data


def validate_file(path: Path) -> List[str]:
    errors: List[str] = []
    if not path.exists():
        return [f"missing file: {path}"]
    try:
        data = read_yaml(path)
    except Exception as exc:
        return [f"YAML parse failed: {path}: {exc}"]

    for key in RISKY_ROOT_KEYS:
        if key in data:
            errors.append(f"{path}: risky root key still exists: {key}")

    proxies = data.get("proxies") or []
    groups = data.get("proxy-groups") or []
    if not isinstance(proxies, list) or not proxies:
        errors.append(f"{path}: proxies is empty/missing")
        proxies = []
    if not isinstance(groups, list) or not groups:
        errors.append(f"{path}: proxy-groups is empty/missing")
        groups = []

    proxy_names: List[str] = []
    for idx, proxy in enumerate(proxies):
        if not isinstance(proxy, dict):
            errors.append(f"{path}: proxy index {idx} is not a mapping")
            continue
        name = str(proxy.get("name") or "").strip()
        ptype = str(proxy.get("type") or "").strip().lower()
        if not name:
            errors.append(f"{path}: proxy index {idx} has no name")
        else:
            proxy_names.append(name)
        if ptype in BLOCKED_TYPES:
            errors.append(f"{path}: blocked proxy type exists: {name or idx} type={ptype}")
    duplicates = sorted({name for name in proxy_names if proxy_names.count(name) > 1})
    for name in duplicates:
        errors.append(f"{path}: duplicate proxy name: {name}")

    proxy_set: Set[str] = set(proxy_names)
    group_names = {str(g.get("name") or "").strip() for g in groups if isinstance(g, dict) and str(g.get("name") or "").strip()}
    allowed = proxy_set | group_names | SPECIAL_REFS
    for idx, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(f"{path}: proxy-group index {idx} is not a mapping")
            continue
        gname = str(group.get("name") or "").strip()
        if not gname:
            errors.append(f"{path}: proxy-group index {idx} has no name")
        for key in RISKY_GROUP_KEYS:
            if key in group:
                errors.append(f"{path}: risky group key still exists: {gname}.{key}")
        refs = group.get("proxies") or []
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}: proxy-group has no proxies: {gname or idx}")
            continue
        for ref in refs:
            value = str(ref).strip()
            if value == gname:
                errors.append(f"{path}: proxy-group self reference: {gname}")
            if value not in allowed:
                errors.append(f"{path}: unknown group reference: {gname} -> {value}")
    return errors


def main(argv: List[str]) -> int:
    paths = [Path(arg) for arg in argv[1:]]
    if not paths:
        paths = [
            Path("output/lengkap.yaml"),
            Path("output/lengkap_alive.yaml"),
            Path("output/strict_alive.yaml"),
            Path("output/lite.yaml"),
            Path("output/fast.yaml"),
            Path("output/manual_only.yaml"),
        ]
    errors: List[str] = []
    for path in paths:
        if not path.exists():
            continue
        errors.extend(validate_file(path))
    if errors:
        print("OpenClash YAML validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("OpenClash YAML validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

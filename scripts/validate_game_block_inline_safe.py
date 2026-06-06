#!/usr/bin/env python3
"""Validate OpenClash-safe inline game blocking rules."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

REQUIRED_GAME_RULES = [
    "DOMAIN-SUFFIX,callofwar.com,BLOCK",
    "DOMAIN-SUFFIX,bytro.com,BLOCK",
    "DOMAIN-SUFFIX,supremacy1914.com,BLOCK",
    "DOMAIN-SUFFIX,conflictofnations.com,BLOCK",
    "DOMAIN-SUFFIX,poki.com,BLOCK",
    "DOMAIN-SUFFIX,crazygames.com,BLOCK",
    "DOMAIN-SUFFIX,y8.com,BLOCK",
    "DOMAIN-SUFFIX,krunker.io,BLOCK",
    "DOMAIN-SUFFIX,roblox.com,BLOCK",
]

FORBIDDEN_PATTERNS = [
    "RULE-SET,GAME-BLOCK",
    "GAME-BLOCK-DOMAIN",
    "GAME-BLOCK-CLASSICAL",
    "MATCH,REJECT",
    "FINAL,REJECT",
]


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def validate_file(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = load_yaml(path)
    errors: List[str] = []

    for pattern in FORBIDDEN_PATTERNS:
        if pattern in text:
            errors.append(f"forbidden pattern found: {pattern}")

    if not isinstance(data, dict):
        errors.append("top-level YAML is not a mapping")
        return {"file": str(path), "ok": False, "errors": errors}

    providers = data.get("rule-providers")
    if isinstance(providers, dict):
        for key in providers:
            if str(key).upper().startswith("GAME-BLOCK"):
                errors.append(f"game rule-provider still exists: {key}")

    groups = as_list(data.get("proxy-groups"))
    block = None
    for group in groups:
        if isinstance(group, dict) and group.get("name") == "BLOCK":
            block = group
            break
    if not block:
        errors.append("missing BLOCK selector group")
    else:
        if block.get("type") != "select":
            errors.append("BLOCK group must be type select")
        proxies = as_list(block.get("proxies"))
        if "REJECT" not in proxies:
            errors.append("BLOCK group must include REJECT as selector option")

    rules = [r.strip() for r in as_list(data.get("rules")) if isinstance(r, str) and r.strip()]
    for required in REQUIRED_GAME_RULES:
        if required not in rules:
            errors.append(f"missing required game block rule: {required}")

    # REJECT may appear inside BLOCK selector but must not be a direct rule target.
    for rule in rules:
        parts = [p.strip() for p in rule.split(",")]
        if len(parts) >= 2 and parts[-1] == "REJECT":
            errors.append(f"rule targets REJECT directly: {rule}")
        if len(parts) >= 2 and parts[-1] == "DIRECT" and parts[0].upper() in {"MATCH", "FINAL", "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "GEOIP"}:
            errors.append(f"rule targets DIRECT directly: {rule}")

    return {"file": str(path), "ok": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    paths = [Path(p) for p in args.files]
    if not paths:
        output = root / "output"
        paths = [p for p in [
            output / "lengkap.yaml",
            output / "lengkap_alive.yaml",
            output / "strict_alive.yaml",
            output / "lite.yaml",
            output / "fast.yaml",
            output / "manual_only.yaml",
        ] if p.exists()]

    results = [validate_file(p) for p in paths if p.exists()]
    ok = all(r["ok"] for r in results)

    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    out = validation_dir / "game_block_inline_safe_validation.json"
    out.write_text(json.dumps({"ok": ok, "files": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": ok, "files": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

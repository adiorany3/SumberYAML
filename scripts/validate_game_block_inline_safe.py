#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    import yaml
except Exception as exc:
    print(f"ERROR: PyYAML required: {exc}", file=sys.stderr)
    sys.exit(2)

REQUIRED_GAME_RULES = [
    "DOMAIN-SUFFIX,steampowered.com,BLOCK",
    "DOMAIN-SUFFIX,epicgames.com,BLOCK",
    "DOMAIN-SUFFIX,riotgames.com,BLOCK",
    "DOMAIN-SUFFIX,roblox.com,BLOCK",
    "DOMAIN-SUFFIX,pubgmobile.com,BLOCK",
    "DOMAIN-SUFFIX,mobilelegends.com,BLOCK",
    "DOMAIN-SUFFIX,freefiremobile.com,BLOCK",
    "DOMAIN-SUFFIX,hoyoverse.com,BLOCK",
    "DOMAIN-SUFFIX,poki.com,BLOCK",
]


def validate(path: Path) -> Dict[str, Any]:
    report: Dict[str, Any] = {"file": str(path), "ok": True, "errors": [], "warnings": []}
    if not path.exists():
        report["warnings"].append("missing file")
        return report
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        report["errors"].append(f"YAML parse error: {exc}")
        report["ok"] = False
        return report
    if not isinstance(data, dict):
        report["errors"].append("root is not mapping")
        report["ok"] = False
        return report

    groups = {str(g.get("name")): g for g in (data.get("proxy-groups") or []) if isinstance(g, dict)}
    if "BLOCK" not in groups:
        report["errors"].append("BLOCK selector group missing")
    else:
        block = groups["BLOCK"]
        if block.get("type") != "select":
            report["errors"].append("BLOCK group must be type select")
        members = [str(x) for x in (block.get("proxies") or [])]
        if "REJECT" not in members:
            report["errors"].append("BLOCK group must contain REJECT as selector option")

    providers = data.get("rule-providers")
    if isinstance(providers, dict):
        for key in providers:
            if str(key).upper().startswith("GAME-BLOCK"):
                report["errors"].append(f"GAME-BLOCK rule-provider still present: {key}")

    rules = [str(x).strip() for x in (data.get("rules") or [])]
    for rule in REQUIRED_GAME_RULES:
        if rule not in rules:
            report["errors"].append(f"required inline game block rule missing: {rule}")
    for rule in rules:
        upper = rule.upper()
        if upper.startswith("RULE-SET,GAME-BLOCK"):
            report["errors"].append(f"unsupported GAME-BLOCK RULE-SET remains: {rule}")
        if rule.endswith(",DIRECT") or rule.endswith(",REJECT"):
            report["errors"].append(f"DIRECT/REJECT used as direct rule target: {rule}")
    report["ok"] = not report["errors"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    files = args.files or [
        "output/fast.yaml",
        "output/lite.yaml",
        "output/lengkap.yaml",
        "output/lengkap_alive.yaml",
        "output/strict_alive.yaml",
        "output/manual_only.yaml",
    ]
    reports: List[Dict[str, Any]] = [validate((root / item).resolve()) for item in files]
    out = root / "output" / "Validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "game_block_inline_safe_validation.json").write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = all(r.get("ok", True) for r in reports if "missing file" not in (r.get("warnings") or []))
    for r in reports:
        if r.get("errors"):
            print(f"ERROR validating {r['file']}:")
            for err in r["errors"]:
                print(f"  - {err}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

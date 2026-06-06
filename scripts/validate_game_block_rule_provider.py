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

REQUIRED_PROVIDER_NAMES = {"GAME-BLOCK-DOMAIN", "GAME-BLOCK-CLASSICAL"}
REQUIRED_RULES = {"RULE-SET,GAME-BLOCK-DOMAIN,BLOCK", "RULE-SET,GAME-BLOCK-CLASSICAL,BLOCK"}
REQUIRED_PROVIDER_FILES = [
    "rules/providers/game_block_domain.yaml",
    "rules/providers/game_block_classical.yaml",
]


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))


def validate_provider_file(root: Path, rel: str) -> List[str]:
    path = root / rel
    errors: List[str] = []
    if not path.exists():
        return [f"missing provider file: {rel}"]
    try:
        data = load_yaml(path)
    except Exception as exc:
        return [f"provider file parse error {rel}: {exc}"]
    payload = data.get("payload") if isinstance(data, dict) else None
    if not isinstance(payload, list) or not payload:
        errors.append(f"provider file has empty payload: {rel}")
    return errors


def validate_output_yaml(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {"file": str(path), "errors": []}
    if not path.exists():
        result["errors"].append("file missing")
        return result
    try:
        data = load_yaml(path)
    except Exception as exc:
        result["errors"].append(f"YAML parse error: {exc}")
        return result
    if not isinstance(data, dict):
        result["errors"].append("YAML root must be mapping")
        return result
    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        result["errors"].append("rule-providers missing or not mapping")
    else:
        missing = REQUIRED_PROVIDER_NAMES - set(map(str, providers.keys()))
        if missing:
            result["errors"].append("missing rule-providers: " + ", ".join(sorted(missing)))
        for name in REQUIRED_PROVIDER_NAMES & set(map(str, providers.keys())):
            cfg = providers.get(name)
            if not isinstance(cfg, dict):
                result["errors"].append(f"provider {name} not mapping")
                continue
            if cfg.get("type") != "http":
                result["errors"].append(f"provider {name} type must be http")
            if cfg.get("behavior") not in {"domain", "classical"}:
                result["errors"].append(f"provider {name} invalid behavior: {cfg.get('behavior')}")
            if not str(cfg.get("url") or "").startswith("https://raw.githubusercontent.com/"):
                result["errors"].append(f"provider {name} must use raw GitHub URL")
            if not str(cfg.get("path") or ""):
                result["errors"].append(f"provider {name} missing path")
    groups = data.get("proxy-groups") or []
    block = None
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, dict) and g.get("name") == "BLOCK":
                block = g
                break
    if not isinstance(block, dict):
        result["errors"].append("BLOCK selector group missing")
    elif block.get("type") != "select":
        result["errors"].append("BLOCK group must be select")
    else:
        proxies = [str(x) for x in block.get("proxies") or []]
        if "REJECT" not in proxies:
            result["errors"].append("BLOCK selector must contain REJECT")
    rules = [str(r).strip() for r in (data.get("rules") or [])] if isinstance(data.get("rules"), list) else []
    for rule in REQUIRED_RULES:
        if rule not in rules:
            result["errors"].append(f"missing game block rule: {rule}")
    # Enforce prior policy: no direct rule target to DIRECT or REJECT.
    for rule in rules:
        parts = [p.strip() for p in rule.split(",")]
        if len(parts) >= 2:
            target = parts[-1]
            if target.lower() == "no-resolve" and len(parts) >= 3:
                target = parts[-2]
            if target in {"DIRECT", "REJECT"}:
                result["errors"].append(f"DIRECT/REJECT used as direct rule target: {rule}")
    result["ok"] = not result["errors"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    errors: List[str] = []
    for rel in REQUIRED_PROVIDER_FILES:
        errors.extend(validate_provider_file(root, rel))
    paths = [Path(p) if Path(p).is_absolute() else root / p for p in args.paths]
    if not paths:
        paths = [root / "output" / name for name in ["fast.yaml", "lite.yaml", "lengkap.yaml", "lengkap_alive.yaml", "strict_alive.yaml", "manual_only.yaml"]]
    reports = []
    for path in paths:
        report = validate_output_yaml(path)
        reports.append(report)
        errors.extend([f"{path}: {e}" for e in report.get("errors", [])])
    out = root / "output" / "Validation"
    out.mkdir(parents=True, exist_ok=True)
    final = {"ok": not errors, "errors": errors, "files": reports}
    (out / "game_block_rule_provider_validation.json").write_text(json.dumps(final, indent=2, ensure_ascii=False), encoding="utf-8")
    if errors:
        for err in errors:
            print("ERROR:", err)
        return 1
    print("Game block rule-provider validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

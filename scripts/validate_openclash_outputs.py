#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Set

try:
    import yaml
except Exception as exc:
    print(f"ERROR: PyYAML required: {exc}", file=sys.stderr)
    sys.exit(2)

ALLOWED_GROUP_TYPES = {"select", "url-test", "fallback"}
DROP_PROXY_TYPES = {"ss", "ssr"}
RISKY_TOP_KEYS = {"tcp-concurrent", "unified-delay"}
RISKY_GROUP_KEYS = {"lazy", "timeout", "strategy"}
SPECIAL_OUTBOUNDS = {"DIRECT", "REJECT"}


def validate_file(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {"file": str(path), "errors": [], "warnings": []}
    if not path.exists():
        result["warnings"].append("file missing")
        return result
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        result["errors"].append(f"YAML parse error: {exc}")
        return result
    if not isinstance(data, dict):
        result["errors"].append("YAML root must be mapping")
        return result

    for key in RISKY_TOP_KEYS:
        if key in data:
            result["errors"].append(f"risky top-level key present: {key}")

    proxies = data.get("proxies") or []
    if not isinstance(proxies, list) or not proxies:
        result["errors"].append("proxies must be non-empty list")
        proxy_names: Set[str] = set()
    else:
        proxy_names = set()
        for idx, proxy in enumerate(proxies):
            if not isinstance(proxy, dict):
                result["errors"].append(f"proxy[{idx}] not mapping")
                continue
            name = str(proxy.get("name") or "").strip()
            typ = str(proxy.get("type") or "").strip().lower()
            if not name:
                result["errors"].append(f"proxy[{idx}] missing name")
            if typ in DROP_PROXY_TYPES:
                result["errors"].append(f"unsupported proxy type remains: {name} type={typ}")
            if name in proxy_names:
                result["errors"].append(f"duplicate proxy name: {name}")
            proxy_names.add(name)

    groups = data.get("proxy-groups") or []
    if not isinstance(groups, list) or not groups:
        result["errors"].append("proxy-groups must be non-empty list")
        group_names: Set[str] = set()
    else:
        group_names = set()
        for idx, group in enumerate(groups):
            if not isinstance(group, dict):
                result["errors"].append(f"proxy-group[{idx}] not mapping")
                continue
            name = str(group.get("name") or "").strip()
            typ = str(group.get("type") or "").strip()
            if not name:
                result["errors"].append(f"proxy-group[{idx}] missing name")
                continue
            if name in group_names:
                result["errors"].append(f"duplicate group name: {name}")
            group_names.add(name)
            if typ not in ALLOWED_GROUP_TYPES:
                result["errors"].append(f"unsupported group type in {name}: {typ}")
            for key in RISKY_GROUP_KEYS:
                if key in group:
                    result["errors"].append(f"risky group key in {name}: {key}")
            members = group.get("proxies") or []
            if not isinstance(members, list) or not members:
                result["errors"].append(f"group {name} has empty/non-list proxies")
                continue
            if typ != "select":
                for member in members:
                    if str(member) in SPECIAL_OUTBOUNDS:
                        result["errors"].append(f"{member} appears in non-selector group {name}")
            for member in members:
                member_name = str(member)
                if member_name in SPECIAL_OUTBOUNDS:
                    continue
                if member_name not in proxy_names and member_name not in group_names:
                    # group_names may be incomplete during loop, checked again below after set complete.
                    pass

        # Second pass now group_names is complete.
        for group in groups:
            if not isinstance(group, dict):
                continue
            name = str(group.get("name") or "").strip()
            for member in group.get("proxies") or []:
                member_name = str(member)
                if member_name in SPECIAL_OUTBOUNDS:
                    continue
                if member_name not in proxy_names and member_name not in group_names:
                    result["errors"].append(f"group {name} references missing proxy/group: {member_name}")

    rules = data.get("rules") or []
    if not isinstance(rules, list) or not rules:
        result["errors"].append("rules must be non-empty list")
    else:
        seen_match = False
        for rule in rules:
            text = str(rule).strip()
            if not text:
                continue
            parts = [p.strip() for p in text.split(")") if p.strip()] if False else [p.strip() for p in text.split(",")]
            target_idx = len(parts) - 1
            if target_idx >= 0 and parts[target_idx].lower() == "no-resolve":
                target_idx -= 1
            if target_idx < 0:
                result["errors"].append(f"invalid rule: {text}")
                continue
            target = parts[target_idx]
            if target in SPECIAL_OUTBOUNDS:
                result["errors"].append(f"DIRECT/REJECT used as direct rule target: {text}")
            elif target not in group_names:
                result["errors"].append(f"rule target missing group: {target} in {text}")
            if text.upper().startswith("MATCH,"):
                seen_match = True
        if not seen_match:
            result["errors"].append("MATCH rule missing")

    result["ok"] = not result["errors"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        args = ["output/fast.yaml", "output/lite.yaml", "output/lengkap.yaml", "output/lengkap_alive.yaml", "output/strict_alive.yaml", "output/manual_only.yaml"]
    reports: List[Dict[str, Any]] = []
    ok = True
    for item in args:
        path = Path(item)
        report = validate_file(path)
        reports.append(report)
        if report.get("errors"):
            ok = False
            print(f"ERROR validating {path}:")
            for err in report["errors"]:
                print(f"  - {err}")
        else:
            print(f"OK: {path}")
    out = Path("output/Validation")
    out.mkdir(parents=True, exist_ok=True)
    (out / "openclash_validation_report.json").write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

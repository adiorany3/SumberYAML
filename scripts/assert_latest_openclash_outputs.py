#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    print(f"ERROR: PyYAML required: {exc}", file=sys.stderr)
    sys.exit(2)

REQUIRED_GROUPS = {"PROXY", "UTAMA", "AUTO", "FALLBACK", "GOOGLE", "YOUTUBE", "REDDIT", "LINKEDIN", "BLIBLI", "BANK", "MARKETPLACE", "SOCIAL", "BYPASS", "BLOCK"}
REQUIRED_REPORTS = [
    "output/Validation/app_aware_groups_report.json",
    "output/Validation/openclash_validation_report.json",
    "output/Validation/last_run.json",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    errors = []
    for rel in REQUIRED_REPORTS:
        if not (root / rel).exists():
            errors.append(f"missing report: {rel}")
    yaml_path = root / "output/fast.yaml"
    if not yaml_path.exists():
        errors.append("missing output/fast.yaml")
    else:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="ignore"))
        groups = {str(g.get("name")) for g in (data.get("proxy-groups") or []) if isinstance(g, dict)} if isinstance(data, dict) else set()
        missing = sorted(REQUIRED_GROUPS - groups)
        if missing:
            errors.append("missing required groups in fast.yaml: " + ", ".join(missing))
        rules = [str(r) for r in (data.get("rules") or [])] if isinstance(data, dict) else []
        needed_rules = ["DOMAIN-SUFFIX,youtube.com,YOUTUBE", "DOMAIN-SUFFIX,google.com,GOOGLE", "DOMAIN-SUFFIX,linkedin.com,LINKEDIN", "DOMAIN-SUFFIX,blibli.com,BLIBLI", "DOMAIN-SUFFIX,reddit.com,REDDIT"]
        for rule in needed_rules:
            if rule not in rules:
                errors.append(f"missing app-aware rule: {rule}")
        for rule in rules:
            if rule.endswith(",DIRECT") or rule.endswith(",REJECT"):
                errors.append(f"DIRECT/REJECT direct rule target found: {rule}")
    report = {"ok": not errors, "errors": errors}
    out = root / "output/Validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "assert_latest_openclash_outputs.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if errors:
        for err in errors:
            print("ERROR:", err)
        return 1
    print("Latest app-aware OpenClash output assertion OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

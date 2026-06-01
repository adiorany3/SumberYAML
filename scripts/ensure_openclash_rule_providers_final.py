#!/usr/bin/env python3
"""Ensure final OpenClash YAML files contain adblock rule-providers.

Runs safely at the very end of the workflow, after any YAML builders that may
overwrite openclash-ready.yaml or output/*.yaml. It does not remove or filter
trusted manual accounts from input.txt/input/links.txt.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROVIDER_DEFS = {
    "youtube-ads": "youtube-ads.yaml",
    "general-ads": "general-ads.yaml",
}
PROVIDER_RULES = [
    "RULE-SET,youtube-ads,REJECT",
    "RULE-SET,general-ads,REJECT",
]

YAML_TARGETS = [
    "output/openclash-ready.yaml",
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/general.yaml",
]


def raw_url(repo: str, branch: str, file_name: str) -> str:
    repo = repo.strip() or "adiorany3/SumberYAML"
    branch = branch.strip() or "main"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/output/RuleProviders/{file_name}"


def load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::warning::failed to read {path}: {exc}")
        return None
    if not isinstance(data, dict):
        return None
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def insert_provider_rules(rules: list[Any]) -> list[Any]:
    cleaned = [rule for rule in rules if not (isinstance(rule, str) and rule in PROVIDER_RULES)]
    insert_at = len(cleaned)
    for idx, rule in enumerate(cleaned):
        if isinstance(rule, str) and rule.startswith("MATCH,"):
            insert_at = idx
            break
    for rule in reversed(PROVIDER_RULES):
        cleaned.insert(insert_at, rule)
    # de-duplicate while preserving order
    out: list[Any] = []
    seen: set[str] = set()
    for rule in cleaned:
        if isinstance(rule, str):
            if rule in seen:
                continue
            seen.add(rule)
        out.append(rule)
    return out


def ensure_yaml(path: Path, repo: str, branch: str) -> dict[str, Any]:
    data = load_yaml(path)
    if data is None:
        return {"file": str(path), "changed": False, "skipped": True, "reason": "not a YAML mapping"}

    changed = False
    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers
        changed = True

    for provider_name, file_name in PROVIDER_DEFS.items():
        expected = {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "path": f"./rule_provider/{file_name}",
            "url": raw_url(repo, branch, file_name),
            "interval": 86400,
        }
        if providers.get(provider_name) != expected:
            providers[provider_name] = expected
            changed = True

    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = ["MATCH,PROXY"]
        data["rules"] = rules
        changed = True

    new_rules = insert_provider_rules(rules)
    if new_rules != rules:
        data["rules"] = new_rules
        changed = True

    if changed:
        dump_yaml(path, data)

    return {
        "file": str(path),
        "changed": changed,
        "skipped": False,
        "providers": list(PROVIDER_DEFS.keys()),
        "provider_rules_present": all(rule in data.get("rules", []) for rule in PROVIDER_RULES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for target in YAML_TARGETS:
        path = root / target
        if path.exists():
            results.append(ensure_yaml(path, args.repo, args.branch))
        else:
            results.append({"file": target, "changed": False, "skipped": True, "reason": "missing"})

    summary = {
        "ok": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": args.repo,
        "branch": args.branch,
        "provider_files_expected": [f"output/RuleProviders/{name}" for name in PROVIDER_DEFS.values()],
        "results": results,
        "trusted_manual_accounts_note": "input.txt and input/links.txt are not filtered or modified by this script.",
    }
    (validation_dir / "summary_rule_providers_final.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

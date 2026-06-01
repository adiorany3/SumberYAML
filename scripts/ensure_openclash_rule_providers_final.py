#!/usr/bin/env python3
"""Ensure adblock rule-providers exist in final OpenClash YAML files.

Runs at the very end of the workflow so final builders cannot overwrite providers.
This script also force-creates output/RuleProviders/youtube-ads.yaml and
output/RuleProviders/general-ads.yaml.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

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

PROVIDER_RULES = [
    "RULE-SET,youtube-ads,REJECT",
    "RULE-SET,general-ads,REJECT",
]


def raw_provider_url(repo: str, branch: str, provider_file: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip()
    branch = (branch or "main").strip()
    return f"https://raw.githubusercontent.com/{repo}/{branch}/output/RuleProviders/{provider_file}"


def make_rule_providers(repo: str, branch: str) -> dict[str, dict[str, Any]]:
    return {
        "youtube-ads": {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "path": "./rule_provider/youtube-ads.yaml",
            "url": raw_provider_url(repo, branch, "youtube-ads.yaml"),
            "interval": 86400,
        },
        "general-ads": {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "path": "./rule_provider/general-ads.yaml",
            "url": raw_provider_url(repo, branch, "general-ads.yaml"),
            "interval": 86400,
        },
    }


def ensure_provider_files(root: Path, repo: str, branch: str) -> None:
    script = root / "scripts" / "create_rule_provider_files.py"
    if script.exists():
        subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--repo", repo, "--branch", branch],
            check=True,
        )
        return

    # Fallback minimal writer if the helper script is missing.
    provider_dir = root / "output" / "RuleProviders"
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "youtube-ads.yaml").write_text(
        "payload:\n"
        "  - \"DOMAIN,pagead2.googlesyndication.com\"\n"
        "  - \"DOMAIN-SUFFIX,doubleclick.net\"\n"
        "  - \"DOMAIN-SUFFIX,googlesyndication.com\"\n",
        encoding="utf-8",
    )
    (provider_dir / "general-ads.yaml").write_text(
        "payload:\n"
        "  - \"DOMAIN-SUFFIX,doubleclick.net\"\n"
        "  - \"DOMAIN-SUFFIX,googlesyndication.com\"\n"
        "  - \"DOMAIN-SUFFIX,googleadservices.com\"\n"
        "  - \"DOMAIN-SUFFIX,taboola.com\"\n"
        "  - \"DOMAIN-SUFFIX,outbrain.com\"\n",
        encoding="utf-8",
    )


def load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] failed to read {path}: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"[WARN] skip non-dict YAML: {path}")
        return None
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def normalize_rules(rules: Any) -> list[str]:
    if not isinstance(rules, list):
        return ["MATCH,PROXY"]
    return [str(item).strip() for item in rules if str(item).strip()]


def insert_provider_rules(rules: list[str]) -> tuple[list[str], int]:
    # Remove duplicates first.
    existing_without_provider = [r for r in rules if r not in PROVIDER_RULES]

    # Insert after local/direct rules but before routing/proxy rules. If unsure, put at top.
    insert_at = 0
    direct_prefixes = (
        "DOMAIN-SUFFIX,local,DIRECT",
        "DOMAIN-SUFFIX,lan,DIRECT",
        "IP-CIDR,127.",
        "IP-CIDR,10.",
        "IP-CIDR,172.16.",
        "IP-CIDR,192.168.",
        "IP-CIDR,169.254.",
        "IP-CIDR,224.",
        "IP-CIDR,255.255.255.255",
        "GEOIP,LAN,DIRECT",
        "DST-PORT,53,DIRECT",
    )
    for idx, rule in enumerate(existing_without_provider):
        if rule.startswith(direct_prefixes):
            insert_at = idx + 1
            continue
        break

    new_rules = existing_without_provider[:insert_at] + PROVIDER_RULES + existing_without_provider[insert_at:]
    return new_rules, len(PROVIDER_RULES)


def apply_to_yaml(path: Path, repo: str, branch: str) -> dict[str, Any]:
    data = load_yaml(path)
    if data is None:
        return {"path": str(path), "ok": False, "reason": "unreadable"}

    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
    providers.update(make_rule_providers(repo, branch))
    data["rule-providers"] = providers

    rules = normalize_rules(data.get("rules"))
    new_rules, inserted = insert_provider_rules(rules)
    data["rules"] = new_rules

    dump_yaml(path, data)
    return {
        "path": str(path),
        "ok": True,
        "provider_count": len(data.get("rule-providers", {})),
        "rules_count": len(new_rules),
        "inserted_provider_rules": inserted,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    repo = (args.repo or "adiorany3/SumberYAML").strip()
    branch = (args.branch or "main").strip()

    ensure_provider_files(root, repo, branch)

    results = []
    for rel in YAML_TARGETS:
        path = root / rel
        if path.exists():
            results.append(apply_to_yaml(path, repo, branch))
        else:
            results.append({"path": rel, "ok": False, "reason": "missing"})

    summary = {
        "ok": any(item.get("ok") for item in results),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": repo,
        "branch": branch,
        "provider_files": [
            "output/RuleProviders/youtube-ads.yaml",
            "output/RuleProviders/general-ads.yaml",
        ],
        "target_files": results,
    }
    out_dir = root / "output" / "Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary_rule_providers_final.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

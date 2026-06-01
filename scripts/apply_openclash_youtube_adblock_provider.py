#!/usr/bin/env python3
"""
Add an optional YouTube ads/telemetry rule-provider to generated OpenClash/Mihomo YAML outputs.

Design goals for SumberYAML:
- Do not modify or filter trusted manual accounts from input.txt / input/links.txt.
- Do not remove proxy nodes or proxy-groups.
- Only add/update a rule-provider and insert one RULE-SET rule near the top of rules.
- Keep the provider list conservative to reduce the risk of breaking YouTube playback.

Usage:
  python scripts/apply_openclash_youtube_adblock_provider.py \
    --repo adiorany3/SumberYAML \
    --branch main

Optional:
  --target REJECT            Rule target, default REJECT
  --provider-name youtube-ads
  --aggressive              Add extra telemetry domains. May break some YouTube features.
  --cdn                     Use jsDelivr CDN URL instead of raw GitHub URL
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: pip install pyyaml") from exc


DEFAULT_TARGET_FILES = [
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
    "output/openclash-ready.yaml",
]

# Conservative list. Avoid googlevideo.com, ytimg.com, youtubei.googleapis.com,
# youtube.com, and youtube-nocookie.com because blocking them can break playback/login.
SAFE_YOUTUBE_AD_RULES = [
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,ads.youtube.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,adservice.google.co.id",
    "DOMAIN-SUFFIX,static.doubleclick.net",
    "DOMAIN,ad.doubleclick.net",
    "DOMAIN,googleads.g.doubleclick.net",
    "DOMAIN,pagead2.googlesyndication.com",
    "DOMAIN,partnerad.l.doubleclick.net",
    "DOMAIN,securepubads.g.doubleclick.net",
]

# Extra telemetry/stat domains. These are intentionally optional because some clients
# report playback/account feature issues when YouTube telemetry is blocked too broadly.
AGGRESSIVE_EXTRA_RULES = [
    "DOMAIN-SUFFIX,s.youtube.com",
    "DOMAIN-SUFFIX,video-stats.l.google.com",
    "DOMAIN,video-stats.l.google.com",
    "DOMAIN,play.google.com/log",
]

LOCAL_DIRECT_PREFIXES = (
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.",
    "IP-CIDR,10.",
    "IP-CIDR,172.16.",
    "IP-CIDR,172.17.",
    "IP-CIDR,172.18.",
    "IP-CIDR,172.19.",
    "IP-CIDR,172.20.",
    "IP-CIDR,172.21.",
    "IP-CIDR,172.22.",
    "IP-CIDR,172.23.",
    "IP-CIDR,172.24.",
    "IP-CIDR,172.25.",
    "IP-CIDR,172.26.",
    "IP-CIDR,172.27.",
    "IP-CIDR,172.28.",
    "IP-CIDR,172.29.",
    "IP-CIDR,172.30.",
    "IP-CIDR,172.31.",
    "IP-CIDR,192.168.",
    "IP-CIDR,169.254.",
    "IP-CIDR,224.",
    "IP-CIDR,255.255.255.255",
)


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def provider_url(repo: str, branch: str, provider_file: str, cdn: bool) -> str:
    provider_file = provider_file.strip("/")
    if cdn:
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{provider_file}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{provider_file}"


def ensure_rule_provider(data: Dict[str, Any], provider_name: str, url: str, path: str) -> bool:
    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers

    old = providers.get(provider_name)
    new_provider = {
        "type": "http",
        "behavior": "classical",
        "path": path,
        "url": url,
        "interval": 86400,
    }
    changed = old != new_provider
    providers[provider_name] = new_provider
    return changed


def insert_rule_set(data: Dict[str, Any], provider_name: str, target: str) -> bool:
    rule = f"RULE-SET,{provider_name},{target}"
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules

    original = list(rules)
    rules = [r for r in rules if not (isinstance(r, str) and r.startswith(f"RULE-SET,{provider_name},"))]

    # Place after LAN/local direct rules, before category/domain/proxy rules.
    insert_at = 0
    for i, item in enumerate(rules):
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text.startswith(LOCAL_DIRECT_PREFIXES):
            insert_at = i + 1

    rules.insert(insert_at, rule)
    data["rules"] = rules
    return rules != original


def write_provider_payload(root: Path, rules: List[str]) -> Path:
    provider_path = root / "output" / "RuleProviders" / "youtube-ads.yaml"
    provider_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"payload": sorted(dict.fromkeys(rules))}
    dump_yaml(provider_path, payload)
    return provider_path


def apply_to_file(path: Path, provider_name: str, url: str, provider_local_path: str, target: str) -> Dict[str, Any]:
    if not path.exists():
        return {"file": str(path), "exists": False, "changed": False}
    data = load_yaml(path)
    if not data:
        return {"file": str(path), "exists": True, "changed": False, "error": "empty_or_invalid_yaml"}

    changed_provider = ensure_rule_provider(data, provider_name, url, provider_local_path)
    changed_rule = insert_rule_set(data, provider_name, target)
    changed = changed_provider or changed_rule
    if changed:
        dump_yaml(path, data)
    return {
        "file": str(path),
        "exists": True,
        "changed": changed,
        "provider_changed": changed_provider,
        "rule_changed": changed_rule,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", os.environ.get("GITHUB_REF", "main")).replace("refs/heads/", ""))
    parser.add_argument("--provider-name", default="youtube-ads")
    parser.add_argument("--target", default="REJECT")
    parser.add_argument("--cdn", action="store_true", help="Use jsDelivr URL for provider instead of raw GitHub.")
    parser.add_argument("--aggressive", action="store_true", help="Add extra telemetry domains. May break some YouTube features.")
    parser.add_argument("--files", nargs="*", default=DEFAULT_TARGET_FILES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    provider_file = "output/RuleProviders/youtube-ads.yaml"
    provider_local_path = "./rule_provider/youtube-ads.yaml"
    rules = list(SAFE_YOUTUBE_AD_RULES)
    if args.aggressive:
        rules.extend(AGGRESSIVE_EXTRA_RULES)

    provider_path = write_provider_payload(root, rules)
    url = provider_url(args.repo, args.branch or "main", provider_file, args.cdn)

    results = []
    for file_name in args.files:
        results.append(apply_to_file(root / file_name, args.provider_name, url, provider_local_path, args.target))

    summary = {
        "provider_name": args.provider_name,
        "target": args.target,
        "repo": args.repo,
        "branch": args.branch,
        "provider_file": str(provider_path.relative_to(root)) if provider_path.is_relative_to(root) else str(provider_path),
        "provider_url": url,
        "rule_count": len(sorted(dict.fromkeys(rules))),
        "aggressive": bool(args.aggressive),
        "changed_files": sum(1 for item in results if item.get("changed")),
        "results": results,
        "note": "This blocks common YouTube/Google ad domains. It cannot guarantee 100% YouTube ad blocking because YouTube may serve ads and videos from shared domains.",
    }
    out = root / "output" / "Validation" / "summary_youtube_adblock_provider.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Force OpenClash/Mihomo rule-providers into final YAML outputs.

This script is intentionally designed to run at the very end of the workflow,
after openclash-ready.yaml and other final YAML files may have been rebuilt.
It creates provider payload files and injects RULE-SET entries into every YAML.

Trusted manual accounts from input.txt / input/links.txt are not filtered,
removed, or modified by this script.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

ROOT = Path.cwd()

YAML_FILES = [
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

# Conservative rules: avoid blocking domains that commonly carry main app/video traffic.
YOUTUBE_AD_RULES = [
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,googleads.g.doubleclick.net",
    "DOMAIN-SUFFIX,static.doubleclick.net",
    "DOMAIN-SUFFIX,ad.doubleclick.net",
    "DOMAIN-SUFFIX,ade.googlesyndication.com",
    "DOMAIN-SUFFIX,partnerad.l.doubleclick.net",
    "DOMAIN-KEYWORD,googleads",
    "DOMAIN-KEYWORD,doubleclick",
    # YouTube telemetry/ads-adjacent endpoints. Avoid googlevideo/youtubei/youtube/ytimg core.
    "DOMAIN,ads.youtube.com",
    "DOMAIN-SUFFIX,ads.youtube.com",
    "DOMAIN-SUFFIX,youtube-nocookie.com",
]

GENERAL_AD_RULES = [
    "DOMAIN-SUFFIX,adnxs.com",
    "DOMAIN-SUFFIX,adsrvr.org",
    "DOMAIN-SUFFIX,adsafeprotected.com",
    "DOMAIN-SUFFIX,adform.net",
    "DOMAIN-SUFFIX,adroll.com",
    "DOMAIN-SUFFIX,adsterra.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,advertising.com",
    "DOMAIN-SUFFIX,appsflyer.com",
    "DOMAIN-SUFFIX,atdmt.com",
    "DOMAIN-SUFFIX,bidswitch.net",
    "DOMAIN-SUFFIX,casalemedia.com",
    "DOMAIN-SUFFIX,chartbeat.com",
    "DOMAIN-SUFFIX,criteo.com",
    "DOMAIN-SUFFIX,criteo.net",
    "DOMAIN-SUFFIX,doubleverify.com",
    "DOMAIN-SUFFIX,flashtalking.com",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,googletagmanager.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,imrworldwide.com",
    "DOMAIN-SUFFIX,indexww.com",
    "DOMAIN-SUFFIX,mathtag.com",
    "DOMAIN-SUFFIX,moatads.com",
    "DOMAIN-SUFFIX,openx.net",
    "DOMAIN-SUFFIX,outbrain.com",
    "DOMAIN-SUFFIX,pubmatic.com",
    "DOMAIN-SUFFIX,quantserve.com",
    "DOMAIN-SUFFIX,scorecardresearch.com",
    "DOMAIN-SUFFIX,sharethrough.com",
    "DOMAIN-SUFFIX,taboola.com",
    "DOMAIN-SUFFIX,tapad.com",
    "DOMAIN-SUFFIX,the-ozone-project.com",
    "DOMAIN-SUFFIX,turn.com",
    "DOMAIN-SUFFIX,zedo.com",
    "DOMAIN-KEYWORD,adservice",
    "DOMAIN-KEYWORD,adserver",
    "DOMAIN-KEYWORD,analytics",
    "DOMAIN-KEYWORD,tracking",
]

PROVIDER_SPECS = {
    "youtube-ads": {
        "file": "youtube-ads.yaml",
        "path": "./rule_provider/youtube-ads.yaml",
        "rules": YOUTUBE_AD_RULES,
        "rule_line": "RULE-SET,youtube-ads,REJECT",
    },
    "general-ads": {
        "file": "general-ads.yaml",
        "path": "./rule_provider/general-ads.yaml",
        "rules": GENERAL_AD_RULES,
        "rule_line": "RULE-SET,general-ads,REJECT",
    },
}


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = str(item).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def write_provider_files(root: Path) -> dict[str, Any]:
    provider_dir = root / "output" / "RuleProviders"
    provider_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {}
    for name, spec in PROVIDER_SPECS.items():
        payload = unique_keep_order(spec["rules"])
        target = provider_dir / spec["file"]
        target.write_text(
            yaml.safe_dump(
                {"payload": payload},
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        result[name] = {"path": str(target), "rule_count": len(payload)}
    return result


def build_provider_url(repo: str, branch: str, provider_file: str, url_source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip().strip("/")
    branch = (branch or "main").strip() or "main"
    if url_source == "cdn":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/output/RuleProviders/{provider_file}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/output/RuleProviders/{provider_file}"


def load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=160,
        ),
        encoding="utf-8",
    )


def ensure_rule_providers(data: dict[str, Any], repo: str, branch: str, url_source: str) -> int:
    changed = 0
    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers
        changed += 1

    for name, spec in PROVIDER_SPECS.items():
        provider = {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "path": spec["path"],
            "url": build_provider_url(repo, branch, spec["file"], url_source),
            "interval": 86400,
        }
        if providers.get(name) != provider:
            providers[name] = provider
            changed += 1
    return changed


def is_provider_rule(rule: Any) -> bool:
    text = str(rule).strip()
    return text.startswith("RULE-SET,youtube-ads,") or text.startswith("RULE-SET,general-ads,")


def is_lan_or_dns_direct_rule(rule: Any) -> bool:
    text = str(rule).strip()
    if not text:
        return False
    upper = text.upper()
    if ",DIRECT" not in upper:
        return False
    direct_prefixes = (
        "DOMAIN-SUFFIX,LOCAL,",
        "DOMAIN-SUFFIX,LAN,",
        "DOMAIN,LOCALHOST,",
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
        "DST-PORT,53,",
    )
    return upper.startswith(direct_prefixes)


def ensure_reject_policy(data: dict[str, Any]) -> int:
    """Keep compatibility for validators that expect REJECT as an outbound option.

    Clash/Mihomo supports REJECT directly in rules, so no proxy is required. But if a
    config has a top-level proxies list and a strict checker only sees names, adding a
    minimal REJECT provider as a group option is not necessary and may be invalid.
    Therefore this function intentionally does nothing.
    """
    return 0


def ensure_rules(data: dict[str, Any]) -> int:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules
        changed = 1
    else:
        changed = 0

    provider_rules = [
        PROVIDER_SPECS["youtube-ads"]["rule_line"],
        PROVIDER_SPECS["general-ads"]["rule_line"],
    ]

    old_rules = [rule for rule in rules if not is_provider_rule(rule)]

    # Put adblock rules after early LAN/DNS direct rules and before traffic routing.
    insert_idx = 0
    for idx, rule in enumerate(old_rules):
        if is_lan_or_dns_direct_rule(rule):
            insert_idx = idx + 1
        else:
            # Stop once normal routing rules start.
            if insert_idx > 0:
                break

    new_rules = old_rules[:insert_idx] + provider_rules + old_rules[insert_idx:]

    # Ensure final rule exists if config had no meaningful rules.
    if not any(str(rule).strip().upper().startswith("MATCH,") for rule in new_rules):
        new_rules.append("MATCH,PROXY")

    if new_rules != rules:
        data["rules"] = new_rules
        changed += 1
    return changed


def apply_to_yaml(path: Path, repo: str, branch: str, url_source: str) -> dict[str, Any]:
    data = load_yaml(path)
    if data is None:
        return {"path": str(path), "exists": path.exists(), "ok": False, "changed": False, "reason": "not a YAML mapping or missing"}

    before = path.read_text(encoding="utf-8") if path.exists() else ""
    changes = 0
    changes += ensure_rule_providers(data, repo, branch, url_source)
    changes += ensure_reject_policy(data)
    changes += ensure_rules(data)
    dump_yaml(path, data)
    after = path.read_text(encoding="utf-8")
    return {
        "path": str(path),
        "exists": True,
        "ok": True,
        "changed": before != after or changes > 0,
        "rules_count": len(data.get("rules", []) or []),
        "provider_count": len(data.get("rule-providers", {}) or {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--url-source", choices=["raw", "cdn"], default="raw")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()

    root = ROOT
    provider_result = write_provider_files(root)

    yaml_files = args.only if args.only else YAML_FILES
    results = []
    for file_name in yaml_files:
        results.append(apply_to_yaml(root / file_name, args.repo, args.branch, args.url_source))

    summary = {
        "ok": True,
        "note": "Rule providers forced into final YAML outputs at the end of workflow.",
        "repo": args.repo,
        "branch": args.branch,
        "url_source": args.url_source,
        "providers": provider_result,
        "files": results,
        "changed_files": [item["path"] for item in results if item.get("changed")],
        "trusted_manual_accounts_policy": "input.txt and input/links.txt are not filtered or removed by this script.",
    }

    out = root / "output" / "Validation" / "summary_rule_providers_final.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

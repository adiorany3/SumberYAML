#!/usr/bin/env python3
"""
Apply general internet ad-block rule-provider to generated OpenClash/Mihomo YAML.

This script is intentionally conservative:
- It creates output/RuleProviders/general-ads.yaml with classical rules.
- It adds a rule-provider named general-ads to output YAML files.
- It inserts RULE-SET,general-ads,REJECT before broad MATCH rules.
- It does not modify, filter, validate, quarantine, or remove trusted manual accounts
  from input.txt / input/links.txt.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml


DEFAULT_YAML_FILES = [
    "lengkap.yaml",
    "lengkap_alive.yaml",
    "strict_alive.yaml",
    "lite.yaml",
    "fast.yaml",
    "gaming.yaml",
    "social_media.yaml",
    "streaming.yaml",
    "working.yaml",
    "general.yaml",
    "openclash-ready.yaml",
]


GENERAL_AD_RULES = [
    # Google ads / analytics
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,googletagmanager.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,app-measurement.com",

    # Major display/native ad networks
    "DOMAIN-SUFFIX,taboola.com",
    "DOMAIN-SUFFIX,outbrain.com",
    "DOMAIN-SUFFIX,criteo.com",
    "DOMAIN-SUFFIX,criteo.net",
    "DOMAIN-SUFFIX,adsrvr.org",
    "DOMAIN-SUFFIX,adnxs.com",
    "DOMAIN-SUFFIX,adform.net",
    "DOMAIN-SUFFIX,smartadserver.com",
    "DOMAIN-SUFFIX,pubmatic.com",
    "DOMAIN-SUFFIX,openx.net",
    "DOMAIN-SUFFIX,rubiconproject.com",
    "DOMAIN-SUFFIX,contextweb.com",
    "DOMAIN-SUFFIX,casalemedia.com",
    "DOMAIN-SUFFIX,yieldmo.com",
    "DOMAIN-SUFFIX,sharethrough.com",
    "DOMAIN-SUFFIX,indexww.com",
    "DOMAIN-SUFFIX,media.net",
    "DOMAIN-SUFFIX,mgid.com",
    "DOMAIN-SUFFIX,revcontent.com",
    "DOMAIN-SUFFIX,zemanta.com",

    # Mobile ad networks
    "DOMAIN-SUFFIX,adcolony.com",
    "DOMAIN-SUFFIX,applovin.com",
    "DOMAIN-SUFFIX,applvn.com",
    "DOMAIN-SUFFIX,chartboost.com",
    "DOMAIN-SUFFIX,ironsrc.com",
    "DOMAIN-SUFFIX,isnssdk.com",
    "DOMAIN-SUFFIX,mopub.com",
    "DOMAIN-SUFFIX,startappservice.com",
    "DOMAIN-SUFFIX,inmobi.com",
    "DOMAIN-SUFFIX,unityads.unity3d.com",
    "DOMAIN-SUFFIX,vungle.com",

    # Pop / push / aggressive ad networks
    "DOMAIN-SUFFIX,popads.net",
    "DOMAIN-SUFFIX,propellerads.com",
    "DOMAIN-SUFFIX,adsterra.com",
    "DOMAIN-SUFFIX,hilltopads.net",
    "DOMAIN-SUFFIX,exoclick.com",
    "DOMAIN-SUFFIX,juicyads.com",
    "DOMAIN-SUFFIX,onclickads.net",
    "DOMAIN-SUFFIX,trafficjunky.net",

    # Measurement / verification often used by ad stacks
    "DOMAIN-SUFFIX,moatads.com",
    "DOMAIN-SUFFIX,scorecardresearch.com",
    "DOMAIN-SUFFIX,quantserve.com",
    "DOMAIN-SUFFIX,adsafeprotected.com",
    "DOMAIN-SUFFIX,doubleverify.com",
    "DOMAIN-SUFFIX,rlcdn.com",
    "DOMAIN-SUFFIX,bluekai.com",
    "DOMAIN-SUFFIX,demdex.net",

    # Social ad endpoints, kept targeted to ad-specific domains
    "DOMAIN-SUFFIX,ads-twitter.com",
    "DOMAIN-SUFFIX,analytics.twitter.com",
    "DOMAIN-SUFFIX,ads.linkedin.com",
    "DOMAIN-SUFFIX,ads.pinterest.com",
    "DOMAIN-SUFFIX,ads.tiktok.com",
    "DOMAIN-SUFFIX,ads-api.tiktok.com",
    "DOMAIN-SUFFIX,ads-sg.tiktok.com",
    "DOMAIN-SUFFIX,ads-va.tiktok.com",

    # Common regional ad/tracker domains
    "DOMAIN-SUFFIX,adskom.com",
    "DOMAIN-SUFFIX,ambientdsp.com",
    "DOMAIN-SUFFIX,innity.com",
    "DOMAIN-SUFFIX,innity.net",
    "DOMAIN-SUFFIX,komli.com",
    "DOMAIN-SUFFIX,adjust.com",
    "DOMAIN-SUFFIX,appsflyer.com",
    "DOMAIN-SUFFIX,branch.io",
]


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        width=120,
        default_flow_style=False,
    )
    path.write_text(text, encoding="utf-8")


def provider_url(repo: str, branch: str, provider_path: str, url_source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip("/")
    branch = branch or "main"
    provider_path = provider_path.strip("/")
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{provider_path}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{provider_path}"


def normalize_rule(rule: str) -> str:
    return ",".join(str(rule).strip().split(","))


def unique_rules(rules: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for rule in rules:
        r = normalize_rule(rule)
        if not r or r.startswith("#"):
            continue
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def write_provider_file(root: Path, provider_name: str, extra_rules_file: str = "") -> Path:
    provider_dir = root / "output" / "RuleProviders"
    provider_dir.mkdir(parents=True, exist_ok=True)
    provider_file = provider_dir / f"{provider_name}.yaml"

    rules = list(GENERAL_AD_RULES)

    if extra_rules_file:
        p = root / extra_rules_file
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "," in line:
                    rules.append(line)
                else:
                    rules.append(f"DOMAIN-SUFFIX,{line}")

    final_rules = unique_rules(rules)
    provider_file.write_text(
        "# General ad/tracker blocking rules for Mihomo/OpenClash\n"
        "# Generated by scripts/apply_openclash_general_adblock_provider.py\n"
        "# Conservative list: avoids blocking core video/app domains.\n"
        + "\n".join(final_rules)
        + "\n",
        encoding="utf-8",
    )
    return provider_file


def ensure_rule_provider(data: dict[str, Any], provider_name: str, url: str) -> bool:
    changed = False
    rule_providers = data.get("rule-providers")
    if not isinstance(rule_providers, dict):
        rule_providers = {}
        data["rule-providers"] = rule_providers
        changed = True

    desired = {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": f"./rule_provider/{provider_name}.yaml",
        "url": url,
        "interval": 86400,
    }

    existing = rule_providers.get(provider_name)
    if existing != desired:
        rule_providers[provider_name] = desired
        changed = True

    return changed


def insert_adblock_rule(data: dict[str, Any], provider_name: str, target_policy: str = "REJECT") -> bool:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules

    rule_line = f"RULE-SET,{provider_name},{target_policy}"

    new_rules = []
    removed = False
    for item in rules:
        s = str(item).strip()
        if s.startswith(f"RULE-SET,{provider_name},"):
            removed = True
            continue
        new_rules.append(item)

    insert_index = len(new_rules)
    for idx, item in enumerate(new_rules):
        s = str(item).strip().upper()
        if (
            s.startswith("MATCH,")
            or s.startswith("GEOIP,")
            or s.startswith("GEOSITE,")
            or s.endswith(",PROXY")
            or s.endswith(",ANTI-BENGONG")
        ):
            insert_index = idx
            break

    new_rules.insert(insert_index, rule_line)

    changed = removed or (new_rules != rules)
    if changed:
        data["rules"] = new_rules
    return changed


def apply_to_yaml(path: Path, provider_name: str, provider_url_value: str, target_policy: str) -> dict[str, Any]:
    if not path.exists():
        return {"file": str(path), "exists": False, "changed": False}

    data = load_yaml(path)
    if not data:
        return {"file": str(path), "exists": True, "changed": False, "reason": "not_yaml_or_empty"}

    changed = False
    changed = ensure_rule_provider(data, provider_name, provider_url_value) or changed
    changed = insert_adblock_rule(data, provider_name, target_policy=target_policy) or changed

    if changed:
        dump_yaml(path, data)

    return {"file": str(path), "exists": True, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME", "main"))
    parser.add_argument("--provider-name", default="general-ads")
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--target-policy", default="REJECT")
    parser.add_argument("--extra-rules-file", default="", help="Optional file containing additional classical rules or domains")
    parser.add_argument("--yaml-files", nargs="*", default=DEFAULT_YAML_FILES)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    provider_file = write_provider_file(root, args.provider_name, args.extra_rules_file)
    provider_rel = str(provider_file.relative_to(root)).replace("\\", "/")
    url = provider_url(args.repo, args.branch, provider_rel, args.url_source)

    results = []
    for name in args.yaml_files:
        results.append(
            apply_to_yaml(
                root / "output" / name,
                args.provider_name,
                url,
                args.target_policy,
            )
        )

    summary = {
        "ok": True,
        "provider_name": args.provider_name,
        "provider_file": provider_rel,
        "provider_url": url,
        "target_policy": args.target_policy,
        "rules_count": len(unique_rules(GENERAL_AD_RULES)),
        "extra_rules_file": args.extra_rules_file,
        "files": results,
        "changed_count": sum(1 for item in results if item.get("changed")),
        "note": "Trusted manual accounts from input.txt/input/links.txt are not filtered or removed by this script.",
    }

    out_dir = root / "output" / "Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary_general_adblock_provider.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

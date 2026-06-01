#!/usr/bin/env python3
"""
Apply marketplace/live-commerce protection rules to OpenClash/Mihomo YAML outputs.

Purpose:
- Prevent Shopee Live and Indonesian marketplaces from being blocked by adblock/security rule-providers.
- Add output/RuleProviders/marketplace-protect.yaml.
- Insert RULE-SET,marketplace-protect,<target> before REJECT/block rules.
- Remove protected marketplace domains from local block provider payloads when found.

This script does not filter, test, remove, or quarantine manual/trusted accounts from input.txt/input/links.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

DEFAULT_YAML_FILES = [
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

# Domain list is intentionally conservative: marketplace/live-commerce core domains,
# app/API/static/CDN domains known to be required by Indonesian marketplace apps.
# It is NOT a general whitelist; it only prevents marketplace functionality from being rejected.
PROTECT_DOMAIN_SUFFIXES = sorted(set([
    # Shopee / Shopee Live
    "shopee.co.id",
    "shopee.com",
    "shopeemobile.com",
    "shopee.sg",
    "shopee.tw",
    "susercontent.com",
    "shp.ee",
    "shp.shopee.co.id",
    "live.shopee.co.id",
    "mall.shopee.co.id",
    "seller.shopee.co.id",
    "seller.shopee.com",
    "deo.shopeemobile.com",

    # Tokopedia / TikTok Shop relation
    "tokopedia.com",
    "tokopedia.net",
    "tokopedia.co.id",
    "tokopedia.link",
    "tkp.me",
    "tiktokshop.com",
    "seller-id.tiktok.com",
    "shop.tiktok.com",

    # TikTok commerce/live dependencies commonly needed by TikTok Shop/Live
    "tiktok.com",
    "tiktokv.com",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "byteoversea.com",
    "bytefcdn-oversea.com",
    "ibytedtos.com",
    "ibyteimg.com",
    "muscdn.com",

    # Lazada
    "lazada.co.id",
    "lazada.com",
    "lazada.sg",
    "lazada.co.th",
    "lazcdn.com",
    "alicdn.com",
    "alibaba.com",
    "aliexpress.com",
    "taobao.com",

    # Bukalapak
    "bukalapak.com",
    "bukalapak.io",
    "bl.id",

    # Blibli
    "blibli.com",
    "blibli.co.id",

    # Other Indonesian marketplaces / commerce sites
    "olx.co.id",
    "zalora.co.id",
    "zalora.com",
    "bhinneka.com",
    "ralali.com",
    "orami.co.id",
    "sociolla.com",
    "soco.id",
    "tiket.com",
    "traveloka.com",
    "gojek.com",
    "gopay.co.id",
    "grab.com",
    "ovo.id",
    "dana.id",
    "shopeepay.co.id",
]))

PROTECT_KEYWORDS = sorted(set([
    "shopee",
    "susercontent",
    "tokopedia",
    "tiktokshop",
    "lazada",
    "lazcdn",
    "bukalapak",
    "blibli",
    "zalora",
    "sociolla",
    "bhinneka",
]))

BLOCK_PROVIDER_NAMES = [
    "youtube-ads",
    "youtube-ads-advanced",
    "youtube-ads-ultimate",
    "goodbyeads-youtube",
    "general-ads",
    "indonesia-ads",
    "android-ads",
    "malware-adware",
    "game-block",
]

BLOCK_PROVIDER_FILES = [
    "output/RuleProviders/youtube-ads.yaml",
    "output/RuleProviders/youtube-ads-advanced.yaml",
    "output/RuleProviders/youtube-ads-ultimate.yaml",
    "output/RuleProviders/goodbyeads-youtube.yaml",
    "output/RuleProviders/general-ads.yaml",
    "output/RuleProviders/indonesia-ads.yaml",
    "output/RuleProviders/android-ads.yaml",
    "output/RuleProviders/malware-adware.yaml",
    "output/RuleProviders/game-block.yaml",
]


def safe_load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096),
        encoding="utf-8",
    )


def normalize_repo_url(repo: str, branch: str, path: str, url_source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip().strip("/")
    branch = (branch or "main").strip()
    path = path.strip("/")
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def provider_rule(repo: str, branch: str, url_source: str, name: str = "marketplace-protect") -> dict[str, Any]:
    return {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": f"./rule_provider/{name}.yaml",
        "url": normalize_repo_url(repo, branch, "output/RuleProviders/marketplace-protect.yaml", url_source),
        "interval": 86400,
    }


def create_provider_file(root: Path) -> dict[str, Any]:
    payload = []
    for domain in PROTECT_DOMAIN_SUFFIXES:
        payload.append(f"DOMAIN-SUFFIX,{domain}")
    for keyword in PROTECT_KEYWORDS:
        payload.append(f"DOMAIN-KEYWORD,{keyword}")

    provider = {"payload": sorted(set(payload))}
    out_path = root / "output/RuleProviders/marketplace-protect.yaml"
    safe_write_yaml(out_path, provider)
    return {
        "path": str(out_path),
        "rule_count": len(provider["payload"]),
        "domain_suffix_count": len(PROTECT_DOMAIN_SUFFIXES),
        "keyword_count": len(PROTECT_KEYWORDS),
    }


def group_names(config: dict[str, Any]) -> set[str]:
    names = set()
    for group in config.get("proxy-groups", []) or []:
        if isinstance(group, dict) and group.get("name"):
            names.add(str(group.get("name")))
    proxies = config.get("proxies", []) or []
    for proxy in proxies:
        if isinstance(proxy, dict) and proxy.get("name"):
            names.add(str(proxy.get("name")))
    names.add("DIRECT")
    return names


def choose_marketplace_target(config: dict[str, Any], preferred: str | None = None) -> str:
    names = group_names(config)
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend([
        "INDONESIA-BEST",
        "ANTI-BENGONG",
        "PROXY",
        "GLOBAL",
        "DIRECT",
    ])
    for candidate in candidates:
        if candidate in names:
            return candidate
    return "DIRECT"


def is_block_rule(rule: str) -> bool:
    text = str(rule).strip()
    if ",REJECT" in text or text.endswith(",REJECT-DROP"):
        return True
    for provider in BLOCK_PROVIDER_NAMES:
        if text.startswith(f"RULE-SET,{provider},"):
            return True
    return False


def upsert_rule_provider(config: dict[str, Any], repo: str, branch: str, url_source: str) -> None:
    providers = config.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
        config["rule-providers"] = providers
    providers["marketplace-protect"] = provider_rule(repo, branch, url_source)


def upsert_marketplace_rule(config: dict[str, Any], target: str) -> dict[str, Any]:
    rules = config.get("rules")
    if not isinstance(rules, list):
        rules = []
        config["rules"] = rules

    # Remove existing marketplace-protect rules so target/order are deterministic.
    new_rules = [rule for rule in rules if not str(rule).startswith("RULE-SET,marketplace-protect,")]
    marketplace_rule = f"RULE-SET,marketplace-protect,{target}"

    insert_at = None
    for idx, rule in enumerate(new_rules):
        if is_block_rule(str(rule)):
            insert_at = idx
            break
    if insert_at is None:
        # Place before MATCH if present, otherwise append.
        for idx, rule in enumerate(new_rules):
            if str(rule).startswith("MATCH,"):
                insert_at = idx
                break
    if insert_at is None:
        new_rules.append(marketplace_rule)
        inserted_index = len(new_rules) - 1
    else:
        new_rules.insert(insert_at, marketplace_rule)
        inserted_index = insert_at

    config["rules"] = new_rules
    return {"target": target, "inserted_index": inserted_index}


def apply_to_yaml_file(path: Path, repo: str, branch: str, url_source: str, preferred_target: str | None) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False}
    config = safe_load_yaml(path)
    if not isinstance(config, dict):
        return {"path": str(path), "exists": True, "changed": False, "error": "not a mapping"}

    before = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=4096)
    upsert_rule_provider(config, repo, branch, url_source)
    target = choose_marketplace_target(config, preferred=preferred_target)
    rule_info = upsert_marketplace_rule(config, target)
    after = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=4096)
    changed = before != after
    if changed:
        safe_write_yaml(path, config)
    return {
        "path": str(path),
        "exists": True,
        "changed": changed,
        "target": rule_info["target"],
        "inserted_index": rule_info["inserted_index"],
        "has_provider": True,
    }


def domain_from_rule(rule: str) -> str | None:
    parts = str(rule).split(",")
    if len(parts) < 2:
        return None
    if parts[0] in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}:
        return parts[1].strip().lower()
    return None


def is_protected_rule(rule: str) -> bool:
    text = str(rule).strip().lower()
    domain = domain_from_rule(text)
    targets = [domain] if domain else [text]
    for value in targets:
        if not value:
            continue
        for protected in PROTECT_DOMAIN_SUFFIXES:
            if value == protected or value.endswith("." + protected) or protected in value:
                return True
        for keyword in PROTECT_KEYWORDS:
            if keyword in value:
                return True
    return False


def sanitize_block_provider(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "removed": 0, "changed": False}
    data = safe_load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("payload"), list):
        return {"path": str(path), "exists": True, "removed": 0, "changed": False, "error": "no payload"}
    original = data["payload"]
    cleaned = []
    removed = []
    seen = set()
    for item in original:
        text = str(item).strip()
        if not text:
            continue
        if is_protected_rule(text):
            removed.append(text)
            continue
        if text not in seen:
            seen.add(text)
            cleaned.append(text)
    changed = len(cleaned) != len(original)
    if changed:
        data["payload"] = cleaned
        safe_write_yaml(path, data)
    return {"path": str(path), "exists": True, "removed": len(removed), "changed": changed, "removed_examples": removed[:20]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Protect Indonesian marketplace/live-commerce domains from adblock/security rule-providers.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--target", default="", help="Preferred policy/group target, e.g. INDONESIA-BEST or PROXY. Auto-detected if empty.")
    parser.add_argument("--yaml", action="append", default=[], help="Extra YAML file to patch. Can be used multiple times.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    provider_info = create_provider_file(root)

    yaml_files = list(DEFAULT_YAML_FILES)
    for extra in args.yaml:
        if extra and extra not in yaml_files:
            yaml_files.append(extra)

    yaml_results = []
    for file_name in yaml_files:
        yaml_results.append(
            apply_to_yaml_file(
                root / file_name,
                repo=args.repo,
                branch=args.branch,
                url_source=args.url_source,
                preferred_target=args.target or None,
            )
        )

    provider_sanitize_results = []
    for file_name in BLOCK_PROVIDER_FILES:
        provider_sanitize_results.append(sanitize_block_provider(root / file_name))

    summary = {
        "ok": True,
        "provider": provider_info,
        "yaml_files_touched": sum(1 for item in yaml_results if item.get("changed")),
        "yaml_files_existing": sum(1 for item in yaml_results if item.get("exists")),
        "provider_rules_removed": sum(int(item.get("removed", 0) or 0) for item in provider_sanitize_results),
        "yaml_results": yaml_results,
        "provider_sanitize_results": provider_sanitize_results,
        "protected_domain_suffixes": PROTECT_DOMAIN_SUFFIXES,
        "protected_keywords": PROTECT_KEYWORDS,
        "note": "marketplace-protect is inserted before adblock/security REJECT rules. Trusted input.txt/input/links.txt accounts are not filtered or removed.",
    }
    out_path = root / "output/Validation/summary_marketplace_protect_provider.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

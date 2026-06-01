#!/usr/bin/env python3
"""Build an advanced YouTube ads rule-provider for OpenClash/Mihomo.

This script is intentionally DNS/rule-provider based. It improves domain-level
blocking, but it does not try to block YouTube core video/CDN domains because
that would break playback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    raise

GOODBYEADS_YOUTUBE_URL = (
    "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Formats/"
    "GoodbyeAds-YouTube-AdBlock-Filter.txt"
)

YAML_OUTPUTS = [
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

# Core domains are intentionally protected to avoid breaking YouTube playback.
PROTECTED_EXACT = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "studio.youtube.com",
    "youtubei.googleapis.com",
    "i.ytimg.com",
    "ytimg.com",
    "googlevideo.com",
    "gvt1.com",
    "gvt2.com",
    "ggpht.com",
    "googleapis.com",
    "gstatic.com",
    "google.com",
    "accounts.google.com",
}
PROTECTED_SUFFIX = {
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "googlevideo.com",
    "ytimg.com",
    "youtubei.googleapis.com",
}

CURATED_SAFE_RULES = {
    # Google/YouTube ad-related domains that are not core video CDNs.
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googleadsserving.cn",
    "DOMAIN-SUFFIX,2mdn.net",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,adsensecustomsearchads.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,tpc.googlesyndication.com",
    "DOMAIN-SUFFIX,partner.googleadservices.com",
    "DOMAIN-SUFFIX,static.doubleclick.net",
    "DOMAIN-SUFFIX,ad.doubleclick.net",
    "DOMAIN-SUFFIX,stats.g.doubleclick.net",
    "DOMAIN-SUFFIX,fls.doubleclick.net",
    "DOMAIN-SUFFIX,s0.2mdn.net",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,googletagmanager.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,googleadapis.l.google.com",
    "DOMAIN-SUFFIX,admob.com",
    "DOMAIN-SUFFIX,app-measurement.com",
}

CURATED_ENHANCED_RULES = CURATED_SAFE_RULES | {
    "DOMAIN-KEYWORD,doubleclick",
    "DOMAIN-KEYWORD,googlesyndication",
    "DOMAIN-KEYWORD,googleadservices",
    "DOMAIN-KEYWORD,pagead",
    "DOMAIN-KEYWORD,adservice",
    "DOMAIN-KEYWORD,googleads",
}

CURATED_AGGRESSIVE_RULES = CURATED_ENHANCED_RULES | {
    "DOMAIN-KEYWORD,adserver",
    "DOMAIN-KEYWORD,admob",
    "DOMAIN-KEYWORD,adsystem",
    "DOMAIN-KEYWORD,adclick",
    "DOMAIN-KEYWORD,adtraffic",
    "DOMAIN-KEYWORD,tracking",
}

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
HOSTS_RE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+([^\s#]+)", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_domain(value: str) -> str | None:
    value = (value or "").strip().lower()
    value = value.replace("\ufeff", "")
    value = value.strip(" .|^/*\t\r\n")
    if not value:
        return None
    if "://" in value:
        try:
            value = urlparse(value).hostname or ""
        except Exception:
            value = ""
    if "/" in value:
        value = value.split("/", 1)[0]
    if ":" in value:
        value = value.split(":", 1)[0]
    value = value.strip(" .")
    if not value or "*" in value or "$" in value or "(" in value or ")" in value:
        return None
    if DOMAIN_RE.match(value):
        return value
    return None


def is_protected_domain(domain: str) -> bool:
    domain = (domain or "").strip().lower().strip(".")
    if not domain:
        return True
    if domain in PROTECTED_EXACT:
        return True
    for suffix in PROTECTED_SUFFIX:
        if domain == suffix or domain.endswith("." + suffix):
            return True
    return False


def adblock_line_to_domains(line: str) -> set[str]:
    """Extract domains from common AdBlock/hosts/list formats.

    Supports:
    - ||domain^
    - 0.0.0.0 domain
    - 127.0.0.1 domain
    - http(s)://domain/path
    - plain domain
    Path-only YouTube rules are intentionally ignored because rule-provider
    classical matching is domain-based here.
    """
    original = (line or "").strip()
    if not original:
        return set()
    if original.startswith(("!", "#", "[", "@@")):
        return set()
    if "##" in original or "#@#" in original or "#$#" in original:
        return set()

    # Remove inline comments where safe.
    line = original.split(" #", 1)[0].strip()
    line = line.split("\t#", 1)[0].strip()

    hosts_match = HOSTS_RE.match(line)
    if hosts_match:
        domain = normalize_domain(hosts_match.group(1))
        return {domain} if domain else set()

    domains: set[str] = set()

    # ABP syntax: ||example.com^$third-party
    if line.startswith("||"):
        body = line[2:]
        body = body.split("$", 1)[0]
        body = re.split(r"[\^/*]", body, maxsplit=1)[0]
        domain = normalize_domain(body)
        if domain:
            domains.add(domain)
        return domains

    # URL syntax.
    if line.startswith(("http://", "https://", "|http://", "|https://")):
        line = line.lstrip("|")
        domain = normalize_domain(line)
        if domain:
            domains.add(domain)
        return domains

    # Plain domain.
    domain = normalize_domain(line)
    if domain:
        domains.add(domain)

    return domains


def safe_rule_from_domain(domain: str) -> str | None:
    domain = normalize_domain(domain) or ""
    if not domain or is_protected_domain(domain):
        return None
    return f"DOMAIN-SUFFIX,{domain}"


def fetch_text(url: str, timeout: int = 30) -> tuple[str, str | None]:
    if not requests:
        return "", "requests not installed"
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "SumberYAML/YouTubeAdsAdvanced"})
        response.raise_for_status()
        return response.text, None
    except Exception as exc:
        return "", str(exc)


def rules_from_sources(sources: Iterable[str]) -> tuple[set[str], list[dict]]:
    rules: set[str] = set()
    source_reports: list[dict] = []
    for url in sources:
        text, error = fetch_text(url)
        before = len(rules)
        if text:
            for line in text.splitlines():
                for domain in adblock_line_to_domains(line):
                    rule = safe_rule_from_domain(domain)
                    if rule:
                        rules.add(rule)
        source_reports.append(
            {
                "url": url,
                "ok": not bool(error),
                "error": error or "",
                "rules_added": len(rules) - before,
            }
        )
    return rules, source_reports


def curated_rules_for_mode(mode: str) -> set[str]:
    mode = (mode or "enhanced").strip().lower()
    if mode == "safe":
        return set(CURATED_SAFE_RULES)
    if mode == "aggressive":
        return set(CURATED_AGGRESSIVE_RULES)
    return set(CURATED_ENHANCED_RULES)


def sort_rules(rules: Iterable[str]) -> list[str]:
    def key(rule: str):
        parts = rule.split(",", 1)
        kind = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        order = {"DOMAIN": 0, "DOMAIN-SUFFIX": 1, "DOMAIN-KEYWORD": 2}.get(kind, 9)
        return (order, value)

    clean = []
    for rule in rules:
        if "," not in rule:
            continue
        kind, value = rule.split(",", 1)
        value = value.strip().lower()
        if kind in {"DOMAIN", "DOMAIN-SUFFIX"} and is_protected_domain(value):
            continue
        clean.append(f"{kind},{value}")
    return sorted(set(clean), key=key)


def write_provider(path: Path, rules: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"payload": rules}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def provider_url(repo: str, branch: str, provider_file: str, url_source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip()
    branch = (branch or "main").strip()
    provider_file = provider_file.strip("/")
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{provider_file}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{provider_file}"


def provider_entry(repo: str, branch: str, url_source: str) -> dict:
    return {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": "./rule_provider/youtube-ads.yaml",
        "url": provider_url(repo, branch, "output/RuleProviders/youtube-ads.yaml", url_source),
        "interval": 86400,
    }


def ensure_rule_in_yaml(path: Path, repo: str, branch: str, url_source: str) -> dict:
    if not path.exists():
        return {"file": str(path), "ok": False, "reason": "missing"}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {"file": str(path), "ok": False, "reason": f"parse error: {exc}"}
    if not isinstance(data, dict):
        return {"file": str(path), "ok": False, "reason": "not a yaml object"}

    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
    providers["youtube-ads"] = provider_entry(repo, branch, url_source)
    data["rule-providers"] = providers

    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
    # Remove duplicate / old YouTube provider references.
    clean_rules = []
    for item in rules:
        item_text = str(item).strip()
        if item_text.startswith("RULE-SET,youtube-ads,"):
            continue
        if item_text.startswith("RULE-SET,youtube-ads-advanced,"):
            continue
        if item_text.startswith("RULE-SET,goodbyeads-youtube,"):
            continue
        clean_rules.append(item)

    youtube_rule = "RULE-SET,youtube-ads,REJECT"
    # Put after local/direct rules when possible, but before generic ad/security rules and MATCH.
    insert_at = 0
    for idx, item in enumerate(clean_rules):
        item_text = str(item)
        if item_text.startswith("MATCH,"):
            insert_at = idx
            break
        if item_text.startswith("RULE-SET,"):
            insert_at = idx
            break
        insert_at = idx + 1
    clean_rules.insert(insert_at, youtube_rule)
    data["rules"] = clean_rules

    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"file": str(path), "ok": True, "rule_inserted": youtube_rule, "providers": ["youtube-ads"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply advanced YouTube ads rule-provider")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--mode", choices=["safe", "enhanced", "aggressive"], default=os.getenv("YOUTUBE_ADS_MODE", "enhanced"))
    parser.add_argument("--source", action="append", default=[], help="Extra AdBlock/hosts source URL")
    parser.add_argument("--max-rules", type=int, default=int(os.getenv("YOUTUBE_ADS_MAX_RULES", "5000")))
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / "output"
    provider_dir = output_dir / "RuleProviders"
    validation_dir = output_dir / "Validation"
    provider_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    sources = [GOODBYEADS_YOUTUBE_URL]
    sources.extend([item for item in args.source if item])
    extra_env = os.getenv("YOUTUBE_ADS_EXTRA_SOURCES", "").strip()
    if extra_env:
        sources.extend([item.strip() for item in extra_env.split(",") if item.strip()])

    fetched_rules, source_reports = rules_from_sources(sources)
    curated = curated_rules_for_mode(args.mode)
    all_rules = sort_rules(fetched_rules | curated)
    if args.max_rules > 0:
        all_rules = all_rules[: args.max_rules]

    write_provider(provider_dir / "youtube-ads.yaml", all_rules)
    write_provider(provider_dir / "youtube-ads-advanced.yaml", all_rules)
    # Also keep old compatibility name if previous workflow expects it.
    write_provider(provider_dir / "goodbyeads-youtube.yaml", all_rules)

    yaml_reports = []
    for rel in YAML_OUTPUTS:
        yaml_reports.append(ensure_rule_in_yaml(root / rel, args.repo, args.branch, args.url_source))

    summary = {
        "ok": True,
        "generated_at": now_iso(),
        "mode": args.mode,
        "url_source": args.url_source,
        "rule_count": len(all_rules),
        "protected_domains": sorted(PROTECTED_EXACT | PROTECTED_SUFFIX),
        "sources": source_reports,
        "provider_files": [
            "output/RuleProviders/youtube-ads.yaml",
            "output/RuleProviders/youtube-ads-advanced.yaml",
            "output/RuleProviders/goodbyeads-youtube.yaml",
        ],
        "yaml_reports": yaml_reports,
        "note": (
            "Domain-level blocking cannot guarantee 100% YouTube ad removal. "
            "Core YouTube video/CDN domains are protected to avoid breaking playback."
        ),
    }
    (validation_dir / "summary_youtube_ads_advanced_provider.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

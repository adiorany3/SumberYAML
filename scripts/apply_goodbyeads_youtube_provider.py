#!/usr/bin/env python3
"""Integrate GoodbyeAds YouTube filter as an OpenClash/Mihomo rule-provider.

This script:
1. Downloads GoodbyeAds YouTube AdBlock filter.
2. Converts common Adblock syntax to Mihomo/Clash classical rules.
3. Writes output/RuleProviders/youtube-ads.yaml and goodbyeads-youtube.yaml.
4. Ensures final YAML files contain the rule-provider and RULE-SET entries.

Manual/trusted accounts from input.txt or input/links.txt are not parsed, filtered,
quarantined, modified, or removed by this script.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

DEFAULT_SOURCE_URL = "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Formats/GoodbyeAds-YouTube-AdBlock-Filter.txt"
DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"

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

# Domains that should not be blocked as a whole because doing so can break video playback/login/API.
PROTECTED_EXACT = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtubei.googleapis.com",
    "ytimg.com",
    "i.ytimg.com",
    "s.ytimg.com",
    "googlevideo.com",
    "gstatic.com",
    "googleapis.com",
    "google.com",
    "accounts.google.com",
    "android.clients.google.com",
}

PROTECTED_SUFFIX = {
    ".googlevideo.com",
    ".ytimg.com",
    ".youtube.com",
    ".youtube-nocookie.com",
    ".googleapis.com",
    ".gstatic.com",
}

# Small safe fallback if remote cannot be downloaded.
FALLBACK_CLASSICAL_RULES = [
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,ads.youtube.com",
    "DOMAIN-SUFFIX,static.doubleclick.net",
    "DOMAIN-SUFFIX,securepubads.g.doubleclick.net",
    "DOMAIN-SUFFIX,googleads.g.doubleclick.net",
    "DOMAIN-SUFFIX,video-stats.video.google.com",
    "DOMAIN-SUFFIX,manifest.googlevideo.com",
    "DOMAIN-KEYWORD,pagead",
    "DOMAIN-KEYWORD,doubleclick",
    "DOMAIN-KEYWORD,googleads",
]

DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,63}\.?$")
HOST_CHARS_RE = re.compile(r"[^a-zA-Z0-9._:-]")


def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.strip(". ")
    value = value.replace("*.", "")
    if ":" in value and not value.startswith("["):
        value = value.split(":", 1)[0]
    value = value.strip(".")
    return value


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except Exception:
        return False


def is_protected_domain(domain: str) -> bool:
    d = normalize_domain(domain)
    if not d:
        return True
    if d in PROTECTED_EXACT:
        return True
    for suffix in PROTECTED_SUFFIX:
        if d.endswith(suffix):
            # allow known ad-specific hosts under google/youtube if explicit
            if any(key in d for key in ["ad", "ads", "doubleclick", "pagead", "stats", "tracking"]):
                return False
            return True
    return False


def valid_domain(domain: str) -> bool:
    d = normalize_domain(domain)
    if not d or len(d) > 253:
        return False
    if is_ip(d):
        return False
    if not DOMAIN_RE.match(d):
        return False
    if is_protected_domain(d):
        return False
    return True


def rule_from_domain(domain: str, prefer_suffix: bool = True) -> Optional[str]:
    d = normalize_domain(domain)
    if not valid_domain(d):
        return None
    rule_type = "DOMAIN-SUFFIX" if prefer_suffix else "DOMAIN"
    return f"{rule_type},{d}"


def host_from_url(text: str) -> Optional[str]:
    candidate = text.strip()
    if candidate.startswith("|"):
        candidate = candidate.lstrip("|")
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
        host = parsed.hostname or ""
        return normalize_domain(host)
    except Exception:
        return None


def clean_adblock_line(line: str) -> str:
    line = line.strip().replace("\ufeff", "")
    if not line:
        return ""
    # Remove inline comments sometimes used by host lists.
    if " #" in line:
        line = line.split(" #", 1)[0].strip()
    return line


def parse_adblock_line(line: str) -> List[str]:
    """Convert a single adblock/hosts style line into 0..n Mihomo classical rules."""
    line = clean_adblock_line(line)
    if not line:
        return []
    if line.startswith(("!", "#", "[", "@@")):
        return []
    if "##" in line or "#@#" in line or "#$#" in line:
        return []  # cosmetic rule; not applicable to Clash/Mihomo
    if line.startswith("/") and line.endswith("/"):
        return []  # regex; too risky to convert

    # Drop adblock options after $, except the left-side matching pattern.
    if "$" in line:
        line = line.split("$", 1)[0].strip()
    if not line:
        return []

    # Hosts format: 0.0.0.0 domain.tld / 127.0.0.1 domain.tld
    parts = line.split()
    if len(parts) >= 2 and (parts[0] in {"0.0.0.0", "127.0.0.1", "::", "::1"} or is_ip(parts[0])):
        out = []
        for part in parts[1:]:
            rule = rule_from_domain(part)
            if rule:
                out.append(rule)
        return out

    # Adblock domain anchor: ||ads.example.com^
    if line.startswith("||"):
        body = line[2:]
        body = body.split("^", 1)[0]
        body = body.split("/", 1)[0]
        body = HOST_CHARS_RE.split(body, 1)[0]
        rule = rule_from_domain(body, prefer_suffix=True)
        return [rule] if rule else []

    # URL/prefix style: |https://ads.example.com/path or https://ads.example.com/path
    if line.startswith("|") or "://" in line:
        host = host_from_url(line)
        rule = rule_from_domain(host, prefer_suffix=True) if host else None
        return [rule] if rule else []

    # Wildcard pattern like *doubleclick* → keyword if safe and simple.
    if "*" in line:
        keyword = line.replace("*", "").replace("^", "").strip("./|")
        keyword = re.sub(r"[^a-zA-Z0-9_.-]", "", keyword).lower()
        if keyword and 4 <= len(keyword) <= 48 and any(k in keyword for k in ["ad", "ads", "track", "doubleclick", "pagead"]):
            return [f"DOMAIN-KEYWORD,{keyword}"]
        return []

    # Plain domain or domain/path
    plain = line.strip("|^")
    plain = plain.split("/", 1)[0]
    plain = plain.split("^", 1)[0]
    rule = rule_from_domain(plain, prefer_suffix=True)
    return [rule] if rule else []


def fetch_text(url: str, timeout: int = 30) -> Tuple[str, str, bool]:
    if not requests:
        return "", "requests not available", False
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "SumberYAML-RuleProvider/1.0"})
        if response.ok and response.text.strip():
            return response.text, f"HTTP {response.status_code}", True
        return "", f"HTTP {response.status_code}: {response.text[:200]}", False
    except Exception as exc:
        return "", str(exc), False


def build_rules(source_text: str, max_rules: int = 1500) -> List[str]:
    seen = set()
    rules: List[str] = []
    for raw_line in source_text.splitlines():
        for rule in parse_adblock_line(raw_line):
            if not rule or rule in seen:
                continue
            seen.add(rule)
            rules.append(rule)
            if len(rules) >= max_rules:
                return rules
    # Always add safe fallback rules to cover common Google ad/tracker hosts.
    for rule in FALLBACK_CLASSICAL_RULES:
        if rule not in seen:
            seen.add(rule)
            rules.append(rule)
    return rules


def write_provider(path: Path, rules: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"payload": rules}
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, default_flow_style=False)


def provider_url(repo: str, branch: str, provider_file: str, source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip()
    branch = (branch or "main").strip()
    provider_file = provider_file.strip("/")
    if source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{provider_file}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{provider_file}"


def ensure_rule_provider_in_yaml(path: Path, repo: str, branch: str, url_source: str) -> Dict[str, Any]:
    data = load_yaml(path)
    if not data:
        return {"file": str(path), "updated": False, "reason": "empty_or_invalid"}

    data.setdefault("rule-providers", {})
    rp = data["rule-providers"]
    if not isinstance(rp, dict):
        rp = {}
        data["rule-providers"] = rp

    rp["youtube-ads"] = {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": "./rule_provider/youtube-ads.yaml",
        "url": provider_url(repo, branch, "output/RuleProviders/youtube-ads.yaml", url_source),
        "interval": 86400,
    }
    rp["goodbyeads-youtube"] = {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": "./rule_provider/goodbyeads-youtube.yaml",
        "url": provider_url(repo, branch, "output/RuleProviders/goodbyeads-youtube.yaml", url_source),
        "interval": 86400,
    }

    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []

    desired = ["RULE-SET,youtube-ads,REJECT", "RULE-SET,goodbyeads-youtube,REJECT"]
    filtered = [r for r in rules if r not in desired]

    # Put adblock after LAN/DNS direct rules but before proxy MATCH/general rules.
    insert_idx = 0
    for idx, rule in enumerate(filtered):
        text = str(rule)
        if (
            ",DIRECT" in text
            or text.startswith("DOMAIN-SUFFIX,local,")
            or text.startswith("IP-CIDR,127.")
            or text.startswith("DST-PORT,53,")
        ):
            insert_idx = idx + 1
    data["rules"] = filtered[:insert_idx] + desired + filtered[insert_idx:]

    # Ensure a REJECT policy is accepted by OpenClash/Mihomo. No special proxy group needed.
    save_yaml(path, data)
    return {"file": str(path), "updated": True, "providers": ["youtube-ads", "goodbyeads-youtube"]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Integrate GoodbyeAds YouTube AdBlock Filter into OpenClash rule-providers")
    parser.add_argument("--source-url", default=os.getenv("GOODBYEADS_YOUTUBE_URL", DEFAULT_SOURCE_URL))
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", os.getenv("GITHUB_REF", "main")).replace("refs/heads/", ""))
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--max-rules", type=int, default=1500)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    provider_dir = root / "output" / "RuleProviders"
    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    text, fetch_message, fetched = fetch_text(args.source_url)
    if not fetched:
        text = "\n".join(FALLBACK_CLASSICAL_RULES)

    rules = build_rules(text, max_rules=max(1, args.max_rules))
    if not rules:
        rules = FALLBACK_CLASSICAL_RULES[:]

    youtube_path = provider_dir / "youtube-ads.yaml"
    goodbye_path = provider_dir / "goodbyeads-youtube.yaml"
    write_provider(youtube_path, rules)
    write_provider(goodbye_path, rules)

    updated_files = []
    for rel in YAML_TARGETS:
        path = root / rel
        if path.exists():
            updated_files.append(ensure_rule_provider_in_yaml(path, args.repo, args.branch, args.url_source))

    summary = {
        "ok": True,
        "source_url": args.source_url,
        "source_fetched": fetched,
        "fetch_message": fetch_message,
        "rule_count": len(rules),
        "provider_files": [str(youtube_path.relative_to(root)), str(goodbye_path.relative_to(root))],
        "updated_yaml_files": updated_files,
        "protected_domains_enabled": True,
        "note": "Converted common Adblock filter patterns to Mihomo classical rule-provider rules. Trusted input.txt/input/links.txt accounts are not modified.",
    }
    with (validation_dir / "summary_goodbyeads_youtube_provider.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

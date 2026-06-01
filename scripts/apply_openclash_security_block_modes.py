#!/usr/bin/env python3
"""Build and inject security/adblock rule-providers for OpenClash/Mihomo.

Modes:
- light: malware/adware only.
- standard: malware/adware + general ads + Indonesia ads + Android ads.
- aggressive: standard + YouTube ads + game block.

The script is intentionally defensive: external lists are best-effort, local
seed rules are always included, and protected core domains are removed from
block providers to reduce false positives.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple
from urllib.parse import urlparse

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

ROOT = Path.cwd()
OUTPUT_DIR = ROOT / "output"
PROVIDER_DIR = OUTPUT_DIR / "RuleProviders"
VALIDATION_DIR = OUTPUT_DIR / "Validation"

DEFAULT_YAML_FILES = [
    "openclash-ready.yaml",
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
]

PROVIDER_NAMES_BY_MODE = {
    "light": ["malware-adware"],
    "standard": ["malware-adware", "general-ads", "indonesia-ads", "android-ads"],
    "aggressive": [
        "malware-adware",
        "general-ads",
        "indonesia-ads",
        "android-ads",
        "youtube-ads",
        "game-block",
    ],
}

PROTECTED_DOMAINS = {
    # Google / Android / YouTube core needed by many apps.
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtubei.googleapis.com",
    "googlevideo.com",
    "ytimg.com",
    "ggpht.com",
    "googleapis.com",
    "gstatic.com",
    "google.com",
    "accounts.google.com",
    "play.google.com",
    "android.clients.google.com",
    "firebaseinstallations.googleapis.com",
    "firebase-settings.crashlytics.com",
    # Messaging / login / infrastructure.
    "whatsapp.com",
    "whatsapp.net",
    "telegram.org",
    "t.me",
    "github.com",
    "raw.githubusercontent.com",
    "cdn.jsdelivr.net",
    "cloudflare.com",
    "cloudflare-dns.com",
    "microsoft.com",
    "office.com",
    "live.com",
    "windows.net",
    "apple.com",
    "icloud.com",
}


SEED_RULES: Dict[str, Set[str]] = {
    "indonesia-ads": {
        "iklanbaris.co.id", "ads.id", "adplus.co.id", "adskom.com", "ads.kaskus.co.id",
        "adstars.co.id", "genieesspv.jp", "revive-adserver.net", "clickmedia.co.id",
        "mgid.com", "popcash.net", "popads.net", "propellerads.com", "adsterra.com",
        "trafficstars.com", "onclickads.net", "adnetworkperformance.com",
    },
    "general-ads": {
        "doubleclick.net", "googleadservices.com", "googlesyndication.com", "adservice.google.com",
        "adsystem.com", "adnxs.com", "taboola.com", "outbrain.com", "criteo.com",
        "pubmatic.com", "openx.net", "rubiconproject.com", "scorecardresearch.com",
        "moatads.com", "adsrvr.org", "quantserve.com", "casalemedia.com", "yieldmo.com",
        "amazon-adsystem.com", "adform.net", "smartadserver.com", "zedo.com",
    },
    "android-ads": {
        "app-measurement.com", "adjust.com", "appsflyer.com", "branch.io", "kochava.com",
        "tapjoy.com", "unityads.unity3d.com", "supersonicads.com", "ironsrc.com",
        "applovin.com", "applvn.com", "chartboost.com", "inmobi.com", "vungle.com",
        "adcolony.com", "startappservice.com", "startapp.com", "mopub.com", "smaato.net",
        "mobileapptracking.com", "adsafeprotected.com", "tns-counter.ru", "onesignal.com",
    },
    "malware-adware": {
        "malwaredomainlist.com", "phishing.com", "cryptoloot.pro", "coinhive.com", "coin-hive.com",
        "crypto-loot.com", "adf.ly", "shorte.st", "bc.vc", "ouo.io", "linkvertise.com",
        "filecrypt.cc", "browsermine.com", "authedmine.com", "jscoinminer.com", "miner.pr0gramm.com",
    },
    "youtube-ads": {
        "ads.youtube.com", "pagead2.googlesyndication.com", "googleads.g.doubleclick.net",
        "static.doubleclick.net", "youtube-nocookie.com", "s.youtube.com",
    },
    "game-block": {
        "steampowered.com", "steamcommunity.com", "steamstatic.com", "steamcdn-a.akamaihd.net",
        "epicgames.com", "unrealengine.com", "fortnite.com", "riotgames.com", "valorant.com",
        "leagueoflegends.com", "garena.com", "freefiremobile.com", "pubgmobile.com", "pubg.com",
        "roblox.com", "rbxcdn.com", "minecraft.net", "mojang.com", "nintendo.com", "playstation.com",
        "xboxlive.com", "xbox.com", "ea.com", "ubisoft.com", "rockstargames.com", "battle.net",
        "blizzard.com", "hoyoverse.com", "mihoyo.com", "genshinimpact.com", "honkaiimpact3.com",
        "mobilelegends.com", "moonton.com", "poki.com", "crazygames.com", "y8.com", "miniclip.com",
        "kongregate.com", "armorgames.com", "newgrounds.com",
    },
}

SOURCE_URLS: Dict[str, List[str]] = {
    "indonesia-ads": [
        "https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/abpindo.txt",
        "https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/abpindo_noelemhide.txt",
    ],
    "general-ads": [
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Hosts/GoodbyeAds.txt",
    ],
    "android-ads": [
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Hosts/GoodbyeAds.txt",
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Hosts/GoodbyeAds-Android-AdBlock.txt",
    ],
    "malware-adware": [
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/tif.txt",
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/multi.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/fakenews-gambling-porn/hosts",
    ],
    "youtube-ads": [
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Formats/GoodbyeAds-YouTube-AdBlock-Filter.txt",
    ],
}

# Prevent too-large providers on small routers. These values can be overridden.
DEFAULT_LIMITS = {
    "indonesia-ads": 3500,
    "general-ads": 7000,
    "android-ads": 5000,
    "malware-adware": 10000,
    "youtube-ads": 3000,
    "game-block": 2500,
}

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9_\-]{1,63}\.)+[a-z]{2,63}$", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_domain(value: str) -> str | None:
    value = (value or "").strip().lower()
    if not value:
        return None

    value = value.strip(". ")
    value = value.replace("\ufeff", "")

    # Adblock format: ||example.com^
    if value.startswith("||"):
        value = value[2:]
    if value.startswith("|"):
        value = value.lstrip("|")
    value = value.split("$", 1)[0]
    value = value.split("^", 1)[0]
    value = value.split("/", 1)[0]
    value = value.strip("*.@|^/ ")

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        value = parsed.hostname or ""

    # Hosts file format: 0.0.0.0 domain or 127.0.0.1 domain
    parts = value.split()
    if len(parts) >= 2 and re.match(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)$", parts[0]):
        value = parts[1]

    # Clash/Mihomo rule format.
    if value.startswith("domain-suffix,"):
        value = value.split(",", 1)[1]
    elif value.startswith("domain,"):
        value = value.split(",", 1)[1]

    value = value.strip(". ")
    if not value or value in {"localhost", "local"}:
        return None
    if "*" in value or "~" in value or ":" in value or "[" in value or "]" in value:
        return None
    if not DOMAIN_RE.match(value):
        return None
    return value


def is_protected(domain: str) -> bool:
    d = domain.lower().strip(".")
    for protected in PROTECTED_DOMAINS:
        protected = protected.lower()
        if d == protected or d.endswith("." + protected):
            return True
    return False


def fetch_text(url: str, timeout: int = 25) -> Tuple[str, str | None]:
    if requests is None:
        return "", "requests not installed"
    try:
        res = requests.get(url, timeout=timeout, headers={"User-Agent": "SumberYAML-RuleProvider/1.0"})
        if not res.ok:
            return "", f"HTTP {res.status_code}"
        return res.text, None
    except Exception as exc:
        return "", str(exc)


def parse_domains_from_text(text: str) -> Set[str]:
    domains: Set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("!", "#", "[", "@@")):
            continue
        # Filter cosmetic/scriptlet rules.
        if "##" in line or "#@#" in line or "#$#" in line or "##+js" in line:
            continue
        # Sometimes adblock has multiple domains before ## or options.
        if line.startswith("||") or line.startswith("|") or line.startswith("DOMAIN") or re.match(r"^(?:0\.0\.0\.0|127\.0\.0\.1|::1)\s+", line):
            domain = clean_domain(line)
            if domain:
                domains.add(domain)
            continue
        # Plain host line.
        domain = clean_domain(line)
        if domain:
            domains.add(domain)
    return domains


def collect_provider_domains(provider_name: str, limit: int) -> Tuple[List[str], List[dict]]:
    domains: Set[str] = set(SEED_RULES.get(provider_name, set()))
    sources: List[dict] = []
    for url in SOURCE_URLS.get(provider_name, []):
        text, error = fetch_text(url)
        count_before = len(domains)
        if text:
            domains.update(parse_domains_from_text(text))
        sources.append({
            "url": url,
            "ok": error is None and bool(text),
            "error": error,
            "added": max(0, len(domains) - count_before),
        })

    # Remove protected/core service domains.
    domains = {d for d in domains if not is_protected(d)}
    # Remove duplicate child domains when parent already exists can be risky for false positives;
    # keep explicit rules but cap total size deterministically.
    ordered = sorted(domains)
    if limit and len(ordered) > limit:
        ordered = ordered[:limit]
    return ordered, sources


def domain_rules(domains: Sequence[str]) -> List[str]:
    return [f"DOMAIN-SUFFIX,{domain}" for domain in sorted(set(domains))]


def write_provider(name: str, rules: Sequence[str]) -> dict:
    PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    path = PROVIDER_DIR / f"{name}.yaml"
    payload = {"payload": list(dict.fromkeys(rules))}
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False, width=120)
    return {"name": name, "path": str(path), "rule_count": len(payload["payload"])}


def make_provider_url(repo: str, branch: str, provider_name: str, url_source: str) -> str:
    clean_repo = repo.strip().strip("/")
    clean_branch = branch.strip() or "main"
    path = f"output/RuleProviders/{provider_name}.yaml"
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{clean_repo}@{clean_branch}/{path}"
    return f"https://raw.githubusercontent.com/{clean_repo}/{clean_branch}/{path}"


def ensure_rule_providers(data: dict, provider_names: Sequence[str], repo: str, branch: str, url_source: str) -> None:
    providers = data.setdefault("rule-providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers

    for name in provider_names:
        providers[name] = {
            "type": "http",
            "behavior": "classical",
            "format": "yaml",
            "path": f"./rule_provider/{name}.yaml",
            "url": make_provider_url(repo, branch, name, url_source),
            "interval": 86400,
        }


def desired_rule_lines(provider_names: Sequence[str]) -> List[str]:
    return [f"RULE-SET,{name},REJECT" for name in provider_names]


def is_provider_rule(rule: str, provider_names: Sequence[str]) -> bool:
    if not isinstance(rule, str):
        return False
    for name in provider_names:
        if rule.startswith(f"RULE-SET,{name},"):
            return True
    # Remove legacy provider rules managed by this family too.
    managed = {
        "youtube-ads", "general-ads", "indonesia-ads", "android-ads",
        "malware-adware", "game-block", "goodbyeads-youtube"
    }
    return any(rule.startswith(f"RULE-SET,{name},") for name in managed)


def inject_rules(data: dict, provider_names: Sequence[str]) -> None:
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
    rules = [r for r in rules if not is_provider_rule(str(r), provider_names)]
    inserts = desired_rule_lines(provider_names)

    # Prefer after local/DNS direct rules, but always before MATCH.
    match_idx = next((i for i, r in enumerate(rules) if isinstance(r, str) and r.startswith("MATCH,")), len(rules))
    insert_idx = match_idx
    for i, r in enumerate(rules[:match_idx]):
        if not isinstance(r, str):
            continue
        upper = r.upper()
        if any(token in upper for token in ["DOMAIN-SUFFIX,LOCAL", "IP-CIDR,10.", "IP-CIDR,192.168", "DST-PORT,53"]):
            insert_idx = i + 1
    rules = rules[:insert_idx] + inserts + rules[insert_idx:]
    data["rules"] = rules


def apply_to_yaml_file(path: Path, provider_names: Sequence[str], repo: str, branch: str, url_source: str) -> dict:
    if not path.exists():
        return {"file": str(path), "exists": False, "changed": False}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {"file": str(path), "exists": True, "changed": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"file": str(path), "exists": True, "changed": False, "error": "YAML root is not object"}

    before = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    ensure_rule_providers(data, provider_names, repo, branch, url_source)
    inject_rules(data, provider_names)
    after = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    changed = before != after
    if changed:
        path.write_text(after, encoding="utf-8")
    return {
        "file": str(path),
        "exists": True,
        "changed": changed,
        "rule_providers": provider_names,
        "rule_count": len(data.get("rules", [])) if isinstance(data.get("rules"), list) else None,
    }


def validate_providers(provider_names: Sequence[str]) -> dict:
    result = {
        "ok": True,
        "providers": {},
        "protected_hits": [],
        "empty": [],
    }
    for name in provider_names:
        path = PROVIDER_DIR / f"{name}.yaml"
        item = {"path": str(path), "exists": path.exists(), "payload_count": 0, "duplicate_count": 0}
        if not path.exists():
            result["ok"] = False
            item["error"] = "missing"
            result["providers"][name] = item
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            payload = data.get("payload", []) if isinstance(data, dict) else []
            payload = payload if isinstance(payload, list) else []
            item["payload_count"] = len(payload)
            item["duplicate_count"] = len(payload) - len(set(payload))
            if not payload:
                result["ok"] = False
                result["empty"].append(name)
            for rule in payload:
                if not isinstance(rule, str):
                    continue
                if rule.startswith("DOMAIN-SUFFIX,"):
                    domain = rule.split(",", 1)[1]
                    if is_protected(domain):
                        result["protected_hits"].append({"provider": name, "domain": domain})
        except Exception as exc:
            result["ok"] = False
            item["error"] = str(exc)
        result["providers"][name] = item
    if result["protected_hits"]:
        result["ok"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["light", "standard", "aggressive"], default="standard")
    parser.add_argument("--repo", default="adiorany3/SumberYAML")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--yaml-file", action="append", dest="yaml_files", default=[])
    parser.add_argument("--max-general", type=int, default=DEFAULT_LIMITS["general-ads"])
    parser.add_argument("--max-indonesia", type=int, default=DEFAULT_LIMITS["indonesia-ads"])
    parser.add_argument("--max-android", type=int, default=DEFAULT_LIMITS["android-ads"])
    parser.add_argument("--max-malware", type=int, default=DEFAULT_LIMITS["malware-adware"])
    parser.add_argument("--max-youtube", type=int, default=DEFAULT_LIMITS["youtube-ads"])
    parser.add_argument("--max-game", type=int, default=DEFAULT_LIMITS["game-block"])
    args = parser.parse_args(argv)

    PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    provider_names = PROVIDER_NAMES_BY_MODE[args.mode]
    limits = {
        "general-ads": args.max_general,
        "indonesia-ads": args.max_indonesia,
        "android-ads": args.max_android,
        "malware-adware": args.max_malware,
        "youtube-ads": args.max_youtube,
        "game-block": args.max_game,
    }

    provider_reports = []
    source_reports = {}

    for name in provider_names:
        domains, sources = collect_provider_domains(name, limit=limits.get(name, 5000))
        rules = domain_rules(domains)
        provider_reports.append(write_provider(name, rules))
        source_reports[name] = sources

    yaml_files = args.yaml_files or DEFAULT_YAML_FILES
    yaml_reports = [
        apply_to_yaml_file(OUTPUT_DIR / file_name, provider_names, args.repo, args.branch, args.url_source)
        for file_name in yaml_files
    ]

    validation = validate_providers(provider_names)
    summary = {
        "ok": bool(validation.get("ok")),
        "generated_at": now_iso(),
        "mode": args.mode,
        "repo": args.repo,
        "branch": args.branch,
        "provider_names": provider_names,
        "providers": provider_reports,
        "sources": source_reports,
        "yaml_files": yaml_reports,
        "validation": validation,
        "note": "input.txt/input/links.txt accounts are not filtered or modified by this script.",
    }
    (VALIDATION_DIR / "summary_security_block_modes.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (VALIDATION_DIR / "summary_rule_provider_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

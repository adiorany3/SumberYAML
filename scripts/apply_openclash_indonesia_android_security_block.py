#!/usr/bin/env python3
"""Build and attach OpenClash/Mihomo rule-providers for:
- Indonesian ads
- Android in-app ads/adware/tracking SDKs
- malware/adware/phishing/threat domains
- general web ads

The script is intentionally defensive:
- It creates provider YAML files even if upstream sources are unreachable, using curated fallbacks.
- It attaches providers to every generated OpenClash YAML file found in output/.
- It does not touch proxy nodes or trusted manual accounts from input.txt/input/links.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
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
    raise SystemExit("PyYAML belum terpasang. Install dengan: pip install pyyaml") from exc

ROOT = Path.cwd()
OUTPUT_DIR = ROOT / "output"
RULE_PROVIDER_DIR = OUTPUT_DIR / "RuleProviders"
VALIDATION_DIR = OUTPUT_DIR / "Validation"

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

SOURCE_URLS = {
    "indonesia_ads": [
        "https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/domain.txt",
        "https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/hosts.txt",
    ],
    "android_ads": [
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Hosts/GoodbyeAds.txt",
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Extension/GoodbyeAds-Samsung-AdBlock.txt",
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Extension/GoodbyeAds-Xiaomi-Extension.txt",
    ],
    "malware_adware": [
        # Medium-size option would be ideal, but tif.txt is the stable documented raw path.
        # We cap entries via --max-malware to keep OpenClash/router memory safe.
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/tif.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    ],
    "general_ads": [
        "https://raw.githubusercontent.com/ABPindo/indonesianadblockrules/master/subscriptions/domain.txt",
        "https://raw.githubusercontent.com/jerryn70/GoodbyeAds/master/Hosts/GoodbyeAds.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    ],
}

# Domains that are too central; blocking them is likely to break apps/websites.
PROTECTED_EXACT = {
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    "youtube.com",
    "youtu.be",
    "youtubei.googleapis.com",
    "googlevideo.com",
    "ytimg.com",
    "android.com",
    "gvt1.com",
    "gvt2.com",
    "apple.com",
    "icloud.com",
    "whatsapp.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "tiktokcdn.com",
    "github.com",
    "githubusercontent.com",
    "raw.githubusercontent.com",
    "cdn.jsdelivr.net",
}

PROTECTED_SUFFIXES = (
    ".google.com",
    ".gstatic.com",
    ".googleapis.com",
    ".googleusercontent.com",
    ".youtube.com",
    ".googlevideo.com",
    ".ytimg.com",
    ".android.com",
    ".gvt1.com",
    ".gvt2.com",
    ".github.com",
    ".githubusercontent.com",
)

CURATED_INDONESIA_ADS = {
    "ads.telkomsel.com",
    "ads.indosatooredoo.com",
    "ibnads.xl.co.id",
    "adsimg.kompas.com",
    "adplus.co.id",
    "adstarsmedia.co.id",
    "digiads.co.id",
    "sitti.co.id",
    "adskom.com",
    "props.id",
    "jagoiklan.com",
    "iklanads.com",
    "pasangiklan.com",
    "trafficfactory.biz",
    "accesstrade.co.id",
    "tracker.lazada.co.id",
}

CURATED_ANDROID_ADS = {
    # Google/AdMob ad endpoints, not core Google domains.
    "admob.com",
    "ads.admob.com",
    "googleads.g.doubleclick.net",
    "pagead2.googlesyndication.com",
    "tpc.googlesyndication.com",
    "securepubads.g.doubleclick.net",
    "adservice.google.com",
    "adservice.google.co.id",
    # Android ad/analytics SDKs.
    "applovin.com",
    "applvn.com",
    "vungle.com",
    "vungle.akadns.net",
    "chartboost.com",
    "unityads.unity3d.com",
    "ads.prd.ie.internal.unity3d.com",
    "ironsrc.com",
    "supersonicads.com",
    "tapjoy.com",
    "inmobi.com",
    "inner-active.mobi",
    "fyber.com",
    "mopub.com",
    "ads.mopub.com",
    "startappservice.com",
    "startappexchange.com",
    "smaato.net",
    "adcolony.com",
    "mydas.mobi",
    "flurry.com",
    "adjust.com",
    "appsflyer.com",
    "branch.io",
    "kochava.com",
    "tenjin.io",
    "singular.net",
    "crashlytics.com",
    "app-measurement.com",
    "firebase-settings.crashlytics.com",
    "firebaseinstallations.googleapis.com",
    # OEM/app ecosystem ads.
    "samsungads.com",
    "samsungadhub.com",
    "samsungtvads.com",
    "log-config.samsungacr.com",
    "sdkconfig.ad.xiaomi.com",
    "api.ad.xiaomi.com",
    "data.mistat.xiaomi.com",
    "tracking.rus.miui.com",
    "adsfs.oppomobile.com",
    "adx.ads.oppomobile.com",
    "ads.heytapmobi.com",
    "adx.ads.heytapmobi.com",
    "ads.vivo.com.cn",
    "adnet.vivo.com.cn",
    "ads-drcn.platform.hicloud.com",
    "metrics.data.hicloud.com",
}

CURATED_MALWARE_ADWARE = {
    "malwaredomainlist.com",
    "malwaredomains.com",
    "phishing.army",
    "urlhaus.abuse.ch",
    "cryptojacking.dns","miner.pr0gramm.com",
}

CURATED_GENERAL_ADS = {
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adsystem.com",
    "adsrvr.org",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "pubmatic.com",
    "openx.net",
    "rubiconproject.com",
    "smartadserver.com",
    "adnxs.com",
    "yieldmo.com",
    "popads.net",
    "propellerads.com",
    "adsterra.com",
    "mgid.com",
    "quantserve.com",
    "scorecardresearch.com",
    "moatads.com",
    "hotjar.com",
}

PROVIDER_SPECS = OrderedDict([
    ("malware-adware", {
        "title": "Malware, phishing, scam, adware and threat domains",
        "source_key": "malware_adware",
        "curated": CURATED_MALWARE_ADWARE,
    }),
    ("android-ads", {
        "title": "Android in-app ads, adware and tracking SDK domains",
        "source_key": "android_ads",
        "curated": CURATED_ANDROID_ADS,
    }),
    ("indonesia-ads", {
        "title": "Indonesian ads and local ad networks",
        "source_key": "indonesia_ads",
        "curated": CURATED_INDONESIA_ADS,
    }),
    ("general-ads", {
        "title": "General internet ads and trackers",
        "source_key": "general_ads",
        "curated": CURATED_GENERAL_ADS,
    }),
])

DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,63}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_domain(raw: str) -> str | None:
    text = (raw or "").strip().lower()
    if not text:
        return None
    text = text.strip("'\"`[](){}<>")
    text = text.rstrip(".")
    if not text:
        return None
    if text.startswith("*."):
        text = text[2:]
    if text.startswith("."):
        text = text[1:]
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.hostname or ""
    if "/" in text:
        text = text.split("/", 1)[0]
    if ":" in text:
        text = text.split(":", 1)[0]
    text = text.strip().strip(".")
    if not text or len(text) > 253:
        return None
    if text in PROTECTED_EXACT or any(text.endswith(suf) for suf in PROTECTED_SUFFIXES):
        return None
    if not DOMAIN_RE.match(text):
        return None
    return text


def line_to_domains(line: str) -> list[str]:
    line = (line or "").strip()
    if not line or line.startswith(("#", "!", "[", "//")):
        return []
    # Strip inline comments for hosts-style entries.
    if " #" in line:
        line = line.split(" #", 1)[0].strip()

    results: list[str] = []

    # Adblock syntax: ||example.com^
    for match in re.finditer(r"\|\|([A-Za-z0-9_.-]+)\^?", line):
        domain = safe_domain(match.group(1))
        if domain:
            results.append(domain)

    # Hosts syntax may appear as repeated pairs in one line: 0.0.0.0 a.com 0.0.0.0 b.com
    tokens = re.split(r"\s+", line)
    for token in tokens:
        token = token.strip()
        if not token or token in {"0.0.0.0", "127.0.0.1", "::", "::1", "localhost"}:
            continue
        if token.startswith(("@@", "#$#", "##", "#@#")):
            continue
        # Remove common adblock modifiers after $.
        if "$" in token:
            token = token.split("$", 1)[0]
        token = token.strip("|").strip("^")
        domain = safe_domain(token)
        if domain:
            results.append(domain)

    return results


def fetch_text(url: str, timeout: int = 45) -> str:
    if requests is None:
        raise RuntimeError("requests belum terpasang")
    headers = {"User-Agent": "SumberYAML-rule-provider-builder/1.0"}
    response = requests.get(url, timeout=timeout, headers=headers)
    response.raise_for_status()
    return response.text


def domains_from_source(url: str, max_entries: int | None = None) -> tuple[set[str], str | None]:
    try:
        text = fetch_text(url)
    except Exception as exc:
        return set(), str(exc)
    domains: set[str] = set()
    # Some upstream files are one very long line; split on whitespace too.
    for piece in re.split(r"[\r\n]+", text):
        subpieces = [piece]
        if len(piece) > 1000:
            subpieces = re.split(r"\s+", piece)
        for item in subpieces:
            for domain in line_to_domains(item):
                domains.add(domain)
                if max_entries and len(domains) >= max_entries:
                    return domains, None
    return domains, None


def rule_payload(domains: Iterable[str]) -> list[str]:
    clean = sorted({d for d in domains if safe_domain(d)})
    return [f"DOMAIN-SUFFIX,{domain}" for domain in clean]


def write_provider(provider_name: str, domains: set[str]) -> Path:
    RULE_PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    path = RULE_PROVIDER_DIR / f"{provider_name}.yaml"
    payload = rule_payload(domains)
    data = {
        "payload": payload,
    }
    header = (
        f"# SumberYAML generated rule-provider: {provider_name}\n"
        f"# Generated at: {now_iso()}\n"
        f"# Format: Mihomo/OpenClash classical rule-provider\n"
        f"# Entries: {len(payload)}\n"
    )
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)
    return path


def load_yaml(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def dump_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)


def provider_url(repo: str, branch: str, provider_name: str, url_source: str) -> str:
    rel = f"output/RuleProviders/{provider_name}.yaml"
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/{rel}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


def ensure_rule_provider(data: dict, provider_name: str, repo: str, branch: str, url_source: str) -> None:
    providers = data.setdefault("rule-providers", {})
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers
    providers[provider_name] = {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": f"./rule_provider/{provider_name}.yaml",
        "url": provider_url(repo, branch, provider_name, url_source),
        "interval": 86400,
    }


def ensure_reject_rule(data: dict, provider_name: str) -> None:
    rule = f"RULE-SET,{provider_name},REJECT"
    rules = data.setdefault("rules", [])
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules
    rules = [r for r in rules if str(r).strip() != rule]
    # Insert after LAN/local direct rules, but before match/proxy/general routing.
    insert_at = 0
    for idx, item in enumerate(rules):
        text = str(item)
        if "DIRECT" in text and any(key in text for key in ["IP-CIDR", "DOMAIN-SUFFIX,local", "DOMAIN-SUFFIX,lan", "GEOIP,LAN"]):
            insert_at = idx + 1
            continue
        break
    rules.insert(insert_at, rule)
    data["rules"] = rules


def attach_to_yaml_files(repo: str, branch: str, url_source: str) -> dict:
    results = {}
    yaml_files = [Path(p) for p in DEFAULT_YAML_FILES]
    # Also include any top-level output YAML files.
    if OUTPUT_DIR.exists():
        for p in OUTPUT_DIR.glob("*.yaml"):
            if p not in yaml_files:
                yaml_files.append(p)
    for path in yaml_files:
        if not path.exists():
            results[str(path)] = {"exists": False, "updated": False}
            continue
        data = load_yaml(path)
        if data is None:
            results[str(path)] = {"exists": True, "updated": False, "error": "not a mapping or failed to parse"}
            continue
        for provider_name in PROVIDER_SPECS.keys():
            ensure_rule_provider(data, provider_name, repo, branch, url_source)
        # Put malware/security first, then ads.
        for provider_name in reversed(list(PROVIDER_SPECS.keys())):
            ensure_reject_rule(data, provider_name)
        dump_yaml(path, data)
        results[str(path)] = {"exists": True, "updated": True}
    return results


def build_providers(args: argparse.Namespace) -> dict:
    provider_summary: dict = {}
    max_by_key = {
        "indonesia_ads": args.max_indonesia,
        "android_ads": args.max_android,
        "malware_adware": args.max_malware,
        "general_ads": args.max_general,
    }
    for provider_name, spec in PROVIDER_SPECS.items():
        source_key = spec["source_key"]
        domains = set(spec["curated"])
        source_results = []
        per_source_limit = max_by_key.get(source_key)
        for url in SOURCE_URLS.get(source_key, []):
            found, error = domains_from_source(url, max_entries=per_source_limit)
            domains.update(found)
            source_results.append({"url": url, "count": len(found), "error": error})
            if per_source_limit and len(domains) >= per_source_limit:
                # keep curated + first source enough for router-safe provider
                domains = set(sorted(domains)[:per_source_limit]) | set(spec["curated"])
                break
        path = write_provider(provider_name, domains)
        provider_summary[provider_name] = {
            "title": spec["title"],
            "path": str(path),
            "domains": len(domains),
            "rules": len(rule_payload(domains)),
            "sources": source_results,
        }
    return provider_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Indonesia/Android/security adblock providers and attach them to OpenClash YAML.")
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "adiorany3/SumberYAML"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw")
    parser.add_argument("--max-indonesia", type=int, default=5000)
    parser.add_argument("--max-android", type=int, default=12000)
    parser.add_argument("--max-malware", type=int, default=50000)
    parser.add_argument("--max-general", type=int, default=25000)
    args = parser.parse_args(argv)

    RULE_PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    providers = build_providers(args)
    yaml_results = attach_to_yaml_files(args.repo, args.branch, args.url_source)

    summary = {
        "generated_at": now_iso(),
        "repo": args.repo,
        "branch": args.branch,
        "url_source": args.url_source,
        "providers": providers,
        "yaml_results": yaml_results,
        "notes": [
            "Manual trusted accounts from input.txt/input/links.txt are not filtered or touched by this script.",
            "Core domains such as youtube.com, googlevideo.com, googleapis.com, github.com and whatsapp.com are protected to reduce breakage.",
            "This is DNS/rule based blocking; it cannot guarantee 100% removal of all ads embedded through first-party domains.",
        ],
    }
    out = VALIDATION_DIR / "summary_indonesia_android_security_block.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

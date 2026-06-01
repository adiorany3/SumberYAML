#!/usr/bin/env python3
"""Force-create OpenClash/Mihomo rule-provider files.

This script intentionally does not touch input.txt or input/links.txt.
It only writes adblock provider payload files under output/RuleProviders.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

YOUTUBE_AD_RULES = [
    "DOMAIN,pagead2.googlesyndication.com",
    "DOMAIN,pagead-googlehosted.l.google.com",
    "DOMAIN,googleads.g.doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,adservice.google.co.id",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,googletagmanager.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,2mdn.net",
]

GENERAL_AD_RULES = [
    # Google / common web ads
    "DOMAIN,pagead2.googlesyndication.com",
    "DOMAIN,googleads.g.doubleclick.net",
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googletagservices.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,adnxs.com",
    "DOMAIN-SUFFIX,adsrvr.org",
    "DOMAIN-SUFFIX,adsafeprotected.com",
    "DOMAIN-SUFFIX,advertising.com",
    "DOMAIN-SUFFIX,adform.net",
    "DOMAIN-SUFFIX,adroll.com",
    "DOMAIN-SUFFIX,criteo.com",
    "DOMAIN-SUFFIX,criteo.net",
    "DOMAIN-SUFFIX,outbrain.com",
    "DOMAIN-SUFFIX,taboola.com",
    "DOMAIN-SUFFIX,scorecardresearch.com",
    "DOMAIN-SUFFIX,quantserve.com",
    "DOMAIN-SUFFIX,moatads.com",
    "DOMAIN-SUFFIX,openx.net",
    "DOMAIN-SUFFIX,pubmatic.com",
    "DOMAIN-SUFFIX,rubiconproject.com",
    "DOMAIN-SUFFIX,smartadserver.com",
    "DOMAIN-SUFFIX,spotxchange.com",
    "DOMAIN-SUFFIX,contextweb.com",
    "DOMAIN-SUFFIX,mathtag.com",
    "DOMAIN-SUFFIX,media.net",
    "DOMAIN-SUFFIX,mgid.com",
    "DOMAIN-SUFFIX,zedo.com",
    "DOMAIN-SUFFIX,revcontent.com",
    # Pop / redirect ads
    "DOMAIN-SUFFIX,popads.net",
    "DOMAIN-SUFFIX,popcash.net",
    "DOMAIN-SUFFIX,propellerads.com",
    "DOMAIN-SUFFIX,adsterra.com",
    "DOMAIN-SUFFIX,onclickads.net",
    "DOMAIN-SUFFIX,exoclick.com",
    # Mobile/common analytics ads
    "DOMAIN-SUFFIX,appsflyer.com",
    "DOMAIN-SUFFIX,adjust.com",
    "DOMAIN-SUFFIX,branch.io",
    "DOMAIN-SUFFIX,kochava.com",
    "DOMAIN-SUFFIX,unityads.unity3d.com",
    "DOMAIN-SUFFIX,applovin.com",
    "DOMAIN-SUFFIX,applvn.com",
    "DOMAIN-SUFFIX,vungle.com",
    "DOMAIN-SUFFIX,ironsrc.com",
]


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        item = str(item).strip()
        if not item or item.startswith("#"):
            continue
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def write_provider(path: Path, rules: list[str]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    rules = unique_keep_order(rules)
    lines = ["payload:"]
    for rule in rules:
        # Quote rules to avoid YAML parsing surprises with commas/colon-like content.
        safe = rule.replace('"', '\\"')
        lines.append(f'  - "{safe}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(path), "rule_count": len(rules)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    provider_dir = root / "output" / "RuleProviders"
    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    youtube = write_provider(provider_dir / "youtube-ads.yaml", YOUTUBE_AD_RULES)
    general = write_provider(provider_dir / "general-ads.yaml", GENERAL_AD_RULES)

    summary = {
        "ok": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": args.repo,
        "branch": args.branch,
        "providers": {
            "youtube-ads": youtube,
            "general-ads": general,
        },
        "note": "Provider files are generated locally under output/RuleProviders and do not filter trusted manual accounts.",
    }
    (validation_dir / "summary_rule_provider_files.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

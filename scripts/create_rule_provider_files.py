#!/usr/bin/env python3
"""Create adblock rule-provider files for OpenClash/Mihomo outputs.

This script is intentionally standalone and safe to run multiple times.
It only creates/updates output/RuleProviders/*.yaml and summary metadata.
It never reads, filters, or removes trusted manual accounts from input.txt or input/links.txt.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

YOUTUBE_RULES = [
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,google-analytics.com",
    "DOMAIN-SUFFIX,ads.youtube.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,video-stats.l.google.com",
    "DOMAIN-SUFFIX,s.youtube.com",
]

GENERAL_ADS_RULES = [
    "DOMAIN-SUFFIX,doubleclick.net",
    "DOMAIN-SUFFIX,googleadservices.com",
    "DOMAIN-SUFFIX,googlesyndication.com",
    "DOMAIN-SUFFIX,adservice.google.com",
    "DOMAIN-SUFFIX,pagead2.googlesyndication.com",
    "DOMAIN-SUFFIX,adsystem.com",
    "DOMAIN-SUFFIX,adnxs.com",
    "DOMAIN-SUFFIX,taboola.com",
    "DOMAIN-SUFFIX,outbrain.com",
    "DOMAIN-SUFFIX,criteo.com",
    "DOMAIN-SUFFIX,pubmatic.com",
    "DOMAIN-SUFFIX,openx.net",
    "DOMAIN-SUFFIX,rubiconproject.com",
    "DOMAIN-SUFFIX,scorecardresearch.com",
    "DOMAIN-SUFFIX,zedo.com",
    "DOMAIN-SUFFIX,adsrvr.org",
    "DOMAIN-SUFFIX,adform.net",
    "DOMAIN-SUFFIX,adroll.com",
    "DOMAIN-SUFFIX,smartadserver.com",
    "DOMAIN-SUFFIX,mgid.com",
    "DOMAIN-SUFFIX,popads.net",
    "DOMAIN-SUFFIX,propellerads.com",
    "DOMAIN-SUFFIX,adsterra.com",
    "DOMAIN-SUFFIX,inmobi.com",
    "DOMAIN-SUFFIX,unityads.unity3d.com",
    "DOMAIN-SUFFIX,applovin.com",
    "DOMAIN-SUFFIX,ironsrc.com",
]


def write_provider(path: Path, rules: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["payload:"]
    for rule in dict.fromkeys(rules):
        lines.append(f"  - {rule}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default="")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    provider_dir = root / "output" / "RuleProviders"
    validation_dir = root / "output" / "Validation"

    youtube_path = provider_dir / "youtube-ads.yaml"
    general_path = provider_dir / "general-ads.yaml"

    write_provider(youtube_path, YOUTUBE_RULES)
    write_provider(general_path, GENERAL_ADS_RULES)

    validation_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "ok": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": args.repo,
        "branch": args.branch,
        "files": [
            str(youtube_path.relative_to(root)),
            str(general_path.relative_to(root)),
        ],
        "rule_counts": {
            "youtube-ads": len(YOUTUBE_RULES),
            "general-ads": len(GENERAL_ADS_RULES),
        },
        "trusted_manual_accounts_note": "input.txt and input/links.txt are not filtered or modified by this script.",
    }
    (validation_dir / "summary_rule_provider_files.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

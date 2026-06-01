#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import yaml

PROTECTED_DOMAINS = {
    "youtube.com", "googlevideo.com", "ytimg.com", "googleapis.com", "gstatic.com",
    "whatsapp.com", "whatsapp.net", "telegram.org", "github.com", "raw.githubusercontent.com",
    "cdn.jsdelivr.net", "cloudflare.com", "microsoft.com", "play.google.com",
}


def is_protected(domain: str) -> bool:
    d = (domain or "").lower().strip(".")
    return any(d == p or d.endswith("." + p) for p in PROTECTED_DOMAINS)


def validate(provider_dir: Path) -> dict:
    summary = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider_dir": str(provider_dir),
        "files": [],
        "protected_hits": [],
    }
    if not provider_dir.exists():
        summary["ok"] = False
        summary["error"] = "provider directory does not exist"
        return summary

    for path in sorted(provider_dir.glob("*.yaml")):
        item = {"file": str(path), "payload_count": 0, "duplicate_count": 0, "ok": True}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            payload = data.get("payload", []) if isinstance(data, dict) else []
            if not isinstance(payload, list):
                payload = []
            item["payload_count"] = len(payload)
            item["duplicate_count"] = len(payload) - len(set(map(str, payload)))
            if len(payload) == 0:
                item["ok"] = False
                item["error"] = "empty payload"
                summary["ok"] = False
            for rule in payload:
                text = str(rule)
                if text.startswith("DOMAIN-SUFFIX,"):
                    domain = text.split(",", 1)[1]
                    if is_protected(domain):
                        hit = {"file": str(path), "domain": domain}
                        summary["protected_hits"].append(hit)
                        item.setdefault("protected_hits", []).append(domain)
                        item["ok"] = False
                        summary["ok"] = False
        except Exception as exc:
            item["ok"] = False
            item["error"] = str(exc)
            summary["ok"] = False
        summary["files"].append(item)
    if not summary["files"]:
        summary["ok"] = False
        summary["error"] = "no provider yaml files found"
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-dir", default="output/RuleProviders")
    parser.add_argument("--output", default="output/Validation/summary_rule_provider_validation.json")
    args = parser.parse_args(argv)
    summary = validate(Path(args.provider_dir))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

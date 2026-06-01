#!/usr/bin/env python3
"""Validate output size and performance constraints for SumberYAML."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:
    yaml = None

ROOT = Path.cwd()
OUT = ROOT / "output"
PERF = OUT / "Performance"


def size_kb(path: Path) -> float:
    return round(path.stat().st_size / 1024, 2) if path.exists() else 0.0


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def count_yaml_proxy_group(path: Path) -> tuple[int, int, int]:
    if not path.exists() or yaml is None:
        return (0, 0, 0)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        proxies = data.get("proxies") if isinstance(data, dict) else []
        groups = data.get("proxy-groups") if isinstance(data, dict) else []
        rules = data.get("rules") if isinstance(data, dict) else []
        return (
            len(proxies) if isinstance(proxies, list) else 0,
            len(groups) if isinstance(groups, list) else 0,
            len(rules) if isinstance(rules, list) else 0,
        )
    except Exception:
        return (0, 0, 0)


def count_singbox(path: Path) -> tuple[int, int, int]:
    data = read_json(path)
    outbounds = data.get("outbounds") if isinstance(data.get("outbounds"), list) else []
    groups = [o for o in outbounds if isinstance(o, dict) and o.get("type") in {"selector", "urltest"}]
    proxy_outs = [o for o in outbounds if isinstance(o, dict) and o.get("type") in {"vmess", "vless", "trojan", "shadowsocks", "hysteria2"}]
    rules = data.get("route", {}).get("rules", []) if isinstance(data.get("route"), dict) else []
    return (len(proxy_outs), len(groups), len(rules) if isinstance(rules, list) else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-openclash-kb", type=int, default=int(os.getenv("MAX_OPENCLASH_READY_KB", "4096")))
    ap.add_argument("--max-openclash-lite-kb", type=int, default=int(os.getenv("MAX_OPENCLASH_LITE_KB", "2048")))
    ap.add_argument("--max-singbox-kb", type=int, default=int(os.getenv("MAX_SINGBOX_PROFILE_KB", "1024")))
    ap.add_argument("--max-ruleproviders-kb", type=int, default=int(os.getenv("MAX_RULEPROVIDERS_TOTAL_KB", "8192")))
    ap.add_argument("--max-active-group-nodes", type=int, default=int(os.getenv("MAX_ACTIVE_GROUP_NODES", "40")))
    ap.add_argument("--fail-on-error", action="store_true", default=os.getenv("PERFORMANCE_FAIL_ON_ERROR", "false").lower() in {"1", "true", "yes"})
    args = ap.parse_args()

    PERF.mkdir(parents=True, exist_ok=True)
    files = {
        "openclash_ready": OUT / "openclash-ready.yaml",
        "openclash_lite": OUT / "openclash-lite-ready.yaml",
        "singbox_mobile": OUT / "SingBox/mobile-stable-safe.json",
        "singbox_performance_lite": OUT / "SingBox/performance-lite.json",
        "v2raybox_lite": OUT / "V2RayBox/performance-lite.txt",
        "nekobox_lite": OUT / "NekoBox/performance-lite.txt",
    }
    report: dict[str, Any] = {
        "ok": True,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "limits": vars(args),
        "files": {},
        "warnings": [],
        "errors": [],
    }
    for key, path in files.items():
        entry = {"path": str(path), "exists": path.exists(), "size_kb": size_kb(path)}
        if path.suffix in {".yaml", ".yml"}:
            p, g, r = count_yaml_proxy_group(path)
            entry.update({"proxies": p, "groups": g, "rules": r})
        elif path.suffix == ".json":
            p, g, r = count_singbox(path)
            entry.update({"proxy_outbounds": p, "groups": g, "route_rules": r})
        elif path.suffix == ".txt" and path.exists():
            lines = [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
            entry.update({"lines": len(lines)})
        report["files"][key] = entry

    rp_dir = OUT / "RuleProviders"
    rp_files = list(rp_dir.glob("*.yaml")) if rp_dir.exists() else []
    rp_total = round(sum(p.stat().st_size for p in rp_files) / 1024, 2) if rp_files else 0.0
    report["rule_providers"] = {"count": len(rp_files), "total_kb": rp_total, "files": {p.name: size_kb(p) for p in rp_files}}

    if report["files"].get("openclash_ready", {}).get("size_kb", 0) > args.max_openclash_kb:
        report["warnings"].append("openclash-ready.yaml is large; use openclash-lite-ready.yaml on small routers.")
    if report["files"].get("openclash_lite", {}).get("size_kb", 0) > args.max_openclash_lite_kb:
        report["errors"].append("openclash-lite-ready.yaml exceeds lite size limit.")
    if report["files"].get("singbox_performance_lite", {}).get("size_kb", 0) > args.max_singbox_kb:
        report["errors"].append("performance-lite.json exceeds sing-box lite size limit.")
    if rp_total > args.max_ruleproviders_kb:
        report["warnings"].append("RuleProviders total size is high; use Light/Standard mode on small routers.")

    report["ok"] = not report["errors"]
    (PERF / "summary_performance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = ["# Performance Validation", "", f"OK: `{report['ok']}`", "", "## Files"]
    for key, entry in report["files"].items():
        md.append(f"- **{key}**: exists={entry['exists']} size={entry['size_kb']} KB")
    md += ["", "## Rule Providers", f"Total: `{rp_total} KB` across `{len(rp_files)}` files", ""]
    if report["warnings"]:
        md.append("## Warnings")
        md.extend([f"- {w}" for w in report["warnings"]])
    if report["errors"]:
        md.append("## Errors")
        md.extend([f"- {e}" for e in report["errors"]])
    (PERF / "summary_performance.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if (args.fail_on_error and not report["ok"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

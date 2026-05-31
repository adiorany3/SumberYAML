#!/usr/bin/env python3
"""Build lightweight diff reports for generated SumberYAML outputs.

Compares the current output/ directory against .previous_output/ when available.
The script is intentionally non-destructive and safe to run at the end of every
workflow. It helps diagnose why a new build behaves differently.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path.cwd()
CURRENT = ROOT / "output"
PREVIOUS = ROOT / ".previous_output"
REPORT_DIR = CURRENT / "Final"

YAML_FILES = [
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
JSON_FILES = [
    "SingBox/import-ready.json",
    "SingBox/mobile-stable-safe.json",
    "SingBox/best-stable-safe.json",
    "SingBox/latest-safe.json",
    "SingBox/lengkap-safe.json",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def proxy_names_from_yaml(path: Path) -> Set[str]:
    data = load_yaml(path)
    names: Set[str] = set()
    for item in data.get("proxies") or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    if not names:
        text = safe_read_text(path)
        for match in re.finditer(r"(?m)^\s*-\s+name:\s*(.+?)\s*$", text):
            names.add(match.group(1).strip().strip('"\''))
    return names


def group_names_from_yaml(path: Path) -> Set[str]:
    data = load_yaml(path)
    names: Set[str] = set()
    for item in data.get("proxy-groups") or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def outbounds_from_json(path: Path) -> Set[str]:
    data = load_json(path)
    tags: Set[str] = set()
    for item in data.get("outbounds") or []:
        if isinstance(item, dict) and item.get("tag"):
            tags.add(str(item["tag"]))
    return tags


def count_rules_yaml(path: Path) -> int:
    data = load_yaml(path)
    rules = data.get("rules") if isinstance(data, dict) else None
    return len(rules) if isinstance(rules, list) else 0


def summarize_file(rel: str) -> Dict[str, Any]:
    cur = CURRENT / rel
    prev = PREVIOUS / rel
    item: Dict[str, Any] = {
        "path": f"output/{rel}",
        "exists": cur.exists(),
        "previous_exists": prev.exists(),
        "changed": None,
    }
    if cur.exists():
        item.update({"size": cur.stat().st_size, "sha256": sha256_file(cur)})
    if prev.exists():
        item.update({"previous_size": prev.stat().st_size, "previous_sha256": sha256_file(prev)})
    if cur.exists() and prev.exists():
        item["changed"] = item.get("sha256") != item.get("previous_sha256")
    elif cur.exists() != prev.exists():
        item["changed"] = True

    if rel.endswith(".yaml"):
        cur_proxy = proxy_names_from_yaml(cur)
        prev_proxy = proxy_names_from_yaml(prev)
        cur_groups = group_names_from_yaml(cur)
        prev_groups = group_names_from_yaml(prev)
        item.update(
            {
                "proxy_count": len(cur_proxy),
                "previous_proxy_count": len(prev_proxy),
                "groups_count": len(cur_groups),
                "previous_groups_count": len(prev_groups),
                "rules_count": count_rules_yaml(cur),
                "added_proxies": sorted(cur_proxy - prev_proxy)[:100],
                "removed_proxies": sorted(prev_proxy - cur_proxy)[:100],
                "added_groups": sorted(cur_groups - prev_groups),
                "removed_groups": sorted(prev_groups - cur_groups),
            }
        )
    elif rel.endswith(".json"):
        cur_tags = outbounds_from_json(cur)
        prev_tags = outbounds_from_json(prev)
        item.update(
            {
                "outbound_count": len(cur_tags),
                "previous_outbound_count": len(prev_tags),
                "added_outbounds": sorted(cur_tags - prev_tags)[:100],
                "removed_outbounds": sorted(prev_tags - cur_tags)[:100],
            }
        )
    return item


def manual_link_count() -> int:
    total = 0
    for rel in ["input/links.txt", "input.txt"]:
        path = ROOT / rel
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                total += 1
    return total


def write_markdown(report: Dict[str, Any], path: Path) -> None:
    lines = [
        "# SumberYAML Diff Report",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Manual trusted links: **{report['manual_link_count']}**",
        "",
        "## Summary",
        "",
        f"Changed files: **{report['changed_file_count']}** / {len(report['files'])}",
        "",
        "## Files",
        "",
    ]
    for item in report["files"]:
        status = "changed" if item.get("changed") else "unchanged"
        if not item.get("exists"):
            status = "missing"
        lines.append(f"### `{item['path']}` — {status}")
        if item["path"].endswith(".yaml"):
            lines.append(
                f"- proxies: {item.get('proxy_count', 0)} "
                f"(prev {item.get('previous_proxy_count', 0)})"
            )
            lines.append(
                f"- groups: {item.get('groups_count', 0)} "
                f"(prev {item.get('previous_groups_count', 0)})"
            )
            lines.append(f"- rules: {item.get('rules_count', 0)}")
            if item.get("added_proxies"):
                lines.append("- added proxies: " + ", ".join(f"`{x}`" for x in item["added_proxies"][:20]))
            if item.get("removed_proxies"):
                lines.append("- removed proxies: " + ", ".join(f"`{x}`" for x in item["removed_proxies"][:20]))
        elif item["path"].endswith(".json"):
            lines.append(
                f"- outbounds: {item.get('outbound_count', 0)} "
                f"(prev {item.get('previous_outbound_count', 0)})"
            )
            if item.get("added_outbounds"):
                lines.append("- added outbounds: " + ", ".join(f"`{x}`" for x in item["added_outbounds"][:20]))
            if item.get("removed_outbounds"):
                lines.append("- removed outbounds: " + ", ".join(f"`{x}`" for x in item["removed_outbounds"][:20]))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rels: List[str] = []
    for rel in YAML_FILES + JSON_FILES:
        if (CURRENT / rel).exists() or (PREVIOUS / rel).exists():
            rels.append(rel)
    if not rels:
        for path in CURRENT.rglob("*"):
            if path.is_file() and path.suffix in {".yaml", ".json"}:
                rels.append(str(path.relative_to(CURRENT)))
    files = [summarize_file(rel) for rel in sorted(set(rels))]
    report = {
        "generated_at": now_iso(),
        "manual_link_count": manual_link_count(),
        "previous_output_available": PREVIOUS.exists(),
        "changed_file_count": sum(1 for item in files if item.get("changed")),
        "files": files,
    }
    (REPORT_DIR / "diff_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, REPORT_DIR / "diff_report.md")
    print(json.dumps({"ok": True, "changed_file_count": report["changed_file_count"], "files": len(files)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a compact diagnostic summary for Streamlit admin."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
FINAL = OUTPUT / "Final"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_csv_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:
        return 0


def yaml_counts(path: Path) -> Dict[str, int]:
    if not path.exists() or yaml is None:
        return {"proxies": 0, "groups": 0, "rules": 0}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return {"proxies": 0, "groups": 0, "rules": 0}
        return {
            "proxies": len(data.get("proxies") or []),
            "groups": len(data.get("proxy-groups") or []),
            "rules": len(data.get("rules") or []),
        }
    except Exception:
        return {"proxies": 0, "groups": 0, "rules": 0}


def singbox_counts(path: Path) -> Dict[str, int]:
    data = read_json(path)
    if not data:
        return {"outbounds": 0, "inbounds": 0, "rules": 0}
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    return {
        "outbounds": len(data.get("outbounds") or []),
        "inbounds": len(data.get("inbounds") or []),
        "rules": len(route.get("rules") or []),
    }


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


def file_status(rel: str) -> Dict[str, Any]:
    path = OUTPUT / rel
    return {
        "path": f"output/{rel}",
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
    }


def main() -> int:
    FINAL.mkdir(parents=True, exist_ok=True)
    diff = read_json(FINAL / "diff_report.json")
    health = read_json(OUTPUT / "Health" / "best_stable_score.json")
    backup = read_json(OUTPUT / "Backup" / "latest_good_summary.json")
    ready = read_json(FINAL / "summary_ready_profiles.json")
    purpose = read_json(OUTPUT / "Validation" / "summary_purpose_groups.json")
    no_bengong = read_json(OUTPUT / "Validation" / "summary_openclash_no_bengong.json")

    summary = {
        "generated_at": now_iso(),
        "manual_link_count": manual_link_count(),
        "openclash_ready": yaml_counts(OUTPUT / "openclash-ready.yaml"),
        "lengkap_yaml": yaml_counts(OUTPUT / "lengkap.yaml"),
        "mobile_stable_safe": singbox_counts(OUTPUT / "SingBox" / "mobile-stable-safe.json"),
        "import_ready": singbox_counts(OUTPUT / "SingBox" / "import-ready.json"),
        "health": {
            "total_nodes": health.get("total_nodes", 0),
            "healthy_or_manual_count": health.get("healthy_or_manual_count", 0),
            "manual_trusted_count": health.get("manual_trusted_count", 0),
            "alive_count": health.get("alive_count", 0),
            "dead_count": health.get("dead_count", 0),
            "untested_count": health.get("untested_count", 0),
        },
        "diff": {
            "changed_file_count": diff.get("changed_file_count", 0),
            "previous_output_available": diff.get("previous_output_available", False),
        },
        "backup": {
            "ok": backup.get("ok", False),
            "action": backup.get("action", "-"),
            "generated_at": backup.get("generated_at", "-"),
            "copied": backup.get("copied", []),
            "restored": backup.get("restored", []),
        },
        "ready_profiles": ready,
        "purpose_groups": purpose,
        "no_bengong": no_bengong,
        "files": [
            file_status("openclash-ready.yaml"),
            file_status("SingBox/mobile-stable-safe.json"),
            file_status("SingBox/import-ready.json"),
            file_status("Final/diff_report.md"),
            file_status("Health/node_score.csv"),
            file_status("Backup/latest_good_summary.json"),
        ],
        "csv_counts": {
            "node_score_rows": read_csv_count(OUTPUT / "Health" / "node_score.csv"),
            "node_history_rows": read_csv_count(OUTPUT / "Health" / "node_score_history.csv"),
            "healthy_rows": read_csv_count(OUTPUT / "Health" / "healthy.csv"),
            "quarantine_rows": read_csv_count(OUTPUT / "Health" / "quarantine.csv"),
        },
    }
    (FINAL / "admin_diagnostic_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health-dir", default="output/Health")
    args = parser.parse_args()
    health_dir = Path(args.health_dir)
    state_path = health_dir / "health_state.json"
    state = read_json(state_path, {"nodes": {}})
    nodes = state.get("nodes", {}) if isinstance(state, dict) else {}
    cleared = 0
    for item in nodes.values():
        if isinstance(item, dict) and item.get("quarantined_until"):
            item["quarantined_until"] = ""
            item["fail_streak"] = 0
            item["last_status"] = "manual_clear_quarantine"
            cleared += 1
    if not isinstance(state, dict):
        state = {"nodes": nodes}
    state["updated_at"] = iso()
    state["last_action"] = "clear_quarantine"
    write_json(state_path, state)
    summary = {
        "ok": True,
        "updated_at": iso(),
        "cleared_count": cleared,
        "state_path": str(state_path),
    }
    write_json(health_dir / "summary_clear_quarantine.json", summary)
    # Empty quarantine.csv after clear for UI clarity.
    (health_dir / "quarantine.csv").parent.mkdir(parents=True, exist_ok=True)
    with (health_dir / "quarantine.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "status", "quarantined_until"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Maintain node score and history reports for SumberYAML.

This script is intentionally diagnostic. It does not remove trusted manual
accounts from input/links.txt or input.txt. It only writes score reports that can
be used to inspect stability trends.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
HEALTH = OUTPUT / "Health"

CSV_SOURCES = [
    OUTPUT / "BestPing" / "top5_indonesia_ping.csv",
    OUTPUT / "BestPing" / "top5_best_ping.csv",
    OUTPUT / "Alive" / "alive.csv",
    OUTPUT / "Alive" / "check_result.csv",
]
YAML_SOURCES = [
    OUTPUT / "openclash-ready.yaml",
    OUTPUT / "lengkap.yaml",
    OUTPUT / "lengkap_alive.yaml",
    OUTPUT / "strict_alive.yaml",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().lower()
    m = re.search(r"\d+", text)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def normalize_name(value: Any) -> str:
    return str(value or "").strip()


def is_manual_name(name: str) -> bool:
    text = name.lower()
    return text.startswith("link ") or text.startswith("link-") or text.startswith("manual ") or " input" in text


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def read_yaml_proxy_names(path: Path) -> List[str]:
    if not path.exists():
        return []
    if yaml is not None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                names = []
                for item in data.get("proxies") or []:
                    if isinstance(item, dict) and item.get("name"):
                        names.append(str(item["name"]))
                if names:
                    return names
        except Exception:
            pass
    text = path.read_text(encoding="utf-8", errors="replace")
    return [m.group(1).strip().strip('"\'') for m in re.finditer(r"(?m)^\s*-\s+name:\s*(.+?)\s*$", text)]


def load_existing_history(path: Path) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"samples": 0, "alive_samples": 0, "dead_samples": 0, "sum_delay": 0, "delay_samples": 0})
    if not path.exists():
        return stats
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                name = normalize_name(row.get("name"))
                if not name:
                    continue
                delay = parse_int(row.get("delay_ms"))
                status = str(row.get("status") or "").lower()
                stats[name]["samples"] += 1
                if status == "alive":
                    stats[name]["alive_samples"] += 1
                elif status == "dead":
                    stats[name]["dead_samples"] += 1
                if delay is not None:
                    stats[name]["sum_delay"] += delay
                    stats[name]["delay_samples"] += 1
    except Exception:
        return stats
    return stats


def collect_current_nodes() -> Dict[str, Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}

    # Seed from YAML so even untested/trusted manual nodes are visible.
    for path in YAML_SOURCES:
        for name in read_yaml_proxy_names(path):
            item = nodes.setdefault(name, {"name": name, "sources": set(), "status": "untested", "delays": []})
            item["sources"].add(path.name)
            if is_manual_name(name):
                item["manual_trusted"] = True

    for path in CSV_SOURCES:
        for row in read_csv_rows(path):
            name = normalize_name(row.get("name") or row.get("proxy") or row.get("tag"))
            if not name:
                continue
            delay = parse_int(row.get("delay_ms") or row.get("delay") or row.get("latency"))
            raw_status = str(row.get("status") or "").strip().lower()
            if not raw_status and delay is not None:
                raw_status = "alive"
            item = nodes.setdefault(name, {"name": name, "sources": set(), "status": "untested", "delays": []})
            item["sources"].add(str(path.relative_to(OUTPUT)))
            if delay is not None:
                item["delays"].append(delay)
            if raw_status in {"alive", "ok", "success"}:
                item["status"] = "alive"
            elif raw_status in {"dead", "failed", "timeout", "error"} and item.get("status") != "alive":
                item["status"] = "dead"
            for key in ["country", "server", "port", "protocol", "network", "reason"]:
                if row.get(key) and not item.get(key):
                    item[key] = row.get(key)
            if is_manual_name(name):
                item["manual_trusted"] = True

    return nodes


def compute_scores(nodes: Dict[str, Dict[str, Any]], history: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    scored = []
    for name, item in nodes.items():
        delays = [int(x) for x in item.get("delays", []) if x is not None]
        current_delay = min(delays) if delays else None
        hist = history.get(name, {})
        hist_samples = int(hist.get("samples", 0) or 0)
        hist_alive = int(hist.get("alive_samples", 0) or 0)
        hist_dead = int(hist.get("dead_samples", 0) or 0)
        hist_delay_samples = int(hist.get("delay_samples", 0) or 0)
        hist_avg_delay = None
        if hist_delay_samples:
            hist_avg_delay = round(float(hist.get("sum_delay", 0)) / hist_delay_samples, 2)
        success_rate = None
        if hist_samples:
            success_rate = round(hist_alive / hist_samples, 4)

        # Score: lower is better. Trusted manual gets visibility bonus but never forced out.
        base_delay = current_delay if current_delay is not None else (hist_avg_delay if hist_avg_delay is not None else 9999)
        penalty = 0
        status = item.get("status", "untested")
        if status == "dead":
            penalty += 5000
        elif status == "untested":
            penalty += 1200
        if success_rate is not None:
            penalty += int((1.0 - success_rate) * 2000)
        if hist_dead:
            penalty += min(hist_dead * 250, 2000)
        if item.get("manual_trusted"):
            penalty -= 300
        score = max(0, int(base_delay) + penalty)

        scored.append(
            {
                "name": name,
                "score": score,
                "status": status,
                "delay_ms": current_delay if current_delay is not None else "",
                "history_samples": hist_samples,
                "history_success_rate": success_rate if success_rate is not None else "",
                "history_avg_delay_ms": hist_avg_delay if hist_avg_delay is not None else "",
                "manual_trusted": bool(item.get("manual_trusted")),
                "country": item.get("country", ""),
                "protocol": item.get("protocol", ""),
                "server": item.get("server", ""),
                "port": item.get("port", ""),
                "sources": ";".join(sorted(str(s) for s in item.get("sources", []))),
            }
        )
    scored.sort(key=lambda row: (0 if row["manual_trusted"] else 1, row["score"], str(row["name"])))
    return scored


def append_history(scored: List[Dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "timestamp",
        "name",
        "status",
        "delay_ms",
        "score",
        "manual_trusted",
        "country",
        "protocol",
        "server",
        "port",
        "sources",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        ts = now_iso()
        for row in scored:
            writer.writerow({key: (ts if key == "timestamp" else row.get(key, "")) for key in fieldnames})


def write_score_csv(scored: List[Dict[str, Any]], path: Path) -> None:
    if not scored:
        path.write_text("name,score,status,delay_ms,manual_trusted\n", encoding="utf-8")
        return
    fieldnames = list(scored[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored)


def main() -> int:
    HEALTH.mkdir(parents=True, exist_ok=True)
    nodes = collect_current_nodes()
    history_path = HEALTH / "node_score_history.csv"
    history = load_existing_history(history_path)
    scored = compute_scores(nodes, history)
    append_history(scored, history_path)
    write_score_csv(scored, HEALTH / "node_score.csv")

    healthy = [row for row in scored if row["status"] == "alive" or row["manual_trusted"]]
    best_stable = healthy[:20]
    summary = {
        "generated_at": now_iso(),
        "total_nodes": len(scored),
        "healthy_or_manual_count": len(healthy),
        "manual_trusted_count": sum(1 for row in scored if row["manual_trusted"]),
        "alive_count": sum(1 for row in scored if row["status"] == "alive"),
        "dead_count": sum(1 for row in scored if row["status"] == "dead"),
        "untested_count": sum(1 for row in scored if row["status"] == "untested"),
        "top_nodes": best_stable[:10],
    }
    (HEALTH / "best_stable_score.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

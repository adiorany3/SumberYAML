#!/usr/bin/env python3
"""Backup/restore latest-good SumberYAML outputs.

Commands:
  --backup   Validate core outputs and copy them to output/Backup/latest-good
  --restore  Restore latest-good files back into output
  --check    Print status only

This script never modifies input/links.txt or input.txt.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path.cwd()
OUTPUT = ROOT / "output"
BACKUP = OUTPUT / "Backup" / "latest-good"
SUMMARY = OUTPUT / "Backup" / "latest_good_summary.json"

CORE_FILES = [
    "openclash-ready.yaml",
    "lengkap.yaml",
    "SingBox/import-ready.json",
    "SingBox/mobile-stable-safe.json",
    "SingBox/best-stable-safe.json",
    "SingBox/latest-safe.json",
]
OPTIONAL_DIRS = [
    "Final",
    "Health",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def validate_yaml(path: Path) -> Tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    data = load_yaml(path)
    if not data:
        return False, "cannot parse yaml or empty"
    if not isinstance(data.get("proxies"), list) or not data.get("proxies"):
        return False, "no proxies"
    if not isinstance(data.get("proxy-groups"), list) or not data.get("proxy-groups"):
        return False, "no proxy-groups"
    if not isinstance(data.get("rules"), list) or not data.get("rules"):
        return False, "no rules"
    names = {str(p.get("name")) for p in data.get("proxies", []) if isinstance(p, dict) and p.get("name")}
    groups = {str(g.get("name")) for g in data.get("proxy-groups", []) if isinstance(g, dict) and g.get("name")}
    valid = names | groups | {"DIRECT", "REJECT", "GLOBAL"}
    missing = []
    for group in data.get("proxy-groups", []):
        if not isinstance(group, dict):
            continue
        for ref in group.get("proxies") or []:
            if str(ref) not in valid:
                missing.append(f"{group.get('name')}->{ref}")
    if missing:
        return False, "missing group refs: " + ", ".join(missing[:10])
    return True, "ok"


def validate_singbox(path: Path) -> Tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    data = load_json(path)
    if not data:
        return False, "cannot parse json or empty"
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        return False, "no outbounds"
    tags = {str(o.get("tag")) for o in outbounds if isinstance(o, dict) and o.get("tag")}
    if not tags:
        return False, "no outbound tags"
    missing = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        for ref in outbound.get("outbounds") or []:
            if str(ref) not in tags and str(ref) not in {"DIRECT", "direct", "REJECT"}:
                missing.append(f"{outbound.get('tag')}->{ref}")
        if outbound.get("default"):
            return False, f"selector default field remains in {outbound.get('tag')}"
    route = data.get("route") if isinstance(data.get("route"), dict) else {}
    final = route.get("final")
    if final and str(final) not in tags and str(final).upper() != "DIRECT":
        missing.append(f"route.final->{final}")
    if missing:
        return False, "missing dependencies: " + ", ".join(missing[:10])
    return True, "ok"


def validate_outputs() -> Dict[str, Any]:
    checks = []
    ok = True
    for rel in CORE_FILES:
        path = OUTPUT / rel
        if rel.endswith(".yaml"):
            item_ok, reason = validate_yaml(path)
        elif rel.endswith(".json"):
            item_ok, reason = validate_singbox(path)
        else:
            item_ok, reason = path.exists(), "ok" if path.exists() else "missing"
        checks.append({"path": f"output/{rel}", "ok": item_ok, "reason": reason})
        # At least one ready file can be missing in older builds, but import-ready/openclash-ready matter most.
        if rel in {"openclash-ready.yaml", "SingBox/mobile-stable-safe.json"} and not item_ok:
            ok = False
    return {"ok": ok, "checks": checks}


def backup() -> Dict[str, Any]:
    validation = validate_outputs()
    BACKUP.mkdir(parents=True, exist_ok=True)
    copied = []
    if not validation["ok"]:
        summary = {"generated_at": now_iso(), "action": "backup", "ok": False, "validation": validation, "copied": []}
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary
    for rel in CORE_FILES:
        src = OUTPUT / rel
        if not src.exists():
            continue
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    # Copy helpful reports without failing.
    for rel_dir in OPTIONAL_DIRS:
        src_dir = OUTPUT / rel_dir
        if src_dir.exists():
            dst_dir = BACKUP / rel_dir
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
    summary = {"generated_at": now_iso(), "action": "backup", "ok": True, "validation": validation, "copied": copied}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def restore() -> Dict[str, Any]:
    restored = []
    missing = []
    for rel in CORE_FILES:
        src = BACKUP / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst = OUTPUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored.append(rel)
    for rel_dir in OPTIONAL_DIRS:
        src_dir = BACKUP / rel_dir
        if src_dir.exists():
            dst_dir = OUTPUT / rel_dir
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
    validation = validate_outputs()
    summary = {"generated_at": now_iso(), "action": "restore", "ok": bool(restored), "restored": restored, "missing": missing, "validation": validation}
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def check() -> Dict[str, Any]:
    files = []
    for rel in CORE_FILES:
        files.append({"path": f"output/Backup/latest-good/{rel}", "exists": (BACKUP / rel).exists()})
    return {"generated_at": now_iso(), "action": "check", "backup_dir_exists": BACKUP.exists(), "files": files, "current_validation": validate_outputs()}


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--backup", action="store_true")
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.backup:
        result = backup()
    elif args.restore:
        result = restore()
    else:
        result = check()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok", True) else 0


if __name__ == "__main__":
    raise SystemExit(main())

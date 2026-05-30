#!/usr/bin/env python3
"""Remove selector outbound `default` fields for older sing-box/SFA import compatibility.

Some Android packet-tunnel/SFA builds bundle older sing-box cores that reject:
    outbounds[n].default: json: unknown field "default"

Official newer sing-box supports selector.default, but the same behavior can be
kept on older cores by moving the default tag to the first entry in `outbounds`
and then removing the `default` key. sing-box selector uses the first outbound
when `default` is empty/absent.

This script processes every JSON file in output/SingBox by default.
It never removes real proxy outbounds, including trusted manual accounts from
input/links.txt/input.txt. It only rewrites group metadata.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_json(path: Path) -> Dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def dump_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def move_tag_to_front(values: Any, tag: str) -> Any:
    if not isinstance(values, list) or not tag:
        return values
    filtered = [item for item in values if item != tag]
    return [tag] + filtered


def sanitize_file(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if data is None:
        return {
            "file": str(path),
            "ok": False,
            "changed": False,
            "reason": "invalid-json-or-not-object",
            "removed_default": 0,
        }

    changed = False
    removed_default = 0
    reordered = 0
    touched_tags: List[str] = []

    outbounds = data.get("outbounds")
    if isinstance(outbounds, list):
        for outbound in outbounds:
            if not isinstance(outbound, dict):
                continue

            if "default" not in outbound:
                continue

            default_tag = outbound.get("default")
            old_list = outbound.get("outbounds")
            if isinstance(default_tag, str) and isinstance(old_list, list) and default_tag in old_list:
                new_list = move_tag_to_front(old_list, default_tag)
                if new_list != old_list:
                    outbound["outbounds"] = new_list
                    reordered += 1

            outbound.pop("default", None)
            removed_default += 1
            touched_tags.append(str(outbound.get("tag", "-")))
            changed = True

    if changed:
        dump_json(path, data)

    return {
        "file": str(path),
        "ok": True,
        "changed": changed,
        "removed_default": removed_default,
        "reordered": reordered,
        "touched_tags": touched_tags,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="output/SingBox", help="Directory containing sing-box JSON files")
    parser.add_argument("--report", default="output/SingBox/summary_selector_default_legacy.json")
    args = parser.parse_args()

    root = Path(args.dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(root.glob("*.json")) if root.exists() else []
    results = [sanitize_file(path) for path in files]

    summary = {
        "ok": True,
        "processed": len(results),
        "changed": sum(1 for item in results if item.get("changed")),
        "removed_default_total": sum(int(item.get("removed_default") or 0) for item in results),
        "files": results,
        "note": "Removed selector default fields for older sing-box/SFA import compatibility. Trusted manual accounts are not filtered or removed.",
    }
    dump_json(report_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

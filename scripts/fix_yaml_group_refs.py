#!/usr/bin/env python3
"""
Fix OpenClash/Mihomo YAML proxy-groups that still reference proxies/groups
that were removed by filtering steps, e.g. lite.yaml / fast.yaml.

Usage:
  python scripts/fix_yaml_group_refs.py
  python scripts/fix_yaml_group_refs.py output/lite.yaml output/fast.yaml

The script is intentionally conservative:
- It does not delete proxy-groups.
- It removes only missing entries inside each group's `proxies` list.
- If a group becomes empty, it fills it with valid proxies so validation passes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyYAML belum terinstall. Tambahkan `pip install pyyaml` di workflow atau requirements.txt."
    ) from exc

OUTPUT_DIR = Path("output")
SPECIAL_TARGETS = {
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "COMPATIBLE",
}

DEFAULT_FILES = [
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/general.yaml",
]


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(
            data,
            handle,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def get_names(data: dict) -> tuple[list[str], list[str]]:
    proxies = as_list(data.get("proxies"))
    groups = as_list(data.get("proxy-groups"))

    proxy_names = [
        str(item.get("name", "")).strip()
        for item in proxies
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    group_names = [
        str(item.get("name", "")).strip()
        for item in groups
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    return proxy_names, group_names


def valid_target_set(proxy_names: list[str], group_names: list[str]) -> set[str]:
    return set(proxy_names) | set(group_names) | SPECIAL_TARGETS


def choose_fallback_for_group(group_name: str, proxy_names: list[str], group_names: list[str]) -> list[str]:
    """Return safe fallback targets when a group loses all entries."""
    # Prefer real proxy nodes. This avoids self-reference/circular group traps.
    if proxy_names:
        return proxy_names[: min(10, len(proxy_names))]

    # If no proxy exists, use DIRECT so the YAML remains syntactically valid.
    return ["DIRECT"]


def fix_one_file(path: Path, dry_run: bool = False) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False, "removed": 0, "filled": 0, "missing_after": []}

    data = read_yaml(path)
    groups = as_list(data.get("proxy-groups"))
    proxy_names, group_names = get_names(data)
    valid_targets = valid_target_set(proxy_names, group_names)

    changed = False
    removed_count = 0
    filled_count = 0
    details: list[str] = []

    for group in groups:
        if not isinstance(group, dict):
            continue

        group_name = str(group.get("name", "")).strip() or "<unnamed>"
        original_targets = group.get("proxies")

        if not isinstance(original_targets, list):
            continue

        clean_targets = []
        seen = set()
        removed_targets = []

        for target in original_targets:
            target_text = str(target).strip()
            if not target_text:
                continue
            if target_text in valid_targets and target_text not in seen:
                clean_targets.append(target_text)
                seen.add(target_text)
            elif target_text not in valid_targets:
                removed_targets.append(target_text)

        if removed_targets:
            removed_count += len(removed_targets)
            changed = True
            details.append(f"{group_name}: removed missing target(s): {', '.join(removed_targets)}")

        if not clean_targets:
            fallback = choose_fallback_for_group(group_name, proxy_names, group_names)
            clean_targets = fallback
            filled_count += 1
            changed = True
            details.append(f"{group_name}: filled empty group with valid fallback target(s): {', '.join(fallback)}")

        if clean_targets != original_targets:
            group["proxies"] = clean_targets

    missing_after = find_missing_group_targets(data)

    if changed and not dry_run:
        write_yaml(path, data)

    return {
        "path": str(path),
        "exists": True,
        "changed": changed,
        "removed": removed_count,
        "filled": filled_count,
        "missing_after": missing_after,
        "details": details,
        "proxy_count": len(proxy_names),
        "group_count": len(group_names),
    }


def find_missing_group_targets(data: dict) -> list[str]:
    proxy_names, group_names = get_names(data)
    valid_targets = valid_target_set(proxy_names, group_names)
    missing = []

    for group in as_list(data.get("proxy-groups")):
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name", "")).strip() or "<unnamed>"
        for target in as_list(group.get("proxies")):
            target_text = str(target).strip()
            if target_text and target_text not in valid_targets:
                missing.append(f"{group_name} -> {target_text}")

    return missing


def discover_files() -> list[Path]:
    files = [Path(item) for item in DEFAULT_FILES]

    if OUTPUT_DIR.exists():
        for path in OUTPUT_DIR.rglob("*.yaml"):
            if path not in files:
                files.append(path)
        for path in OUTPUT_DIR.rglob("*.yml"):
            if path not in files:
                files.append(path)

    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix missing proxy/group references in OpenClash YAML files.")
    parser.add_argument("files", nargs="*", help="YAML files to sanitize. Default: common output files + output/**/*.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing files.")
    args = parser.parse_args()

    paths = [Path(item) for item in args.files] if args.files else discover_files()
    if not paths:
        print("No YAML files found.")
        return 0

    failed = False
    for path in paths:
        result = fix_one_file(path, dry_run=args.dry_run)
        if not result["exists"]:
            continue

        status = "CHANGED" if result["changed"] else "OK"
        print(
            f"[{status}] {result['path']} "
            f"proxies={result.get('proxy_count', '-')} "
            f"groups={result.get('group_count', '-')} "
            f"removed={result.get('removed', 0)} "
            f"filled={result.get('filled', 0)}"
        )
        for detail in result.get("details", []):
            print(f"  - {detail}")

        missing_after = result.get("missing_after", [])
        if missing_after:
            failed = True
            print("  Missing references remain:")
            for item in missing_after:
                print(f"  - {item}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

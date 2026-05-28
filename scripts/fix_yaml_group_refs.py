#!/usr/bin/env python3
"""
Fix OpenClash/Mihomo YAML proxy-group references after generated outputs are filtered.

Problem handled:
- output/lite.yaml and output/fast.yaml may contain fewer proxies than lengkap.yaml.
- proxy-groups copied from the full config can still reference proxies removed by filtering.
- The validator then fails with: group points to proxy/group that does not exist.

This script sanitizes every output YAML before validation:
1. Collects existing proxy names from proxies[].name.
2. Collects existing group names from proxy-groups[].name.
3. Removes every proxy-group target that is not an existing proxy, existing group, or Clash/Mihomo special target.
4. If a group becomes empty, fills it with the fastest/first available proxy, otherwise DIRECT.
5. Avoids self references.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML belum terinstall. Tambahkan step: pip install pyyaml"
    ) from exc


DEFAULT_SPECIAL_TARGETS = {
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "GLOBAL",
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


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else {}


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def unique_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def collect_proxy_names(data: dict[str, Any]) -> list[str]:
    proxies = data.get("proxies") or []
    names: list[str] = []
    if not isinstance(proxies, list):
        return names
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        name = str(proxy.get("name") or "").strip()
        if name:
            names.append(name)
    return unique_keep_order(names)


def collect_group_names(data: dict[str, Any]) -> list[str]:
    groups = data.get("proxy-groups") or []
    names: list[str] = []
    if not isinstance(groups, list):
        return names
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or "").strip()
        if name:
            names.append(name)
    return unique_keep_order(names)


def choose_fallback_proxy(proxy_names: list[str], special_targets: set[str]) -> str:
    if proxy_names:
        return proxy_names[0]
    if "DIRECT" in special_targets:
        return "DIRECT"
    return next(iter(special_targets), "DIRECT")


def sanitize_group_refs(data: dict[str, Any], path: Path, special_targets: set[str]) -> dict[str, Any]:
    proxy_names = collect_proxy_names(data)
    group_names = collect_group_names(data)
    allowed_targets = set(proxy_names) | set(group_names) | special_targets
    groups = data.get("proxy-groups") or []

    report = {
        "file": str(path),
        "proxies": len(proxy_names),
        "groups": len(group_names),
        "changed": False,
        "removed": [],
        "filled": [],
    }

    if not isinstance(groups, list):
        return report

    fallback_proxy = choose_fallback_proxy(proxy_names, special_targets)

    for group in groups:
        if not isinstance(group, dict):
            continue

        group_name = str(group.get("name") or "").strip()
        targets = group.get("proxies")

        if not isinstance(targets, list):
            continue

        cleaned: list[str] = []
        removed: list[str] = []
        for target in targets:
            target_name = str(target).strip()
            if not target_name:
                continue

            # Hindari self-reference karena bisa membuat selector/group aneh.
            if target_name == group_name:
                removed.append(target_name)
                continue

            if target_name in allowed_targets:
                cleaned.append(target_name)
            else:
                removed.append(target_name)

        cleaned = unique_keep_order(cleaned)

        # Group url-test/fallback/load-balance/select butuh minimal 1 target.
        if not cleaned:
            cleaned = [fallback_proxy]
            report["filled"].append({
                "group": group_name,
                "fallback": fallback_proxy,
            })

        if cleaned != [str(item).strip() for item in targets if str(item).strip()]:
            group["proxies"] = cleaned
            report["changed"] = True

        for item in unique_keep_order(removed):
            report["removed"].append({
                "group": group_name,
                "target": item,
            })

    return report


def find_yaml_files(output_dir: Path, explicit_files: list[str] | None = None) -> list[Path]:
    paths: list[Path] = []

    candidates = explicit_files or DEFAULT_FILES
    for item in candidates:
        path = Path(item)
        if path.exists() and path.is_file():
            paths.append(path)

    # Tambahkan YAML lain di output root jika ada, tanpa masuk terlalu dalam ke arsip/country jika tidak perlu.
    if output_dir.exists():
        for path in sorted(output_dir.glob("*.yaml")):
            if path.is_file() and path not in paths:
                paths.append(path)

    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--report", default="output/Validation/group_ref_fix_report.json")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    special_targets = set(DEFAULT_SPECIAL_TARGETS)
    paths = find_yaml_files(output_dir, explicit_files=args.files or None)

    reports: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = load_yaml(path)
            report = sanitize_group_refs(data, path, special_targets)
            if report.get("changed"):
                dump_yaml(path, data)
            reports.append(report)
        except Exception as exc:
            reports.append({
                "file": str(path),
                "error": str(exc),
                "changed": False,
            })

    summary = {
        "ok": not any(item.get("error") for item in reports),
        "files_checked": len(reports),
        "files_changed": sum(1 for item in reports if item.get("changed")),
        "removed_count": sum(len(item.get("removed", [])) for item in reports),
        "filled_count": sum(len(item.get("filled", [])) for item in reports),
        "files": reports,
    }

    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Group reference fix report: {report_path}")
    print(
        f"Checked={summary['files_checked']} Changed={summary['files_changed']} "
        f"Removed={summary['removed_count']} Filled={summary['filled_count']}"
    )

    for item in reports:
        if item.get("changed"):
            print(f"[FIXED] {item['file']}")
            for removed in item.get("removed", [])[:30]:
                print(f"  - removed {removed['target']} from {removed['group']}")
            if len(item.get("removed", [])) > 30:
                print(f"  - ... {len(item.get('removed', [])) - 30} more removed")
            for filled in item.get("filled", []):
                print(f"  - filled {filled['group']} with {filled['fallback']}")
        else:
            print(f"[OK] {item.get('file')}")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

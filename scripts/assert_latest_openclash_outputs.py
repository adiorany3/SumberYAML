#!/usr/bin/env python3
"""Assert that the committed OpenClash outputs contain the latest smart-safe features.

This is intentionally strict for CI: it prevents GitHub Actions from committing only
`last_run.json` when the YAML files were not regenerated with the latest generator stages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml


BASE_OUTPUTS = [
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
]

OPTIONAL_OUTPUTS = [
    "output/gaming.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/general.yaml",
    "output/openclash-ready.yaml",
    "output/openclash-lite-ready.yaml",
]

SMART_SAFE_GROUPS = {
    "MANUAL-LINK",
    "MANUAL-FALLBACK",
    "MANUAL-BEST",
    "SAT-SET",
    "ANTI-BENGONG",
    "BEST-STABLE",
    "fallback-link",
    "best-link",
}

RULE_FOCUS_GROUPS = {
    "WEB-AI",
    "WEB-STREAMING",
    "WEB-SOCIAL",
    "WEB-GAMING",
    "WEB-BANKING",
    "WEB-MARKETPLACE",
    "WEB-DEV",
    "WEB-GOOGLE",
    "WEB-DEFAULT",
    "WEB-BYPASS",
    "WEB-BLOCK",
}

SMART_QOS_GROUPS = {
    "QOS-REALTIME",
    "QOS-GAMING",
    "QOS-STREAMING",
    "QOS-AI",
    "QOS-SOCIAL",
    "QOS-WORK",
    "QOS-BANKING",
    "QOS-MARKETPLACE",
    "QOS-DOWNLOAD",
    "QOS-BYPASS",
    "QOS-BLOCK",
    "QOS-DEFAULT",
}

INPUT_VMESS_LB_GROUP = "INPUT-VMESS-LB"
INPUT_VMESS_TARGET_GROUPS = {
    "QOS-MARKETPLACE",
    "QOS-SOCIAL",
    "QOS-BANKING",
    "WEB-MARKETPLACE",
    "WEB-SOCIAL",
    "WEB-BANKING",
}

BLOCKED_TYPES = {"ss", "ssr"}
RULE_BLOCKED_TARGETS = {"DIRECT", "REJECT"}


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception as exc:
        raise AssertionError(f"YAML parse failed: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AssertionError(f"YAML root must be a mapping: {path}")
    return data


def group_names(data: dict[str, Any]) -> set[str]:
    groups = data.get("proxy-groups") or []
    return {str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")}


def proxy_names(data: dict[str, Any]) -> set[str]:
    proxies = data.get("proxies") or []
    return {str(p.get("name")) for p in proxies if isinstance(p, dict) and p.get("name")}


def require_report(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"Missing {label} report: {path}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        errors.append(f"Invalid JSON report {path}: {exc}")
        return
    if isinstance(data, dict) and data.get("ok") is False:
        errors.append(f"Report says not OK: {path}")


def target_of_rule(rule: str) -> str:
    parts = [part.strip() for part in str(rule).split(",")]
    return parts[-1].upper() if parts else ""


def assert_direct_reject_policy(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    rules = data.get("rules") or []
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, str) and target_of_rule(rule) in RULE_BLOCKED_TARGETS:
                errors.append(f"DIRECT/REJECT must not be a direct rule target: {path}: {rule}")

    for group in data.get("proxy-groups") or []:
        if not isinstance(group, dict):
            continue
        gtype = str(group.get("type") or "").lower()
        gname = str(group.get("name") or "")
        refs = [str(x) for x in (group.get("proxies") or [])]
        if gtype not in {"select", "selector"}:
            bad = [x for x in refs if x.upper() in RULE_BLOCKED_TARGETS]
            if bad:
                errors.append(f"DIRECT/REJECT only allowed inside selector groups: {path}: {gname}: {bad}")


def assert_group_refs(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    pnames = proxy_names(data)
    gnames = group_names(data)
    allowed = pnames | gnames | {"DIRECT", "REJECT", "PASS", "COMPATIBLE"}
    for group in data.get("proxy-groups") or []:
        if not isinstance(group, dict):
            continue
        gname = str(group.get("name") or "")
        refs = group.get("proxies") or []
        if not isinstance(refs, list):
            errors.append(f"Group proxies must be a list: {path}: {gname}")
            continue
        for ref in refs:
            ref = str(ref)
            if ref == gname:
                errors.append(f"Group self-reference is invalid: {path}: {gname} -> {ref}")
            elif ref not in allowed:
                errors.append(f"Invalid proxy-group reference: {path}: {gname} -> {ref}")


def assert_no_blocked_protocols(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    for proxy in data.get("proxies") or []:
        if not isinstance(proxy, dict):
            continue
        ptype = str(proxy.get("type") or "").strip().lower()
        if ptype in BLOCKED_TYPES:
            errors.append(f"Blocked proxy type remains in output: {path}: {proxy.get('name')} type={ptype}")


def assert_groups(path: Path, data: dict[str, Any], required: Iterable[str], label: str, errors: list[str]) -> None:
    existing = group_names(data)
    missing = sorted(set(required) - existing)
    if missing:
        errors.append(f"Missing {label} groups in {path}: {', '.join(missing)}")


def assert_input_vmess_lb(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    groups = {str(g.get("name")): g for g in (data.get("proxy-groups") or []) if isinstance(g, dict) and g.get("name")}
    proxies = {str(p.get("name")): p for p in (data.get("proxies") or []) if isinstance(p, dict) and p.get("name")}
    lb = groups.get(INPUT_VMESS_LB_GROUP)
    if not lb:
        return
    if str(lb.get("type") or "").lower() != "load-balance":
        errors.append(f"{INPUT_VMESS_LB_GROUP} must be load-balance: {path}")
    refs = lb.get("proxies") or []
    if not isinstance(refs, list) or not refs:
        errors.append(f"{INPUT_VMESS_LB_GROUP} empty proxies: {path}")
        return
    for ref in refs:
        item = proxies.get(str(ref))
        if not item:
            errors.append(f"{INPUT_VMESS_LB_GROUP} ref missing: {path}: {ref}")
        elif str(item.get("type") or "").lower() != "vmess":
            errors.append(f"{INPUT_VMESS_LB_GROUP} contains non-vmess: {path}: {ref} type={item.get('type')}")
    for name in INPUT_VMESS_TARGET_GROUPS:
        group = groups.get(name)
        if group and isinstance(group.get("proxies"), list) and INPUT_VMESS_LB_GROUP not in [str(x) for x in group.get("proxies")]:
            errors.append(f"{name} must include {INPUT_VMESS_LB_GROUP}: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--strict", action="store_true", help="Fail when latest optional feature outputs are missing.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    enable_rule_focus = truthy(os.environ.get("ENABLE_RULE_FOCUS"), True)
    enable_smart_qos = truthy(os.environ.get("ENABLE_SMART_QOS"), True)
    enable_input_vmess_lb = truthy(os.environ.get("ENABLE_INPUT_VMESS_LB"), True)
    smart_safe_manual_only = truthy(os.environ.get("SMART_SAFE_MANUAL_ONLY"), True)

    errors: list[str] = []
    files = [root / p for p in BASE_OUTPUTS]
    files += [root / p for p in OPTIONAL_OUTPUTS if (root / p).is_file()]

    if smart_safe_manual_only:
        manual_only = root / "output/manual_only.yaml"
        if not manual_only.is_file():
            errors.append("Missing required latest output: output/manual_only.yaml")
        else:
            files.append(manual_only)

    for path in files:
        if not path.is_file():
            errors.append(f"Missing required output YAML: {path.relative_to(root)}")
            continue
        try:
            data = load_yaml(path)
        except AssertionError as exc:
            errors.append(str(exc))
            continue

        assert_no_blocked_protocols(path.relative_to(root), data, errors)
        assert_group_refs(path.relative_to(root), data, errors)
        assert_direct_reject_policy(path.relative_to(root), data, errors)

        # Smart-safe groups are expected in the main YAML outputs. manual_only may only have manual groups.
        if path.name != "manual_only.yaml":
            assert_groups(path.relative_to(root), data, {"SAT-SET", "ANTI-BENGONG", "BEST-STABLE"}, "smart-safe", errors)

        if enable_rule_focus:
            assert_groups(path.relative_to(root), data, RULE_FOCUS_GROUPS, "rule-focus", errors)

        if enable_smart_qos:
            assert_groups(path.relative_to(root), data, SMART_QOS_GROUPS, "smart-qos", errors)

        if enable_input_vmess_lb:
            assert_input_vmess_lb(path.relative_to(root), data, errors)

    # Required feature reports prove the feature scripts actually ran, not just the marker.
    if smart_safe_manual_only:
        # The smart-safe script historically writes either smart_safe_report.json or report.txt.
        if not (root / "output/Validation/smart_safe_report.json").is_file() and not (root / "output/report.txt").is_file():
            errors.append("Missing smart-safe output report: output/Validation/smart_safe_report.json or output/report.txt")
    if enable_rule_focus:
        require_report(root / "output/Validation/rule_focus_report.json", "rule-focus", errors)
    if enable_smart_qos:
        require_report(root / "output/Validation/smart_qos_report.json", "smart-qos", errors)
    if enable_input_vmess_lb:
        require_report(root / "output/Validation/input_vmess_loadbalance_report.json", "input-vmess-loadbalance", errors)

    if errors:
        print("Latest OpenClash output assertion FAILED:")
        for err in errors:
            print(f"- {err}")
        print("\nExisting output files:")
        for p in sorted((root / "output").glob("**/*")):
            if p.is_file():
                print(f"  {p.relative_to(root)}")
        return 1

    print("Latest OpenClash output assertion OK")
    print(f"Checked YAML files: {len(files)}")
    print(f"Rule focus enabled: {enable_rule_focus}")
    print(f"Smart QoS enabled: {enable_smart_qos}")
    print(f"Input VMess LB enabled: {enable_input_vmess_lb}")
    print(f"Manual-only enabled: {smart_safe_manual_only}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

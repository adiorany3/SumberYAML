#!/usr/bin/env python3
"""Rename generated proxy names with an update date suffix.

Manual/trusted accounts from input/links.txt or input.txt are intentionally skipped.
The script updates references in OpenClash YAML, sing-box JSON, and plain
V2RayBox/NekoBox subscription TXT files when possible.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

DATE_SUFFIX_RE = re.compile(r"\s+-\s+20\d{2}-\d{2}-\d{2}$")
MANUAL_PREFIX_RE = re.compile(
    r"^(LINK|MANUAL|INPUT|TRUSTED|TRUST|FROM-LINK|FROM_LINK|BEST-LINK|FALLBACK-LINK)\b",
    re.IGNORECASE,
)
GENERIC_GROUP_TYPES = {
    "selector",
    "urltest",
    "direct",
    "block",
    "dns",
}

OPENCLASH_FILES = [
    "output/openclash-ready.yaml",
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

SINGBOX_DIR = Path("output/SingBox")
SUBSCRIPTION_DIRS = [Path("output/V2RayBox"), Path("output/NekoBox")]


def b64decode_padded(value: str) -> bytes:
    value = value.strip()
    missing = len(value) % 4
    if missing:
        value += "=" * (4 - missing)
    return base64.urlsafe_b64decode(value.encode("utf-8"))


def b64encode_unpadded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def today_string(timezone_name: str) -> str:
    env_date = os.getenv("PROXY_UPDATE_DATE") or os.getenv("UPDATE_DATE")
    if env_date:
        value = str(env_date).strip()
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
            return value
        if re.fullmatch(r"20\d{6}", value):
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    if ZoneInfo:
        return datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")


def strip_update_suffix(name: str) -> str:
    return DATE_SUFFIX_RE.sub("", str(name or "")).strip()


def with_update_suffix(name: str, date_text: str) -> str:
    base = strip_update_suffix(name)
    return f"{base} - {date_text}".strip()


def is_manual_like_name(name: Any, manual_names: Set[str]) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    base = strip_update_suffix(text)
    lowered = base.lower()
    if MANUAL_PREFIX_RE.search(base):
        return True
    if lowered in {item.lower() for item in manual_names}:
        return True
    for manual in manual_names:
        m = strip_update_suffix(manual).strip()
        if not m:
            continue
        if base == m:
            return True
        if base == f"LINK {m}" or base == f"INPUT {m}" or base == f"MANUAL {m}":
            return True
    return False


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(read_text(path))


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )


def parse_name_from_link(line: str) -> Optional[str]:
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None
    try:
        if text.startswith("vmess://"):
            payload = text[len("vmess://") :]
            data = json.loads(b64decode_padded(payload).decode("utf-8", errors="replace"))
            return str(data.get("ps") or data.get("name") or "").strip() or None
        if text.startswith(("vless://", "trojan://", "ss://")):
            parsed = urlsplit(text)
            if parsed.fragment:
                return unquote(parsed.fragment).strip() or None
            host = parsed.hostname or ""
            return host.strip() or None
    except Exception:
        return None
    return None


def collect_manual_links(root: Path) -> Tuple[Set[str], Set[str]]:
    manual_links: Set[str] = set()
    manual_names: Set[str] = set()
    for rel in ["input/links.txt", "input.txt"]:
        path = root / rel
        if not path.exists():
            continue
        for raw in read_text(path).splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "://" not in line:
                continue
            manual_links.add(line)
            name = parse_name_from_link(line)
            if name:
                manual_names.add(name)
                manual_names.add(f"LINK {name}")
                manual_names.add(f"MANUAL {name}")
                manual_names.add(f"INPUT {name}")
    return manual_links, manual_names


def make_unique_mapping(names: Sequence[str], date_text: str, manual_names: Set[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    used: Set[str] = set(names)
    for old in names:
        if is_manual_like_name(old, manual_names):
            continue
        desired = with_update_suffix(old, date_text)
        if desired == old:
            continue
        candidate = desired
        index = 2
        while candidate in used and candidate != old:
            candidate = f"{desired} #{index}"
            index += 1
        mapping[old] = candidate
        used.discard(old)
        used.add(candidate)
    return mapping


def replace_rule_target(rule: Any, mapping: Dict[str, str]) -> Any:
    if not isinstance(rule, str) or not mapping:
        return rule
    parts = [part.strip() for part in rule.split(",")]
    if len(parts) >= 2 and parts[-1] in mapping:
        parts[-1] = mapping[parts[-1]]
        return ",".join(parts)
    return rule


def apply_yaml(path: Path, root: Path, date_text: str, manual_names: Set[str]) -> Dict[str, Any]:
    result = {
        "file": str(path),
        "exists": path.exists(),
        "renamed": 0,
        "skipped_manual": 0,
        "mapping": {},
    }
    if not path.exists():
        return result

    data = load_yaml(path)
    if not isinstance(data, dict):
        return result

    proxies = data.get("proxies")
    if not isinstance(proxies, list):
        return result

    proxy_names = [str(item.get("name", "")).strip() for item in proxies if isinstance(item, dict) and item.get("name")]
    for name in proxy_names:
        if is_manual_like_name(name, manual_names):
            result["skipped_manual"] += 1
    mapping = make_unique_mapping(proxy_names, date_text, manual_names)

    if not mapping:
        return result

    for proxy in proxies:
        if isinstance(proxy, dict):
            old = str(proxy.get("name", "")).strip()
            if old in mapping:
                proxy["name"] = mapping[old]

    groups = data.get("proxy-groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            refs = group.get("proxies")
            if isinstance(refs, list):
                group["proxies"] = [mapping.get(str(ref), ref) for ref in refs]

    rules = data.get("rules")
    if isinstance(rules, list):
        data["rules"] = [replace_rule_target(rule, mapping) for rule in rules]

    dump_yaml(path, data)
    result["renamed"] = len(mapping)
    result["mapping"] = mapping
    return result


def walk_replace_refs(obj: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(obj, str):
        return mapping.get(obj, obj)
    if isinstance(obj, list):
        return [walk_replace_refs(item, mapping) for item in obj]
    if isinstance(obj, dict):
        new: Dict[str, Any] = {}
        for key, value in obj.items():
            if key in {"outbound", "final", "default", "detour"} and isinstance(value, str):
                new[key] = mapping.get(value, value)
            elif key == "outbounds" and isinstance(value, list):
                new[key] = [mapping.get(str(item), item) for item in value]
            else:
                new[key] = walk_replace_refs(value, mapping)
        return new
    return obj


def apply_singbox_json(path: Path, date_text: str, manual_names: Set[str]) -> Dict[str, Any]:
    result = {
        "file": str(path),
        "exists": path.exists(),
        "renamed": 0,
        "skipped_manual": 0,
        "mapping": {},
    }
    if not path.exists():
        return result
    try:
        data = json.loads(read_text(path))
    except Exception as exc:
        result["error"] = str(exc)
        return result
    if not isinstance(data, dict):
        return result
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        return result

    names: List[str] = []
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        tag = str(outbound.get("tag", "")).strip()
        if not tag:
            continue
        otype = str(outbound.get("type", "")).lower()
        if otype in GENERIC_GROUP_TYPES:
            continue
        names.append(tag)
        if is_manual_like_name(tag, manual_names):
            result["skipped_manual"] += 1

    mapping = make_unique_mapping(names, date_text, manual_names)
    if not mapping:
        return result

    for outbound in outbounds:
        if isinstance(outbound, dict):
            tag = str(outbound.get("tag", "")).strip()
            if tag in mapping:
                outbound["tag"] = mapping[tag]

    data = walk_replace_refs(data, mapping)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["renamed"] = len(mapping)
    result["mapping"] = mapping
    return result


def rename_vmess_line(line: str, date_text: str, manual_names: Set[str]) -> Tuple[str, bool, bool]:
    payload = line[len("vmess://") :].strip()
    data = json.loads(b64decode_padded(payload).decode("utf-8", errors="replace"))
    name = str(data.get("ps") or data.get("name") or "").strip()
    if not name:
        return line, False, False
    if is_manual_like_name(name, manual_names):
        return line, False, True
    new_name = with_update_suffix(name, date_text)
    if new_name == name:
        return line, False, False
    data["ps"] = new_name
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "vmess://" + b64encode_unpadded(raw), True, False


def rename_fragment_line(line: str, date_text: str, manual_names: Set[str]) -> Tuple[str, bool, bool]:
    parsed = urlsplit(line)
    name = unquote(parsed.fragment or "").strip()
    if not name:
        return line, False, False
    if is_manual_like_name(name, manual_names):
        return line, False, True
    new_name = with_update_suffix(name, date_text)
    if new_name == name:
        return line, False, False
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, quote(new_name, safe=""))), True, False


def apply_subscription_txt(path: Path, date_text: str, manual_links: Set[str], manual_names: Set[str]) -> Dict[str, Any]:
    result = {"file": str(path), "exists": path.exists(), "renamed": 0, "skipped_manual": 0, "errors": 0}
    if not path.exists():
        return result
    if path.name.endswith("_base64.txt") or path.name == "subscription_base64.txt":
        return result
    lines = read_text(path).splitlines()
    new_lines: List[str] = []
    changed = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if stripped in manual_links:
            result["skipped_manual"] += 1
            new_lines.append(line)
            continue
        try:
            if stripped.startswith("vmess://"):
                new_line, did, skipped = rename_vmess_line(stripped, date_text, manual_names)
            elif stripped.startswith(("vless://", "trojan://", "ss://")):
                new_line, did, skipped = rename_fragment_line(stripped, date_text, manual_names)
            else:
                new_line, did, skipped = stripped, False, False
            if skipped:
                result["skipped_manual"] += 1
            if did:
                result["renamed"] += 1
                changed = True
            new_lines.append(new_line)
        except Exception:
            result["errors"] += 1
            new_lines.append(line)
    if changed:
        write_text(path, "\n".join(new_lines).rstrip() + "\n")
        maybe_regenerate_base64(path)
    return result


def maybe_regenerate_base64(txt_path: Path) -> None:
    if not txt_path.exists():
        return
    content = read_text(txt_path).strip() + "\n"
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8") + "\n"
    candidates = []
    if txt_path.name == "all.txt":
        candidates.append(txt_path.with_name("subscription_base64.txt"))
    candidates.append(txt_path.with_name(txt_path.stem + "_base64.txt"))
    for candidate in candidates:
        if candidate.exists():
            write_text(candidate, encoded)


def collect_files(root: Path, only: Optional[str]) -> Tuple[List[Path], List[Path], List[Path]]:
    yaml_files = [root / rel for rel in OPENCLASH_FILES]
    if only == "yaml":
        return yaml_files, [], []

    json_files: List[Path] = []
    if SINGBOX_DIR.exists():
        json_files = sorted((root / SINGBOX_DIR).glob("*.json"))
    if only == "json":
        return [], json_files, []

    subscription_files: List[Path] = []
    for rel_dir in SUBSCRIPTION_DIRS:
        directory = root / rel_dir
        if directory.exists():
            subscription_files.extend(sorted(directory.glob("*.txt")))
    if only == "subscriptions":
        return [], [], subscription_files
    return yaml_files, json_files, subscription_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Append update date to generated proxy names, skipping input.txt/links.txt accounts.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--date", default="", help="Date suffix YYYY-MM-DD. Defaults to today Asia/Jakarta.")
    parser.add_argument("--timezone", default="Asia/Jakarta", help="Timezone for default date")
    parser.add_argument("--only", choices=["yaml", "json", "subscriptions"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    date_text = args.date.strip() or today_string(args.timezone)
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date_text):
        raise SystemExit(f"Invalid date {date_text!r}; expected YYYY-MM-DD")

    manual_links, manual_names = collect_manual_links(root)
    yaml_files, json_files, subscription_files = collect_files(root, args.only)

    report: Dict[str, Any] = {
        "date": date_text,
        "manual_link_count": len(manual_links),
        "manual_name_count": len(manual_names),
        "yaml": [],
        "singbox_json": [],
        "subscriptions": [],
        "totals": {"renamed": 0, "skipped_manual": 0, "errors": 0},
    }

    if args.dry_run:
        report["dry_run"] = True
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    for path in yaml_files:
        item = apply_yaml(path, root, date_text, manual_names)
        report["yaml"].append(item)
    for path in json_files:
        item = apply_singbox_json(path, date_text, manual_names)
        report["singbox_json"].append(item)
    for path in subscription_files:
        item = apply_subscription_txt(path, date_text, manual_links, manual_names)
        report["subscriptions"].append(item)

    for section in ["yaml", "singbox_json", "subscriptions"]:
        for item in report[section]:
            report["totals"]["renamed"] += int(item.get("renamed", 0) or 0)
            report["totals"]["skipped_manual"] += int(item.get("skipped_manual", 0) or 0)
            report["totals"]["errors"] += int(item.get("errors", 0) or 0)
            if item.get("error"):
                report["totals"]["errors"] += 1

    report_path = root / "output" / "Validation" / "summary_rename_proxies_with_update_date.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md_path = root / "output" / "Validation" / "summary_rename_proxies_with_update_date.md"
    md_path.write_text(
        "# Rename proxies with update date\n\n"
        f"- Date suffix: `{date_text}`\n"
        f"- Total renamed: `{report['totals']['renamed']}`\n"
        f"- Manual/trusted skipped: `{report['totals']['skipped_manual']}`\n"
        f"- Errors: `{report['totals']['errors']}`\n\n"
        "Manual accounts from `input/links.txt` and `input.txt` are intentionally not renamed.\n",
        encoding="utf-8",
    )
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 1 if report["totals"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

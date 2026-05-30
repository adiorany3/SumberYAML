#!/usr/bin/env python3
"""Create an OpenClash YAML fallback group from trusted manual input accounts.

For SumberYAML:
- Accounts from input/links.txt or input.txt are trusted/manual.
- They must not be filtered, ping-tested, quarantined, or removed.
- This script only groups the manual accounts that are already present in generated YAML files.
- It creates/updates one proxy-group, by default: fallback-link.

Recommended workflow order:
1. Generate YAML from automatic sources.
2. Validate automatic YAML.
3. Merge trusted input/links.txt into YAML.
4. Run this script.
5. Continue sing-box build/sanitize/final commit.

Report:
- output/Validation/summary_input_fallback_group_yaml.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import unquote, urlparse
import base64

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML belum tersedia. Install dengan: pip install pyyaml") from exc

DEFAULT_YAML_FILES = [
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

DEFAULT_INSERT_GROUPS = {
    "PROXY",
    "GLOBAL",
    "MANUAL",
    "SELECT",
    "FALLBACK",
    "FALLBACK CEPAT",
}

REPORT_PATH = Path("output/Validation/summary_input_fallback_group_yaml.json")


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def unique(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        text = clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def b64decode_padded(text: str) -> str:
    text = text.strip()
    text += "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text.encode()).decode("utf-8", errors="replace")


def parse_input_link_names(paths: Sequence[str]) -> List[str]:
    """Best-effort extraction of human names from input links.

    This does not validate link liveness. It only helps identify manual accounts if
    a merge script preserved original names without a LINK prefix.
    """
    names: List[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                if line.startswith("vmess://"):
                    payload = line.removeprefix("vmess://")
                    obj = json.loads(b64decode_padded(payload))
                    if isinstance(obj, dict):
                        names.append(clean_text(obj.get("ps") or obj.get("name")))
                elif line.startswith(("vless://", "trojan://")):
                    parsed = urlparse(line)
                    if parsed.fragment:
                        names.append(clean_text(unquote(parsed.fragment)))
            except Exception:
                # Link manual tetap trusted; kegagalan parse nama tidak menghentikan workflow.
                continue
    return unique(names)


def read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] gagal membaca {path}: {exc}", flush=True)
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("proxies"), list):
        data["proxies"] = []
    if not isinstance(data.get("proxy-groups"), list):
        data["proxy-groups"] = []
    return data


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )


def proxy_name(proxy: Any) -> str:
    if not isinstance(proxy, dict):
        return ""
    return clean_text(proxy.get("name"))


def is_manual_proxy(name: str, prefixes: Sequence[str], input_names: Sequence[str]) -> bool:
    if not name:
        return False
    upper_name = name.upper()
    for prefix in prefixes:
        prefix = clean_text(prefix).upper()
        if prefix and (upper_name == prefix or upper_name.startswith(prefix + " ") or upper_name.startswith(prefix + "-")):
            return True
    # If a merge script keeps the original fragment name, include exact matches too.
    input_name_set = {clean_text(n) for n in input_names if clean_text(n)}
    if name in input_name_set:
        return True
    # Common generated pattern: LINK <fragment-name>.
    for input_name in input_name_set:
        if input_name and upper_name == ("LINK " + input_name).upper():
            return True
    return False


def ensure_fallback_group(
    data: Dict[str, Any],
    group_name: str,
    manual_names: List[str],
    test_url: str,
    interval: int,
    insert_groups: Set[str],
) -> Dict[str, Any]:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        groups = []
        data["proxy-groups"] = groups

    changed = False
    existing = None
    for group in groups:
        if isinstance(group, dict) and clean_text(group.get("name")) == group_name:
            existing = group
            break

    desired_group = {
        "name": group_name,
        "type": "fallback",
        "proxies": manual_names[:],
        "url": test_url,
        "interval": int(interval),
    }

    if existing is None:
        groups.insert(0, desired_group)
        changed = True
    else:
        before = json.dumps(existing, ensure_ascii=False, sort_keys=True)
        existing.clear()
        existing.update(desired_group)
        after = json.dumps(existing, ensure_ascii=False, sort_keys=True)
        changed = before != after

    # Make the one fallback group visible from common selector/fallback groups.
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = clean_text(group.get("name"))
        if not name or name == group_name:
            continue
        proxies = group.get("proxies")
        if not isinstance(proxies, list):
            continue
        group_type = clean_text(group.get("type")).lower()
        if name.upper() in insert_groups or (name.upper() == "PROXY") or group_type in {"select", "fallback"}:
            if group_name not in proxies:
                group["proxies"] = [group_name] + [p for p in proxies if p != group_name]
                changed = True

    return {
        "changed": changed,
        "group_name": group_name,
        "manual_count": len(manual_names),
        "manual_names": manual_names,
    }


def process_file(
    path: Path,
    group_name: str,
    prefixes: Sequence[str],
    input_names: Sequence[str],
    test_url: str,
    interval: int,
    insert_groups: Set[str],
) -> Dict[str, Any]:
    item: Dict[str, Any] = {"file": str(path), "exists": path.exists(), "changed": False, "manual_count": 0}
    if not path.exists():
        return item

    data = read_yaml(path)
    if data is None:
        item["error"] = "not a valid YAML mapping"
        return item

    all_proxy_names = [proxy_name(proxy) for proxy in data.get("proxies", [])]
    manual_names = unique(
        name for name in all_proxy_names if is_manual_proxy(name, prefixes=prefixes, input_names=input_names)
    )
    item["manual_count"] = len(manual_names)

    if not manual_names:
        item["message"] = "Tidak ada akun manual trusted yang sudah masuk ke YAML. Jalankan merge_links_into_openclash_yaml.py lebih dulu."
        return item

    result = ensure_fallback_group(
        data=data,
        group_name=group_name,
        manual_names=manual_names,
        test_url=test_url,
        interval=interval,
        insert_groups=insert_groups,
    )
    item.update(result)

    if result.get("changed"):
        write_yaml(path, data)
        item["changed"] = True
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Add fallback-link group from trusted input accounts into OpenClash YAML outputs.")
    parser.add_argument("--group", default="fallback-link", help="Nama group fallback yang dibuat/diupdate.")
    parser.add_argument("--file", action="append", dest="files", help="File YAML output. Bisa dipakai berulang.")
    parser.add_argument("--input", action="append", dest="inputs", default=[], help="File input links, misalnya input/links.txt atau input.txt.")
    parser.add_argument("--manual-prefix", action="append", dest="prefixes", default=[], help="Prefix nama akun manual. Default: LINK dan INPUT.")
    parser.add_argument("--insert-to", action="append", dest="insert_to", default=[], help="Nama group yang akan diberi fallback-link. Bisa dipakai berulang.")
    parser.add_argument("--url", default="https://www.gstatic.com/generate_204", help="URL health-check fallback group.")
    parser.add_argument("--interval", type=int, default=300, help="Interval fallback check dalam detik.")
    parser.add_argument("--report", default=str(REPORT_PATH), help="Path laporan JSON.")
    args = parser.parse_args()

    files = args.files or DEFAULT_YAML_FILES
    inputs = args.inputs or ["input/links.txt", "input.txt"]
    prefixes = args.prefixes or ["LINK", "INPUT"]
    insert_groups = {clean_text(x).upper() for x in (args.insert_to or []) if clean_text(x)} or set(DEFAULT_INSERT_GROUPS)

    input_names = parse_input_link_names(inputs)

    report: Dict[str, Any] = {
        "ok": True,
        "group": args.group,
        "inputs": inputs,
        "manual_prefixes": prefixes,
        "input_name_count": len(input_names),
        "input_names_sample": input_names[:20],
        "files": [],
        "total_changed": 0,
        "total_manual_refs": 0,
    }

    for raw_file in files:
        item = process_file(
            path=Path(raw_file),
            group_name=args.group,
            prefixes=prefixes,
            input_names=input_names,
            test_url=args.url,
            interval=args.interval,
            insert_groups=insert_groups,
        )
        report["files"].append(item)
        if item.get("changed"):
            report["total_changed"] += 1
        report["total_manual_refs"] += int(item.get("manual_count") or 0)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Fallback input group report: {report_path}", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

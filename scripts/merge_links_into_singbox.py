#!/usr/bin/env python3
"""
Merge outbounds generated from input/links.txt into final sing-box JSON profiles.

Designed for SumberYAML workflow:
1) scripts/convert_openclash_to_singbox.py generates output/SingBox/lengkap.json, best-ping.json, etc.
2) scripts/convert_links_to_singbox.py generates output/SingBox/from-links.json from input/links.txt.
3) This script appends link-based vmess/vless/trojan outbounds into the final JSON profiles,
   then adds those tags to PROXY selectors and AUTO-BEST-PING/urltest groups.

This script does not modify OpenClash YAML outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROXY_TYPES = {"vmess", "vless", "trojan", "shadowsocks", "hysteria", "hysteria2", "tuic"}
GROUP_TYPES = {"selector", "urltest"}
DEFAULT_TARGETS = [
    "output/SingBox/lengkap.json",
    "output/SingBox/latest.json",
    "output/SingBox/best-ping.json",
    "output/SingBox/best.json",
    "output/SingBox/fast.json",
    "output/SingBox/gaming.json",
    "output/SingBox/streaming.json",
    "output/SingBox/social_media.json",
    "output/SingBox/working.json",
    "output/SingBox/general.json",
    "output/SingBox/lengkap-new-dns.json",
    "output/SingBox/lengkap-legacy-tun.json",
    "output/SingBox/best-ping-new-dns.json",
    "output/SingBox/best-ping-legacy-tun.json",
]

SKIP_SOURCE_NAMES = {
    "from-links.json",
    "from-links-new-dns.json",
    "from-links-legacy-tun.json",
    "vmess-links.json",
    "vless-links.json",
    "trojan-links.json",
}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_tag(value: Any, fallback: str = "proxy") -> str:
    text = str(value or fallback).strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def unique_tag(base: str, used: set[str]) -> str:
    base = clean_tag(base)
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    out = f"{base} {idx}"
    used.add(out)
    return out


def outbound_signature(outbound: Dict[str, Any]) -> Tuple[Any, ...]:
    """Build a stable signature to avoid duplicate nodes across YAML and links."""
    typ = str(outbound.get("type") or "").lower()
    server = str(outbound.get("server") or "").lower()
    port = str(outbound.get("server_port") or outbound.get("serverPort") or "")
    uuid = str(outbound.get("uuid") or "").lower()
    password = str(outbound.get("password") or "")
    method = str(outbound.get("method") or outbound.get("security") or "").lower()
    transport = outbound.get("transport") or {}
    transport_type = ""
    path = ""
    host = ""
    if isinstance(transport, dict):
        transport_type = str(transport.get("type") or "").lower()
        path = str(transport.get("path") or transport.get("service_name") or "")
        headers = transport.get("headers") or {}
        if isinstance(headers, dict):
            host = str(headers.get("Host") or headers.get("host") or "").lower()
    tls = outbound.get("tls") or {}
    sni = ""
    if isinstance(tls, dict):
        sni = str(tls.get("server_name") or "").lower()
    return (typ, server, port, uuid, password, method, transport_type, path, host, sni)


def is_proxy_outbound(outbound: Dict[str, Any]) -> bool:
    typ = str(outbound.get("type") or "").lower()
    return typ in PROXY_TYPES and bool(outbound.get("tag"))


def load_link_outbounds(source_profile: Path) -> List[Dict[str, Any]]:
    if not source_profile.exists():
        return []
    data = read_json(source_profile)
    outbounds = data.get("outbounds", []) if isinstance(data, dict) else []
    if not isinstance(outbounds, list):
        return []
    result = [item for item in outbounds if isinstance(item, dict) and is_proxy_outbound(item)]
    return result


def ensure_from_links(source_profile: Path, link_input: str, output_dir: str, convert_script: str) -> Dict[str, Any]:
    """Generate from-links.json if it is absent and input/links.txt exists."""
    info: Dict[str, Any] = {
        "generated": False,
        "source_profile": str(source_profile),
        "link_input": link_input,
    }
    if source_profile.exists():
        return info
    if not Path(link_input).exists():
        info["skipped_reason"] = f"{link_input} not found"
        return info
    if not Path(convert_script).exists():
        info["skipped_reason"] = f"{convert_script} not found"
        return info

    cmd = [sys.executable, convert_script, "--input", link_input, "--output-dir", output_dir]
    completed = subprocess.run(cmd, text=True, capture_output=True)
    info["generated"] = completed.returncode == 0
    info["returncode"] = completed.returncode
    info["stdout_tail"] = completed.stdout[-2000:]
    info["stderr_tail"] = completed.stderr[-2000:]
    if completed.returncode != 0:
        raise RuntimeError(
            "Gagal menjalankan convert_links_to_singbox.py\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return info


def add_once(values: List[str], tag: str, before_direct: bool = True) -> bool:
    if not tag or tag in values:
        return False
    if before_direct and "DIRECT" in values:
        idx = values.index("DIRECT")
        values.insert(idx, tag)
    else:
        values.append(tag)
    return True


def merge_into_config(
    target_path: Path,
    link_outbounds: Sequence[Dict[str, Any]],
    *,
    add_to_urltest: bool = True,
    add_to_selector: bool = True,
    link_prefix: str = "LINK",
) -> Dict[str, Any]:
    data = read_json(target_path)
    if not isinstance(data, dict):
        raise ValueError(f"{target_path} root JSON bukan object")

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        raise ValueError(f"{target_path} tidak punya outbounds list")

    existing_tags = {str(item.get("tag")) for item in outbounds if isinstance(item, dict) and item.get("tag")}
    existing_signatures = {
        outbound_signature(item)
        for item in outbounds
        if isinstance(item, dict) and is_proxy_outbound(item)
    }

    appended: List[str] = []
    duplicates: List[str] = []
    renamed: List[Dict[str, str]] = []
    used_tags = set(existing_tags)

    for source in link_outbounds:
        outbound = json.loads(json.dumps(source, ensure_ascii=False))
        sig = outbound_signature(outbound)
        raw_tag = clean_tag(outbound.get("tag"), "link-proxy")
        if sig in existing_signatures:
            duplicates.append(raw_tag)
            continue

        # Add prefix so link-based nodes are easy to identify in sing-box UI.
        desired_tag = raw_tag if raw_tag.upper().startswith(f"{link_prefix} ") else f"{link_prefix} {raw_tag}"
        new_tag = unique_tag(desired_tag, used_tags)
        if new_tag != raw_tag:
            renamed.append({"from": raw_tag, "to": new_tag})
        outbound["tag"] = new_tag
        outbounds.append(outbound)
        appended.append(new_tag)
        existing_signatures.add(sig)

    # Add link nodes into final routing groups so they are actually used.
    selector_updated = 0
    urltest_updated = 0
    created_selector = False
    created_urltest = False

    if appended:
        # PROXY selector is the main manual selector in these generated configs.
        proxy_selector = None
        auto_urltest = None
        for item in outbounds:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "selector" and item.get("tag") == "PROXY":
                proxy_selector = item
            if item.get("type") == "urltest" and item.get("tag") == "AUTO-BEST-PING":
                auto_urltest = item

        if add_to_urltest:
            if auto_urltest is None:
                auto_urltest = {
                    "type": "urltest",
                    "tag": "AUTO-BEST-PING",
                    "outbounds": [],
                    "url": "http://www.gstatic.com/generate_204",
                    "interval": "3m",
                    "tolerance": 50,
                    "interrupt_exist_connections": False,
                }
                outbounds.append(auto_urltest)
                created_urltest = True
            if isinstance(auto_urltest.get("outbounds"), list):
                for tag in appended:
                    if add_once(auto_urltest["outbounds"], tag, before_direct=False):
                        urltest_updated += 1

        if add_to_selector:
            if proxy_selector is None:
                selector_outbounds = []
                if add_to_urltest:
                    selector_outbounds.append("AUTO-BEST-PING")
                selector_outbounds.extend(appended)
                selector_outbounds.append("DIRECT")
                proxy_selector = {
                    "type": "selector",
                    "tag": "PROXY",
                    "outbounds": selector_outbounds,
                    "default": selector_outbounds[0],
                    "interrupt_exist_connections": False,
                }
                outbounds.append(proxy_selector)
                created_selector = True
            elif isinstance(proxy_selector.get("outbounds"), list):
                if add_to_urltest:
                    add_once(proxy_selector["outbounds"], "AUTO-BEST-PING", before_direct=True)
                for tag in appended:
                    if add_once(proxy_selector["outbounds"], tag, before_direct=True):
                        selector_updated += 1
                if not proxy_selector.get("default"):
                    proxy_selector["default"] = "AUTO-BEST-PING" if add_to_urltest else appended[0]

            # Ensure final route can use PROXY when a selector has been created.
            route = data.get("route")
            if isinstance(route, dict) and created_selector:
                route["final"] = "PROXY"

    write_json(target_path, data)

    return {
        "target": str(target_path),
        "appended_count": len(appended),
        "appended_tags": appended,
        "duplicate_count": len(duplicates),
        "duplicates_skipped": duplicates,
        "renamed": renamed,
        "selector_updated": selector_updated,
        "urltest_updated": urltest_updated,
        "created_selector": created_selector,
        "created_urltest": created_urltest,
        "total_outbounds_after": len(outbounds),
    }


def discover_targets(output_dir: Path, explicit_targets: Sequence[str]) -> List[Path]:
    if explicit_targets:
        candidates = [Path(item) for item in explicit_targets]
    else:
        candidates = [Path(item) for item in DEFAULT_TARGETS]
        # Add any other generated JSON profile except link-only outputs and summaries.
        if output_dir.exists():
            for path in sorted(output_dir.glob("*.json")):
                if path.name.startswith("summary") or path.name in SKIP_SOURCE_NAMES:
                    continue
                if path not in candidates:
                    candidates.append(path)

    out: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        if path.name.startswith("summary") or path.name in SKIP_SOURCE_NAMES:
            continue
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def copy_latest_alias(output_dir: Path) -> Optional[str]:
    latest = output_dir / "latest.json"
    lengkap = output_dir / "lengkap.json"
    if lengkap.exists():
        shutil.copyfile(lengkap, latest)
        return str(latest)
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge input/links.txt sing-box nodes into final JSON profiles.")
    parser.add_argument("--output-dir", default="output/SingBox", help="Folder output SingBox.")
    parser.add_argument("--source-profile", default="output/SingBox/from-links.json", help="Profile source hasil convert_links_to_singbox.py.")
    parser.add_argument("--link-input", default="input/links.txt", help="Input links fallback jika from-links.json belum ada.")
    parser.add_argument("--convert-script", default="scripts/convert_links_to_singbox.py", help="Script converter links fallback.")
    parser.add_argument("--target", action="append", default=[], help="Target JSON final. Bisa dipakai berulang. Jika kosong, auto-discover output/SingBox/*.json.")
    parser.add_argument("--no-urltest", action="store_true", help="Jangan masukkan link nodes ke AUTO-BEST-PING/urltest.")
    parser.add_argument("--no-selector", action="store_true", help="Jangan masukkan link nodes ke selector PROXY.")
    parser.add_argument("--prefix", default="LINK", help="Prefix tag node dari input/links.txt.")
    parser.add_argument("--make-latest", action="store_true", help="Copy lengkap.json ke latest.json setelah merge.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 jika tidak ada link valid atau target tidak ada.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    source_profile = Path(args.source_profile)

    generation_info = ensure_from_links(
        source_profile=source_profile,
        link_input=args.link_input,
        output_dir=args.output_dir,
        convert_script=args.convert_script,
    )

    link_outbounds = load_link_outbounds(source_profile)
    targets = discover_targets(output_dir, args.target)
    summaries: List[Dict[str, Any]] = []

    if not link_outbounds:
        msg = "Tidak ada outbound valid dari input/links.txt/from-links.json. Merge dilewati."
        print(f"SKIP: {msg}")
        summary = {
            "ok": not args.strict,
            "message": msg,
            "source_profile": str(source_profile),
            "generation_info": generation_info,
            "link_outbound_count": 0,
            "target_count": len(targets),
            "files": [],
        }
        write_json(output_dir / "summary_merge_links_into_singbox.json", summary)
        return 1 if args.strict else 0

    if not targets:
        msg = "Tidak ada target final JSON yang ditemukan untuk di-merge."
        print(f"SKIP: {msg}")
        summary = {
            "ok": not args.strict,
            "message": msg,
            "source_profile": str(source_profile),
            "generation_info": generation_info,
            "link_outbound_count": len(link_outbounds),
            "target_count": 0,
            "files": [],
        }
        write_json(output_dir / "summary_merge_links_into_singbox.json", summary)
        return 1 if args.strict else 0

    for target in targets:
        try:
            result = merge_into_config(
                target,
                link_outbounds,
                add_to_urltest=not args.no_urltest,
                add_to_selector=not args.no_selector,
                link_prefix=args.prefix,
            )
            summaries.append(result)
            print(f"OK: merge links -> {target} (+{result['appended_count']} node, skip dup {result['duplicate_count']})")
        except Exception as exc:
            summaries.append({"target": str(target), "error": str(exc)})
            eprint(f"ERROR: {target}: {exc}")
            if args.strict:
                break

    latest_alias = None
    if args.make_latest:
        latest_alias = copy_latest_alias(output_dir)
        if latest_alias:
            print(f"OK: updated latest alias -> {latest_alias}")

    has_error = any("error" in item for item in summaries)
    summary = {
        "ok": not has_error,
        "source_profile": str(source_profile),
        "generation_info": generation_info,
        "link_outbound_count": len(link_outbounds),
        "link_tags_source": [item.get("tag") for item in link_outbounds],
        "target_count": len(targets),
        "updated_latest_alias": latest_alias,
        "files": summaries,
    }
    write_json(output_dir / "summary_merge_links_into_singbox.json", summary)

    if args.strict and has_error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

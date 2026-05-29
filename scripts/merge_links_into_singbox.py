#!/usr/bin/env python3
"""
Force-merge vmess/vless/trojan nodes from input/links.txt / from-links.json
into final SumberYAML sing-box JSON profiles.

This script is intentionally a POST-PROCESS step. Run it AFTER:
1) convert_openclash_to_singbox.py has generated output/SingBox/*.json
2) convert_links_to_singbox.py has generated output/SingBox/from-links.json

What it does:
- reads proxy outbounds from output/SingBox/from-links.json
- appends missing LINK-prefixed outbounds to final JSON profiles
- injects those tags into PROXY selector and AUTO-BEST-PING urltest
- creates missing PROXY/AUTO-BEST-PING if needed
- updates latest.json after merge when --make-latest is used
- writes output/SingBox/summary_merge_links_into_singbox.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROXY_TYPES = {
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
    "hysteria",
    "hysteria2",
    "tuic",
}

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

LINK_ONLY_FILES = {
    "from-links.json",
    "from-links-new-dns.json",
    "from-links-legacy-tun.json",
    "vmess-links.json",
    "vless-links.json",
    "trojan-links.json",
}

SUMMARY_FILES_PREFIX = ("summary",)


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    value = f"{base} {idx}"
    used.add(value)
    return value


def is_proxy_outbound(outbound: Dict[str, Any]) -> bool:
    return (
        isinstance(outbound, dict)
        and str(outbound.get("type") or "").lower() in PROXY_TYPES
        and bool(outbound.get("tag"))
    )


def outbound_signature(outbound: Dict[str, Any]) -> Tuple[Any, ...]:
    """Avoid exact duplicate server/account entries while allowing distinct tags."""
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
    service_name = ""
    if isinstance(transport, dict):
        transport_type = str(transport.get("type") or "").lower()
        path = str(transport.get("path") or "")
        service_name = str(transport.get("service_name") or "")
        headers = transport.get("headers") or {}
        if isinstance(headers, dict):
            host = str(headers.get("Host") or headers.get("host") or "").lower()

    tls = outbound.get("tls") or {}
    sni = ""
    reality_key = ""
    if isinstance(tls, dict):
        sni = str(tls.get("server_name") or "").lower()
        reality = tls.get("reality") or {}
        if isinstance(reality, dict):
            reality_key = str(reality.get("public_key") or "")

    return (
        typ,
        server,
        port,
        uuid,
        password,
        method,
        transport_type,
        path,
        service_name,
        host,
        sni,
        reality_key,
    )


def load_link_outbounds(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    data = read_json(path)
    if not isinstance(data, dict):
        return []
    outbounds = data.get("outbounds", [])
    if not isinstance(outbounds, list):
        return []
    return [
        item
        for item in outbounds
        if isinstance(item, dict) and is_proxy_outbound(item)
    ]


def ensure_from_links(
    source_profile: Path,
    link_input: str,
    output_dir: str,
    convert_script: str,
) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "source_profile": str(source_profile),
        "link_input": link_input,
        "convert_script": convert_script,
        "generated_now": False,
    }

    if source_profile.exists():
        info["status"] = "source_profile_already_exists"
        return info

    if not Path(link_input).exists():
        info["status"] = "skipped"
        info["reason"] = f"{link_input} not found"
        return info

    raw = Path(link_input).read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        info["status"] = "skipped"
        info["reason"] = f"{link_input} is empty"
        return info

    if not Path(convert_script).exists():
        info["status"] = "skipped"
        info["reason"] = f"{convert_script} not found"
        return info

    cmd = [
        sys.executable,
        convert_script,
        "--input",
        link_input,
        "--output-dir",
        output_dir,
    ]
    completed = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )
    info["generated_now"] = completed.returncode == 0
    info["returncode"] = completed.returncode
    info["stdout_tail"] = completed.stdout[-2000:]
    info["stderr_tail"] = completed.stderr[-2000:]

    if completed.returncode != 0:
        raise RuntimeError(
            "convert_links_to_singbox.py gagal dijalankan.\n"
            f"Command: {' '.join(cmd)}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    info["status"] = "generated"
    return info


def add_once(values: List[str], tag: str, *, before_direct: bool = True) -> bool:
    if not tag or tag in values:
        return False
    if before_direct and "DIRECT" in values:
        values.insert(values.index("DIRECT"), tag)
    else:
        values.append(tag)
    return True


def ensure_route_final(data: Dict[str, Any], tag: str) -> None:
    route = data.get("route")
    if not isinstance(route, dict):
        data["route"] = {"final": tag}
        return
    if not route.get("final"):
        route["final"] = tag


def ensure_proxy_selector(
    outbounds: List[Dict[str, Any]],
    appended_tags: List[str],
    *,
    use_auto_best: bool,
) -> Tuple[Dict[str, Any], bool, int]:
    selector = None
    for item in outbounds:
        if isinstance(item, dict) and item.get("type") == "selector" and item.get("tag") == "PROXY":
            selector = item
            break

    created = False
    inserted = 0
    if selector is None:
        selector_outbounds: List[str] = []
        if use_auto_best:
            selector_outbounds.append("AUTO-BEST-PING")
        selector_outbounds.extend(appended_tags)
        selector_outbounds.append("DIRECT")
        selector = {
            "type": "selector",
            "tag": "PROXY",
            "outbounds": selector_outbounds,
            "default": selector_outbounds[0],
            "interrupt_exist_connections": False,
        }
        outbounds.append(selector)
        return selector, True, len(appended_tags)

    values = selector.get("outbounds")
    if not isinstance(values, list):
        values = []
        selector["outbounds"] = values

    if use_auto_best:
        add_once(values, "AUTO-BEST-PING", before_direct=True)
    for tag in appended_tags:
        if add_once(values, tag, before_direct=True):
            inserted += 1

    if not selector.get("default"):
        selector["default"] = "AUTO-BEST-PING" if use_auto_best else (appended_tags[0] if appended_tags else "DIRECT")

    return selector, created, inserted


def ensure_auto_best_urltest(
    outbounds: List[Dict[str, Any]],
    appended_tags: List[str],
) -> Tuple[Dict[str, Any], bool, int]:
    urltest = None
    for item in outbounds:
        if isinstance(item, dict) and item.get("type") == "urltest" and item.get("tag") == "AUTO-BEST-PING":
            urltest = item
            break

    created = False
    inserted = 0
    if urltest is None:
        urltest = {
            "type": "urltest",
            "tag": "AUTO-BEST-PING",
            "outbounds": [],
            "url": "http://www.gstatic.com/generate_204",
            "interval": "3m",
            "tolerance": 50,
            "interrupt_exist_connections": False,
        }
        outbounds.append(urltest)
        created = True

    values = urltest.get("outbounds")
    if not isinstance(values, list):
        values = []
        urltest["outbounds"] = values

    for tag in appended_tags:
        if add_once(values, tag, before_direct=False):
            inserted += 1

    return urltest, created, inserted


def inject_into_all_existing_groups(
    outbounds: List[Dict[str, Any]],
    appended_tags: List[str],
    *,
    include_all_urltests: bool,
    include_all_selectors: bool,
) -> Dict[str, int]:
    selector_updates = 0
    urltest_updates = 0

    for item in outbounds:
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        tag = item.get("tag")
        if tag in {"PROXY", "AUTO-BEST-PING"}:
            continue
        if typ == "selector" and include_all_selectors:
            values = item.get("outbounds")
            if not isinstance(values, list):
                values = []
                item["outbounds"] = values
            for node_tag in appended_tags:
                if add_once(values, node_tag, before_direct=True):
                    selector_updates += 1
        elif typ == "urltest" and include_all_urltests:
            values = item.get("outbounds")
            if not isinstance(values, list):
                values = []
                item["outbounds"] = values
            for node_tag in appended_tags:
                if add_once(values, node_tag, before_direct=False):
                    urltest_updates += 1

    return {
        "all_selector_insertions": selector_updates,
        "all_urltest_insertions": urltest_updates,
    }


def merge_into_config(
    target_path: Path,
    link_outbounds: Sequence[Dict[str, Any]],
    *,
    link_prefix: str,
    add_to_selector: bool,
    add_to_urltest: bool,
    add_to_all_selectors: bool,
    add_to_all_urltests: bool,
    force_keep_duplicate_accounts: bool,
) -> Dict[str, Any]:
    data = read_json(target_path)
    if not isinstance(data, dict):
        raise ValueError(f"{target_path} root JSON bukan object")

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list):
        raise ValueError(f"{target_path} tidak punya outbounds list")

    existing_tags = {
        str(item.get("tag"))
        for item in outbounds
        if isinstance(item, dict) and item.get("tag")
    }
    existing_signatures = {
        outbound_signature(item)
        for item in outbounds
        if isinstance(item, dict) and is_proxy_outbound(item)
    }

    used_tags = set(existing_tags)
    appended_tags: List[str] = []
    duplicate_tags: List[str] = []
    renamed: List[Dict[str, str]] = []

    for source in link_outbounds:
        outbound = json.loads(json.dumps(source, ensure_ascii=False))
        raw_tag = clean_tag(outbound.get("tag"), "link-proxy")
        sig = outbound_signature(outbound)

        if sig in existing_signatures and not force_keep_duplicate_accounts:
            duplicate_tags.append(raw_tag)
            continue

        desired = raw_tag
        if not desired.upper().startswith(f"{link_prefix.upper()} "):
            desired = f"{link_prefix} {desired}"

        final_tag = unique_tag(desired, used_tags)
        if final_tag != raw_tag:
            renamed.append({"from": raw_tag, "to": final_tag})

        outbound["tag"] = final_tag
        outbounds.append(outbound)
        existing_signatures.add(sig)
        appended_tags.append(final_tag)

    selector_created = False
    urltest_created = False
    selector_insertions = 0
    urltest_insertions = 0
    all_group_insertions = {
        "all_selector_insertions": 0,
        "all_urltest_insertions": 0,
    }

    if appended_tags:
        if add_to_urltest:
            _, urltest_created, urltest_insertions = ensure_auto_best_urltest(
                outbounds,
                appended_tags,
            )
        if add_to_selector:
            _, selector_created, selector_insertions = ensure_proxy_selector(
                outbounds,
                appended_tags,
                use_auto_best=add_to_urltest,
            )
            ensure_route_final(data, "PROXY")
        elif add_to_urltest:
            ensure_route_final(data, "AUTO-BEST-PING")

        all_group_insertions = inject_into_all_existing_groups(
            outbounds,
            appended_tags,
            include_all_urltests=add_to_all_urltests,
            include_all_selectors=add_to_all_selectors,
        )

    write_json(target_path, data)

    return {
        "target": str(target_path),
        "appended_count": len(appended_tags),
        "appended_tags": appended_tags,
        "duplicate_count": len(duplicate_tags),
        "duplicates_skipped": duplicate_tags,
        "renamed": renamed,
        "selector_created": selector_created,
        "urltest_created": urltest_created,
        "selector_insertions": selector_insertions,
        "urltest_insertions": urltest_insertions,
        **all_group_insertions,
        "total_outbounds_after": len(outbounds),
    }


def discover_targets(output_dir: Path, explicit_targets: Sequence[str]) -> List[Path]:
    candidates: List[Path] = []
    if explicit_targets:
        candidates.extend(Path(item) for item in explicit_targets)
    else:
        candidates.extend(Path(item) for item in DEFAULT_TARGETS)
        if output_dir.exists():
            for path in sorted(output_dir.glob("*.json")):
                if path.name in LINK_ONLY_FILES:
                    continue
                if path.name.startswith(SUMMARY_FILES_PREFIX):
                    continue
                candidates.append(path)

    result: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        if path.name in LINK_ONLY_FILES or path.name.startswith(SUMMARY_FILES_PREFIX):
            continue
        key = str(path.resolve())
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def copy_latest_alias(output_dir: Path) -> Optional[str]:
    lengkap = output_dir / "lengkap.json"
    latest = output_dir / "latest.json"
    if lengkap.exists():
        shutil.copyfile(lengkap, latest)
        return str(latest)
    return None


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge input/links.txt nodes into final sing-box JSON profiles."
    )
    parser.add_argument("--output-dir", default="output/SingBox")
    parser.add_argument("--source-profile", default="output/SingBox/from-links.json")
    parser.add_argument("--link-input", default="input/links.txt")
    parser.add_argument("--convert-script", default="scripts/convert_links_to_singbox.py")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--prefix", default="LINK")
    parser.add_argument("--make-latest", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-selector", action="store_true")
    parser.add_argument("--no-urltest", action="store_true")
    parser.add_argument(
        "--add-to-all-selectors",
        action="store_true",
        help="Also inject LINK nodes into every existing selector group. Default: only PROXY.",
    )
    parser.add_argument(
        "--add-to-all-urltests",
        action="store_true",
        help="Also inject LINK nodes into every existing urltest group. Default: only AUTO-BEST-PING.",
    )
    parser.add_argument(
        "--force-keep-duplicate-accounts",
        action="store_true",
        help="Keep link nodes even if the same account already exists in the YAML-derived profile.",
    )
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

    if not link_outbounds:
        msg = "Tidak ada outbound valid dari input/links.txt/from-links.json."
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
        print(f"SKIP: {msg}")
        return 1 if args.strict else 0

    if not targets:
        msg = "Tidak ada target final JSON yang ditemukan. Jalankan convert_openclash_to_singbox.py dulu."
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
        print(f"SKIP: {msg}")
        return 1 if args.strict else 0

    files: List[Dict[str, Any]] = []
    for target in targets:
        try:
            result = merge_into_config(
                target,
                link_outbounds,
                link_prefix=args.prefix,
                add_to_selector=not args.no_selector,
                add_to_urltest=not args.no_urltest,
                add_to_all_selectors=args.add_to_all_selectors,
                add_to_all_urltests=args.add_to_all_urltests,
                force_keep_duplicate_accounts=args.force_keep_duplicate_accounts,
            )
            files.append(result)
            print(
                "OK: merge links -> "
                f"{target} (+{result['appended_count']} node, "
                f"skip duplicate {result['duplicate_count']})"
            )
        except Exception as exc:
            eprint(f"ERROR: {target}: {exc}")
            files.append({"target": str(target), "error": str(exc)})
            if args.strict:
                break

    latest_alias = None
    if args.make_latest:
        latest_alias = copy_latest_alias(output_dir)
        if latest_alias:
            print(f"OK: latest.json refreshed from lengkap.json after merge -> {latest_alias}")

    has_error = any("error" in item for item in files)
    appended_total = sum(int(item.get("appended_count", 0)) for item in files)
    summary = {
        "ok": not has_error,
        "source_profile": str(source_profile),
        "generation_info": generation_info,
        "link_outbound_count": len(link_outbounds),
        "link_tags_source": [item.get("tag") for item in link_outbounds],
        "target_count": len(targets),
        "appended_total_across_files": appended_total,
        "updated_latest_alias": latest_alias,
        "files": files,
    }
    write_json(output_dir / "summary_merge_links_into_singbox.json", summary)

    if args.strict and (has_error or appended_total <= 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

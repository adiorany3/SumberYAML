#!/usr/bin/env python3
"""Force trusted manual accounts from input/links.txt/input.txt into final outputs.

Purpose for SumberYAML:
- Accounts supplied manually by the user are trusted.
- They must not be removed by alive/dead filtering, ping/strict filtering,
  quarantine, best-stable selection, or import sanitizer.
- This script runs late in the workflow, after sanitizers/builders, and appends
  the parsed manual accounts back into all final sing-box JSON profiles.
- It can also re-append the same links into OpenClash YAML outputs without using
  validation as a gate.

A manual account is only skipped when its share URI is completely unparsable by
scripts/convert_links_to_singbox.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REGULAR_TYPES = {
    "vless",
    "vmess",
    "trojan",
    "shadowsocks",
}
GROUP_TYPES = {"selector", "urltest"}
SUMMARY_PREFIXES = ("summary_", "health_")
SUMMARY_NAMES = {
    "summary.json",
    "summary_best_stable.json",
    "summary_from_links.json",
    "summary_merge_links_into_singbox.json",
    "summary_mobile_idle_reconnect_fix.json",
    "summary_dns_fallback_stable.json",
    "summary_import_sanitize.json",
    "summary_clear_quarantine.json",
    "summary_trusted_manual_accounts.json",
}
PRIVATE_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "224.0.0.0/4",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]


def log(message: str) -> None:
    print(message, flush=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(default)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_profile_json(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    if path.name in SUMMARY_NAMES:
        return False
    if path.name.startswith(SUMMARY_PREFIXES):
        return False
    if path.name.startswith("from-links-trusted"):
        return False
    if path.name in {"from-links.json", "from-links-new-dns.json", "from-links-legacy-tun.json"}:
        return False
    return True


def has_any_link(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    lowered = text.lower()
    return any(token in lowered for token in ("vmess://", "vless://", "trojan://"))


def existing_input_paths(paths: Sequence[str]) -> List[str]:
    out: List[str] = []
    for raw in paths:
        path = Path(raw)
        if has_any_link(path):
            out.append(str(path))
    return out


def run_command(cmd: Sequence[str], *, allow_fail: bool = False) -> Tuple[int, str]:
    log("$ " + " ".join(cmd))
    proc = subprocess.run(
        list(cmd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode and not allow_fail:
        raise RuntimeError(f"Command failed with exit code {proc.returncode}: {' '.join(cmd)}")
    return proc.returncode, proc.stdout or ""


def convert_manual_links(
    *,
    python_bin: str,
    convert_script: Path,
    input_paths: Sequence[str],
    output_dir: Path,
    name: str,
) -> Dict[str, Any]:
    if not input_paths:
        return {"ok": False, "message": "Tidak ada input link manual yang berisi vmess/vless/trojan.", "manual_regular": []}
    if not convert_script.exists():
        raise FileNotFoundError(f"Converter tidak ditemukan: {convert_script}")
    cmd = [python_bin, str(convert_script), "--output-dir", str(output_dir), "--name", name]
    for item in input_paths:
        cmd.extend(["--input", item])
    # Do not use --strict here. Trusted links should not fail the entire workflow
    # merely because one line is a comment/bad copy.
    run_command(cmd, allow_fail=False)
    profile_path = output_dir / f"{name}.json"
    profile = read_json(profile_path, {})
    outbounds = profile.get("outbounds") if isinstance(profile, dict) else []
    manual_regular = [deepcopy(item) for item in outbounds if isinstance(item, dict) and item.get("type") in REGULAR_TYPES]
    return {
        "ok": bool(manual_regular),
        "profile_path": str(profile_path),
        "manual_count": len(manual_regular),
        "manual_tags": [str(item.get("tag")) for item in manual_regular],
        "manual_regular": manual_regular,
    }


def unique_tag(tag: str, used: set[str]) -> str:
    base = str(tag or "LINK MANUAL").strip() or "LINK MANUAL"
    if not base.upper().startswith("LINK"):
        base = f"LINK {base}"
    if base not in used:
        used.add(base)
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    out = f"{base} {idx}"
    used.add(out)
    return out


def normalize_duration(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return default
    import re
    if re.fullmatch(r"\d+", text):
        return f"{text}s"
    if re.fullmatch(r"\d+(ms|s|m|h|d)", text):
        return text
    return default


def minimal_safe_manual(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a compatibility-cleaned manual outbound without deleting valid accounts.

    Unknown/risky optional fields are removed, but the account itself is kept as
    long as required URI-derived fields are present.
    """
    typ = str(item.get("type") or "").strip().lower()
    if typ not in REGULAR_TYPES:
        return None
    server = str(item.get("server") or "").strip()
    try:
        port = int(item.get("server_port") or item.get("port") or 0)
    except Exception:
        port = 0
    if not server or not (1 <= port <= 65535):
        return None

    out: Dict[str, Any] = {
        "type": typ,
        "tag": str(item.get("tag") or "LINK MANUAL"),
        "server": server,
        "server_port": port,
    }
    if typ in {"vless", "vmess"}:
        uuid = str(item.get("uuid") or item.get("id") or "").strip()
        if not uuid:
            return None
        out["uuid"] = uuid
    if typ == "vless":
        flow = str(item.get("flow") or "").strip()
        if flow:
            out["flow"] = flow
    if typ == "vmess":
        security = str(item.get("security") or item.get("cipher") or "auto").strip().lower()
        if security not in {"auto", "none", "zero", "aes-128-gcm", "chacha20-poly1305"}:
            security = "auto"
        out["security"] = security
        try:
            out["alter_id"] = max(0, int(item.get("alter_id") or item.get("alterId") or 0))
        except Exception:
            out["alter_id"] = 0
    if typ == "trojan":
        password = str(item.get("password") or "").strip()
        if not password:
            return None
        out["password"] = password

    tls = item.get("tls")
    if isinstance(tls, dict) and tls.get("enabled", True) is not False:
        clean_tls: Dict[str, Any] = {"enabled": True}
        server_name = tls.get("server_name") or tls.get("servername") or tls.get("sni")
        if server_name:
            clean_tls["server_name"] = str(server_name)
        if "insecure" in tls:
            clean_tls["insecure"] = bool(tls.get("insecure"))
        alpn = tls.get("alpn")
        if isinstance(alpn, list):
            clean_tls["alpn"] = [str(x) for x in alpn if str(x).strip()]
        utls = tls.get("utls")
        if isinstance(utls, dict):
            fp = str(utls.get("fingerprint") or "").strip().lower()
            if fp:
                clean_tls["utls"] = {"enabled": True, "fingerprint": fp}
        reality = tls.get("reality")
        if isinstance(reality, dict):
            pk = str(reality.get("public_key") or reality.get("publicKey") or "").strip()
            if pk:
                clean_reality = {"enabled": True, "public_key": pk}
                sid = str(reality.get("short_id") or reality.get("shortId") or "").strip()
                spx = str(reality.get("spider_x") or reality.get("spiderX") or "").strip()
                if sid:
                    clean_reality["short_id"] = sid
                if spx:
                    clean_reality["spider_x"] = spx
                clean_tls["reality"] = clean_reality
        out["tls"] = clean_tls
    elif typ == "trojan":
        out["tls"] = {"enabled": True, "server_name": server}

    transport = item.get("transport")
    if isinstance(transport, dict):
        t = str(transport.get("type") or "").strip().lower()
        if t in {"ws", "websocket"}:
            clean_transport = {"type": "ws", "path": str(transport.get("path") or "/")}
            headers = transport.get("headers")
            if isinstance(headers, dict):
                clean_headers = {str(k): str(v) for k, v in headers.items() if str(k).strip() and str(v).strip()}
                if clean_headers:
                    clean_transport["headers"] = clean_headers
            out["transport"] = clean_transport
        elif t == "grpc":
            clean_transport = {"type": "grpc"}
            service_name = transport.get("service_name") or transport.get("serviceName")
            if service_name:
                clean_transport["service_name"] = str(service_name)
            out["transport"] = clean_transport
        elif t in {"httpupgrade", "http-upgrade", "http_upgrade"}:
            # Keep httpupgrade because some trusted manual accounts require it.
            clean_transport = {"type": "httpupgrade"}
            if transport.get("path"):
                clean_transport["path"] = str(transport.get("path"))
            if transport.get("host"):
                clean_transport["host"] = str(transport.get("host"))
            out["transport"] = clean_transport
        elif t in {"http", "h2"}:
            clean_transport = {"type": "http"}
            if transport.get("path"):
                clean_transport["path"] = str(transport.get("path"))
            if transport.get("host"):
                host = transport.get("host")
                clean_transport["host"] = host if isinstance(host, list) else [str(host)]
            out["transport"] = clean_transport

    return out


def ensure_base_sections(config: Dict[str, Any], safe: bool) -> None:
    config.setdefault("log", {"level": "info", "timestamp": True})
    if not isinstance(config.get("dns"), dict):
        config["dns"] = {}
    config["dns"] = {
        "servers": [
            {"tag": "cloudflare", "address": "1.1.1.1"},
            {"tag": "google", "address": "8.8.8.8"},
        ],
        "final": "cloudflare",
    }
    if not isinstance(config.get("inbounds"), list) or not config.get("inbounds"):
        if safe:
            config["inbounds"] = [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "inet4_address": "172.19.0.1/30",
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system",
                },
                {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7893},
            ]
        else:
            config["inbounds"] = [
                {
                    "type": "tun",
                    "tag": "tun-in",
                    "address": ["172.19.0.1/30"],
                    "auto_route": True,
                    "strict_route": True,
                    "stack": "system",
                },
                {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7893},
            ]
    if not isinstance(config.get("route"), dict):
        config["route"] = {}
    config["route"].setdefault("auto_detect_interface", True)
    config["route"].setdefault("rules", [{"ip_cidr": PRIVATE_CIDRS, "outbound": "DIRECT"}])
    config["route"].setdefault("final", "PROXY")


def ensure_direct(outbounds: List[Dict[str, Any]]) -> None:
    if not any(item.get("type") == "direct" and item.get("tag") == "DIRECT" for item in outbounds):
        outbounds.append({"type": "direct", "tag": "DIRECT"})


def upsert_group(outbounds: List[Dict[str, Any]], group: Dict[str, Any], *, front: bool = True) -> Dict[str, Any]:
    for item in outbounds:
        if item.get("tag") == group["tag"] and item.get("type") in GROUP_TYPES:
            item.setdefault("outbounds", [])
            if not isinstance(item["outbounds"], list):
                item["outbounds"] = []
            for target in group.get("outbounds", []):
                if target not in item["outbounds"]:
                    item["outbounds"].append(target)
            for key, value in group.items():
                if key not in {"outbounds"}:
                    item[key] = value
            if item.get("type") == "selector" and item.get("default") not in item["outbounds"]:
                item["default"] = item["outbounds"][0]
            return item
    if front:
        outbounds.insert(0, group)
    else:
        outbounds.append(group)
    return group


def inject_manual_into_config(config: Dict[str, Any], manual_regular: List[Dict[str, Any]], *, safe: bool) -> Dict[str, Any]:
    ensure_base_sections(config, safe=safe)
    outbounds = config.setdefault("outbounds", [])
    if not isinstance(outbounds, list):
        outbounds = []
        config["outbounds"] = outbounds

    used_tags = {str(item.get("tag")) for item in outbounds if isinstance(item, dict) and item.get("tag")}
    inserted_tags: List[str] = []

    for source in manual_regular:
        item = minimal_safe_manual(source) if safe else minimal_safe_manual(source)
        if not item:
            continue
        original_tag = str(item.get("tag") or "LINK MANUAL")
        item["tag"] = unique_tag(original_tag, used_tags)
        inserted_tags.append(item["tag"])
        outbounds.append(item)

    if not inserted_tags:
        ensure_direct(outbounds)
        return config

    ensure_direct(outbounds)
    regular_tags = [str(item.get("tag")) for item in outbounds if isinstance(item, dict) and item.get("type") in REGULAR_TYPES and item.get("tag")]
    # Manual accounts are always included in stable/urltest groups, regardless of
    # quarantine reports or ping data.
    auto_tag = "AUTO-BEST-STABLE"
    upsert_group(
        outbounds,
        {
            "type": "urltest",
            "tag": auto_tag,
            "outbounds": list(dict.fromkeys(regular_tags)),
            "url": "https://www.gstatic.com/generate_204",
            "interval": "3m",
            "tolerance": 80,
            **({} if safe else {"idle_timeout": "2h", "interrupt_exist_connections": False}),
        },
        front=True,
    )
    proxy_outs = [auto_tag] + inserted_tags + [tag for tag in regular_tags if tag not in inserted_tags] + ["DIRECT"]
    upsert_group(
        outbounds,
        {
            "type": "selector",
            "tag": "PROXY",
            "outbounds": list(dict.fromkeys(proxy_outs)),
            "default": auto_tag,
            **({} if safe else {"interrupt_exist_connections": False}),
        },
        front=True,
    )
    # If AUTO-BEST-PING already exists, also add trusted manual nodes there.
    for group in outbounds:
        if not isinstance(group, dict) or group.get("type") not in GROUP_TYPES:
            continue
        if group.get("tag") in {"AUTO-BEST-PING", "AUTO-BEST-STABLE", "PROXY"} or str(group.get("tag", "")).endswith("STABIL"):
            group.setdefault("outbounds", [])
            if isinstance(group["outbounds"], list):
                for tag in inserted_tags:
                    if tag not in group["outbounds"] and group.get("tag") != tag:
                        group["outbounds"].append(tag)
                if group.get("type") == "selector" and group.get("default") not in group["outbounds"]:
                    group["default"] = group["outbounds"][0]

    valid_tags = {str(item.get("tag")) for item in outbounds if isinstance(item, dict) and item.get("tag")}
    for group in outbounds:
        if isinstance(group, dict) and group.get("type") in GROUP_TYPES and isinstance(group.get("outbounds"), list):
            group["outbounds"] = list(dict.fromkeys([tag for tag in group["outbounds"] if tag in valid_tags and tag != group.get("tag")]))
            if not group["outbounds"]:
                group["outbounds"] = inserted_tags[:] or ["DIRECT"]
            if group.get("type") == "selector" and group.get("default") not in group["outbounds"]:
                group["default"] = group["outbounds"][0]
    if config["route"].get("final") not in valid_tags:
        config["route"]["final"] = "PROXY" if "PROXY" in valid_tags else (inserted_tags[0] if inserted_tags else "DIRECT")
    return config


def build_manual_only_profile(manual_regular: List[Dict[str, Any]], *, safe: bool) -> Dict[str, Any]:
    config: Dict[str, Any] = {"outbounds": []}
    inject_manual_into_config(config, manual_regular, safe=safe)
    return config


def sync_latest_safe(output_dir: Path, preferred_name: str = "best-stable-safe.json") -> Optional[str]:
    candidates = [
        output_dir / preferred_name,
        output_dir / "mobile-stable-safe.json",
        output_dir / "fallback-stable-safe.json",
        output_dir / "lengkap-safe.json",
        output_dir / "latest-safe.json",
    ]
    for path in candidates:
        if path.exists():
            target = output_dir / "latest-safe.json"
            if path.resolve() != target.resolve():
                shutil.copyfile(path, target)
            return str(target)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Force trusted manual accounts into final YAML and sing-box JSON outputs.")
    parser.add_argument("--input", action="append", default=[], help="Trusted manual input file. Can repeat.")
    parser.add_argument("--output-dir", default="output/SingBox")
    parser.add_argument("--convert-script", default="scripts/convert_links_to_singbox.py")
    parser.add_argument("--yaml-merge-script", default="scripts/merge_links_into_openclash_yaml.py")
    parser.add_argument("--trusted-name", default="from-links-trusted")
    parser.add_argument("--skip-yaml", action="store_true")
    parser.add_argument("--preferred-latest-safe", default="best-stable-safe.json")
    args = parser.parse_args()

    python_bin = sys.executable
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    requested_inputs = args.input or [
        "input/links.txt",
        "input.txt",
        "input/vmess.txt",
        "input/vless.txt",
        "input/trojan.txt",
        "links.txt",
    ]
    input_paths = existing_input_paths(requested_inputs)

    summary: Dict[str, Any] = {
        "input_paths_checked": requested_inputs,
        "input_paths_used": input_paths,
        "trusted_policy": "manual accounts are appended after filtering, quarantine, and sanitizer; they are not removed unless unparsable",
        "json_targets": [],
        "manual_count": 0,
        "manual_tags": [],
        "yaml_merge_ran": False,
    }

    if not input_paths:
        summary["message"] = "Tidak ada trusted manual input links yang ditemukan."
        write_json(output_dir / "summary_trusted_manual_accounts.json", summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    if not args.skip_yaml and Path(args.yaml_merge_script).exists():
        cmd = [python_bin, args.yaml_merge_script, "--trusted"]
        for item in input_paths:
            cmd.extend(["--input", item])
        run_command(cmd, allow_fail=False)
        summary["yaml_merge_ran"] = True

    converted = convert_manual_links(
        python_bin=python_bin,
        convert_script=Path(args.convert_script),
        input_paths=input_paths,
        output_dir=output_dir,
        name=args.trusted_name,
    )
    manual_regular: List[Dict[str, Any]] = converted.get("manual_regular", []) or []
    summary["manual_count"] = len(manual_regular)
    summary["manual_tags"] = [str(item.get("tag")) for item in manual_regular]
    summary["converted_profile"] = converted.get("profile_path", "")

    if not manual_regular:
        summary["message"] = "Input ditemukan, tetapi tidak ada URI vmess/vless/trojan yang bisa diparse."
        write_json(output_dir / "summary_trusted_manual_accounts.json", summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # Manual-only profiles for debugging/import fallback.
    write_json(output_dir / "manual-links.json", build_manual_only_profile(manual_regular, safe=False))
    write_json(output_dir / "manual-links-safe.json", build_manual_only_profile(manual_regular, safe=True))

    for path in sorted(output_dir.glob("*.json")):
        if not is_profile_json(path):
            continue
        data = read_json(path, {})
        if not isinstance(data, dict):
            continue
        safe = path.name.endswith("-safe.json")
        before = len([item for item in data.get("outbounds", []) if isinstance(item, dict) and item.get("type") in REGULAR_TYPES]) if isinstance(data.get("outbounds"), list) else 0
        updated = inject_manual_into_config(data, manual_regular, safe=safe)
        after = len([item for item in updated.get("outbounds", []) if isinstance(item, dict) and item.get("type") in REGULAR_TYPES]) if isinstance(updated.get("outbounds"), list) else 0
        write_json(path, updated)
        summary["json_targets"].append({"path": str(path), "safe": safe, "regular_before": before, "regular_after": after, "manual_appended": max(0, after - before)})
        log(f"[OK] trusted manual accounts enforced in {path}")

    latest_safe = sync_latest_safe(output_dir, args.preferred_latest_safe)
    summary["latest_safe"] = latest_safe or ""
    write_json(output_dir / "summary_trusted_manual_accounts.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

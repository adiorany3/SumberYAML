#!/usr/bin/env python3
"""
Fetch extra V2Ray subscription sources, extract supported nodes, run a TCP alive
pre-check, and append only alive vmess/vless/trojan nodes to input/links.txt for
this workflow run.

Additionally, bucket alive nodes into provider-specific input files based on node
names, for example input/google.txt, input/oracle.txt, input/microsoft.txt,
input/amazon.txt, input/digitalocean.txt, input/melbikom.txt, input/vultr.txt, and input/r3xxe.txt.

This intentionally skips ss:// and ssr:// because they were reported as causing
OpenClash compatibility problems in this repo.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_URLS = [
    # Existing extra sources
    "https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/sub/port_443.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/detailed/vless/443.txt",
    # Additional all-account sources requested by the user
    "https://raw.githubusercontent.com/itsyebekhe/PSG/main/lite/subscriptions/xray/normal/mix",
    "https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/mix/sub.html",
    "https://raw.githubusercontent.com/Rayan-Config/C-Sub/refs/heads/main/configs/proxy.txt",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "https://raw.githubusercontent.com/Everyday-VPN/Everyday-VPN/main/subscription/main.txt",
    "https://raw.githubusercontent.com/MahsaNetConfigTopic/config/refs/heads/main/xray_final.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/trojan.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vmess_configs.txt",
    # r3xxe.eu.cc discovery sources found from public GitHub search
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub2.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub3.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub4.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
]

SUPPORTED_SCHEMES = {"vmess", "vless", "trojan"}
DROPPED_SCHEMES = {"ss", "ssr"}
LINK_RE = re.compile(r"(?i)\b(vmess|vless|trojan|ssr|ss)://[^\s'\"<>]+")

PROVIDER_BUCKETS = {
    "google": {
        "filename": "google.txt",
        "keywords": ["google", "gcp", "googlecloud", "google-cloud", "gmail", "gstatic", "googlevideo", "ytimg", "youtube", "youtu"],
    },
    "oracle": {
        "filename": "oracle.txt",
        "keywords": ["oracle", "oci", "oraclecloud", "oracle-cloud"],
    },
    "microsoft": {
        "filename": "microsoft.txt",
        "keywords": ["microsoft", "azure", "msft", "windowsazure", "azureedge"],
    },
    "amazon": {
        "filename": "amazon.txt",
        "keywords": ["amazon", "aws", "amazonaws", "ec2", "cloudfront"],
    },
    "digitalocean": {
        "filename": "digitalocean.txt",
        "keywords": ["digitalocean", "digital ocean", "digital-ocean", "digital_ocean", "do-droplet", "droplet"],
    },
    "melbikom": {
        "filename": "melbikom.txt",
        "keywords": ["melbikom", "melbi"],
    },
    "vultr": {
        "filename": "vultr.txt",
        "keywords": ["vultr"],
    },
    "r3xxe": {
        "filename": "r3xxe.txt",
        "keywords": ["r3xxe.eu.cc", "r3xxe"],
    },
}

PROVIDER_INPUT_FILENAMES = [cfg["filename"] for cfg in PROVIDER_BUCKETS.values()]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def b64_decode_text(value: str) -> Optional[str]:
    s = re.sub(r"\s+", "", value.strip())
    if not s:
        return None
    # Avoid trying to decode obvious URL-only content as one giant base64 blob.
    if "://" in s and len(s) < 4096:
        return None
    try:
        padded = s + "=" * ((4 - len(s) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        text = raw.decode("utf-8", errors="ignore")
        if "://" in text:
            return text
    except Exception:
        pass
    try:
        padded = s + "=" * ((4 - len(s) % 4) % 4)
        raw = base64.b64decode(padded.encode("utf-8"), validate=False)
        text = raw.decode("utf-8", errors="ignore")
        if "://" in text:
            return text
    except Exception:
        pass
    return None


def read_urls(args_urls: List[str], url_file: Optional[Path]) -> List[str]:
    urls: List[str] = []
    if args_urls:
        urls.extend(args_urls)
    env_urls = os.environ.get("EXTRA_SOURCE_URLS", "").strip()
    if env_urls:
        urls.extend([u.strip() for u in re.split(r"[,\n]", env_urls) if u.strip()])
    if url_file and url_file.exists():
        for line in url_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    if not urls:
        urls = list(DEFAULT_URLS)
    # preserve order, dedupe
    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def fetch_url(url: str, timeout: float) -> Tuple[bool, str, Optional[str]]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SumberYAML-extra-sources-alive/1.0",
            "Accept": "text/plain,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", errors="ignore")
        return True, text, None
    except Exception as exc:
        return False, "", str(exc)


def clean_link(link: str) -> str:
    link = link.strip()
    # Trim common trailing punctuation accidentally captured from markdown/html.
    return link.rstrip(").,;]")


def extract_links(text: str) -> List[str]:
    candidates: List[str] = []
    variants = [text]
    decoded = b64_decode_text(text)
    if decoded:
        variants.append(decoded)
    # Decode individual long base64-ish lines too.
    for line in text.splitlines():
        line = line.strip()
        if not line or "://" in line:
            continue
        if len(line) >= 16:
            d = b64_decode_text(line)
            if d:
                variants.append(d)
    for variant in variants:
        for match in LINK_RE.finditer(variant):
            candidates.append(clean_link(match.group(0)))
    seen = set()
    out = []
    for link in candidates:
        if link and link not in seen:
            seen.add(link)
            out.append(link)
    return out


def decode_vmess(link: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    payload = link.split("://", 1)[1]
    try:
        padded = payload + "=" * ((4 - len(payload) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        text = raw.decode("utf-8", errors="ignore").strip()
        data = json.loads(text)
        return data, None
    except Exception as exc:
        return None, str(exc)


def link_scheme(link: str) -> str:
    return link.split("://", 1)[0].lower() if "://" in link else ""


def parse_link_endpoint(link: str) -> Dict[str, Any]:
    scheme = link_scheme(link)
    info: Dict[str, Any] = {
        "scheme": scheme,
        "server": None,
        "port": None,
        "name": "",
        "valid": False,
        "error": None,
    }
    if scheme == "vmess":
        data, err = decode_vmess(link)
        if not data:
            info["error"] = f"vmess decode failed: {err}"
            return info
        server = str(data.get("add") or data.get("server") or "").strip()
        port_raw = data.get("port")
        name = str(data.get("ps") or data.get("name") or "").strip()
        try:
            port = int(str(port_raw).strip())
        except Exception:
            port = None
        match_parts = []
        for key in ("ps", "name", "add", "server", "host", "sni", "path", "net", "type", "tls", "aid", "scy"):
            value = data.get(key)
            if value is not None:
                match_parts.append(str(value))
        info.update({"server": server, "port": port, "name": name, "match_text": " ".join(match_parts)})
    elif scheme in {"vless", "trojan"}:
        try:
            parsed = urllib.parse.urlsplit(link)
            server = parsed.hostname or ""
            port = parsed.port
            name = urllib.parse.unquote(parsed.fragment or "").strip()
            info.update({"server": server, "port": port, "name": name, "match_text": f"{parsed.netloc} {parsed.query} {parsed.fragment}"})
        except Exception as exc:
            info["error"] = f"uri parse failed: {exc}"
            return info
    else:
        info["error"] = f"unsupported scheme: {scheme}"
        return info

    if not info["server"] or not info["port"]:
        info["error"] = "missing server or port"
        return info
    if not (1 <= int(info["port"]) <= 65535):
        info["error"] = "invalid port"
        return info
    info["valid"] = True
    return info


async def tcp_check(server: str, port: int, timeout: float) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        # Resolve first so DNS errors are visible and so asyncio.open_connection
        # does not spend too long on broken names.
        await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, server, port, type=socket.SOCK_STREAM), timeout=timeout)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout)
        peer = writer.get_extra_info("peername")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        peer_s = f"{peer[0]}:{peer[1]}" if peer else None
        return True, peer_s, None
    except Exception as exc:
        return False, None, str(exc)


async def check_all(items: List[Dict[str, Any]], timeout: float, concurrency: int) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(item: Dict[str, Any]) -> Dict[str, Any]:
        if not item.get("valid"):
            item["alive"] = False
            item["alive_error"] = item.get("error") or "invalid"
            return item
        async with sem:
            ok, peer, err = await tcp_check(str(item["server"]), int(item["port"]), timeout)
            item["alive"] = ok
            item["peer"] = peer
            item["alive_error"] = err
            return item

    return await asyncio.gather(*(one(item) for item in items))


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", urllib.parse.unquote(value or "").lower()).strip()


def provider_matches(*values: str) -> List[str]:
    """Return provider buckets matched by node name/host/link metadata.

    The primary signal remains the node name. Host/link text is used as a
    fallback because many public subscriptions use provider words in the host
    or remark variants rather than a clean node name.
    """
    norm = " ".join(normalize_name(v) for v in values if v)
    if not norm:
        return []
    matched: List[str] = []
    for bucket, cfg in PROVIDER_BUCKETS.items():
        for keyword in cfg["keywords"]:
            if keyword.lower() in norm:
                matched.append(bucket)
                break
    return matched


def write_provider_bucket_files(
    root: Path,
    output_dir: str,
    alive_items: List[Dict[str, Any]],
    report_path: Optional[Path],
) -> Dict[str, Any]:
    """Write provider-specific alive node lists under input/*.txt.

    Matching primarily uses node names, with server/link text as a fallback.
    Files are always created so workflow commits can show an explicit empty
    bucket when no alive matching node was found.
    """
    out_dir = root / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    buckets: Dict[str, List[Dict[str, Any]]] = {key: [] for key in PROVIDER_BUCKETS}
    seen_per_bucket: Dict[str, set] = {key: set() for key in PROVIDER_BUCKETS}

    for item in alive_items:
        link = str(item.get("link") or "").strip()
        name = str(item.get("name") or "").strip()
        server = str(item.get("server") or "").strip()
        match_text = str(item.get("match_text") or "").strip()
        if not link:
            continue
        for bucket in provider_matches(name, server, match_text, link):
            if link in seen_per_bucket[bucket]:
                continue
            seen_per_bucket[bucket].add(link)
            buckets[bucket].append(item)

    files: Dict[str, Dict[str, Any]] = {}
    for bucket, cfg in PROVIDER_BUCKETS.items():
        filename = cfg["filename"]
        path = out_dir / filename
        links = [str(item.get("link") or "").strip() for item in buckets[bucket] if str(item.get("link") or "").strip()]
        path.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
        files[bucket] = {
            "file": str(path.relative_to(root)),
            "count": len(links),
            "keywords": cfg["keywords"],
            "sample": [
                {
                    "scheme": item.get("scheme"),
                    "name": item.get("name"),
                    "server": item.get("server"),
                    "port": item.get("port"),
                }
                for item in buckets[bucket][:10]
            ],
        }

    report = {
        "generated_at_utc": now_iso(),
        "policy": "provider-bucket-input-files-from-alive-extra-sources-by-node-name",
        "note": "Buckets are matched primarily from node names, with server/link text fallback. Supported links are vmess/vless/trojan; ss/ssr stay skipped for OpenClash compatibility.",
        "output_dir": output_dir,
        "files": files,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def append_block(path: Path, links: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    begin = "# BEGIN EXTRA-SOURCES-ALIVE-AUTO"
    end = "# END EXTRA-SOURCES-ALIVE-AUTO"
    # Remove previous generated block if present.
    pattern = re.compile(rf"\n?{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
    existing_clean = pattern.sub("\n", existing).rstrip()
    block_lines = [begin]
    block_lines.extend(links)
    block_lines.append(end)
    block = "\n".join(block_lines)
    final = (existing_clean + "\n\n" + block + "\n").lstrip("\n")
    path.write_text(final, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch extra sources and append TCP-alive nodes to input links.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--url", action="append", default=[], help="Extra source URL; can be repeated.")
    parser.add_argument("--url-file", default="input/extra_sources_urls.txt")
    parser.add_argument("--append-to", default="input/links.txt")
    parser.add_argument("--all-output", default="input/extra_sources_all.txt")
    parser.add_argument("--alive-output", default="input/extra_sources_alive.txt")
    parser.add_argument("--provider-output-dir", default="input")
    parser.add_argument("--provider-report", default=".extra_sources_provider_buckets_report.json")
    parser.add_argument("--report", default=".extra_sources_alive_report.json")
    parser.add_argument("--fetch-timeout", type=float, default=float(os.environ.get("EXTRA_SOURCE_FETCH_TIMEOUT", "25")))
    parser.add_argument("--tcp-timeout", type=float, default=float(os.environ.get("EXTRA_SOURCE_TCP_TIMEOUT", "4")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("EXTRA_SOURCE_CONCURRENCY", "120")))
    parser.add_argument("--max-candidates", type=int, default=int(os.environ.get("EXTRA_SOURCE_MAX_CANDIDATES", "800")))
    parser.add_argument("--max-alive", type=int, default=int(os.environ.get("EXTRA_SOURCE_MAX_ALIVE", "250")))
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    url_file = root / args.url_file if args.url_file else None
    urls = read_urls(args.url, url_file)

    per_source: List[Dict[str, Any]] = []
    all_links: List[str] = []
    dropped_scheme = 0

    for url in urls:
        ok, text, err = fetch_url(url, args.fetch_timeout)
        links = extract_links(text) if ok else []
        per_source.append({
            "url": url,
            "fetch_ok": ok,
            "error": err,
            "bytes": len(text.encode("utf-8")) if text else 0,
            "extracted_links": len(links),
        })
        all_links.extend(links)

    deduped: List[str] = []
    seen = set()
    for link in all_links:
        scheme = link_scheme(link)
        if scheme in DROPPED_SCHEMES:
            dropped_scheme += 1
            continue
        if scheme not in SUPPORTED_SCHEMES:
            continue
        if link not in seen:
            seen.add(link)
            deduped.append(link)
    if args.max_candidates > 0:
        deduped = deduped[: args.max_candidates]

    parsed_items: List[Dict[str, Any]] = []
    for idx, link in enumerate(deduped, start=1):
        info = parse_link_endpoint(link)
        info["index"] = idx
        info["link"] = link
        parsed_items.append(info)

    checked = asyncio.run(check_all(parsed_items, args.tcp_timeout, args.concurrency)) if parsed_items else []
    alive_items = [item for item in checked if item.get("alive")]
    if args.max_alive > 0:
        alive_items = alive_items[: args.max_alive]

    all_output = root / args.all_output
    alive_output = root / args.alive_output
    all_output.parent.mkdir(parents=True, exist_ok=True)
    all_output.write_text("\n".join(deduped) + ("\n" if deduped else ""), encoding="utf-8")
    alive_links = [str(item["link"]) for item in alive_items]
    alive_output.write_text("\n".join(alive_links) + ("\n" if alive_links else ""), encoding="utf-8")

    provider_report_path = root / args.provider_report if args.provider_report else None
    provider_report = write_provider_bucket_files(root, args.provider_output_dir, alive_items, provider_report_path)

    if not args.no_append and alive_links:
        append_block(root / args.append_to, alive_links)

    by_scheme: Dict[str, int] = {}
    alive_by_scheme: Dict[str, int] = {}
    for item in checked:
        by_scheme[item["scheme"]] = by_scheme.get(item["scheme"], 0) + 1
        if item.get("alive"):
            alive_by_scheme[item["scheme"]] = alive_by_scheme.get(item["scheme"], 0) + 1

    report = {
        "generated_at_utc": now_iso(),
        "policy": "extra-sources-tcp-alive-vmess-vless-trojan-only",
        "note": "Alive means TCP connection to server:port succeeded before the main generator's own proxy test. SS/SSR are intentionally skipped for OpenClash compatibility.",
        "sources": per_source,
        "input_urls": urls,
        "total_extracted_raw": len(all_links),
        "dropped_ss_ssr": dropped_scheme,
        "unique_supported_candidates": len(deduped),
        "checked_candidates": len(checked),
        "alive_candidates": len(alive_items),
        "by_scheme": by_scheme,
        "alive_by_scheme": alive_by_scheme,
        "append_to": args.append_to if not args.no_append else None,
        "all_output": args.all_output,
        "alive_output": args.alive_output,
        "provider_output_dir": args.provider_output_dir,
        "provider_report": args.provider_report,
        "provider_bucket_counts": {key: value.get("count", 0) for key, value in provider_report.get("files", {}).items()},
        "sample_alive": [
            {
                "scheme": item.get("scheme"),
                "name": item.get("name"),
                "server": item.get("server"),
                "port": item.get("port"),
                "peer": item.get("peer"),
            }
            for item in alive_items[:20]
        ],
    }
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "sources": len(urls),
        "unique_supported_candidates": len(deduped),
        "alive_candidates": len(alive_items),
        "dropped_ss_ssr": dropped_scheme,
        "provider_bucket_counts": {key: value.get("count", 0) for key, value in provider_report.get("files", {}).items()},
        "report": str(report_path),
        "provider_report": str(provider_report_path) if provider_report_path else None,
    }, ensure_ascii=False, indent=2))
    # Do not fail if no alive node: generator may still use existing input links.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

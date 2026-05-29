#!/usr/bin/env python3
"""
One-shot builder for SumberYAML sing-box final output.

Use this in GitHub Actions after OpenClash YAML files are generated/validated.
It guarantees input/links.txt is merged into the final JSON because merge runs LAST.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence


def run(cmd: List[str], *, required: bool = True) -> int:
    print("RUN:", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd)
    if required and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    return completed.returncode


def has_nonempty_links(path: str) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return False
    markers = ("vmess://", "vless://", "trojan://")
    return any(marker in text.lower() for marker in markers) or len(text) > 24


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sing-box JSON and merge input links into final profiles.")
    parser.add_argument("--link-input", default="input/links.txt")
    parser.add_argument("--output-dir", default="output/SingBox")
    parser.add_argument("--skip-openclash-convert", action="store_true")
    parser.add_argument("--strict-links", action="store_true", help="Fail if input links exist but cannot be merged.")
    parser.add_argument("--add-to-all-selectors", action="store_true")
    parser.add_argument("--add-to-all-urltests", action="store_true")
    parser.add_argument("--force-keep-duplicate-accounts", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not args.skip_openclash_convert:
        if not Path("scripts/convert_openclash_to_singbox.py").exists():
            print("ERROR: scripts/convert_openclash_to_singbox.py tidak ditemukan.", file=sys.stderr)
            return 1
        run([
            sys.executable,
            "scripts/convert_openclash_to_singbox.py",
            "--also-new-dns",
            "--also-legacy-tun",
            "--make-latest",
        ])

    links_present = has_nonempty_links(args.link_input)
    if not links_present:
        print(f"INFO: {args.link_input} kosong/tidak ada. Merge link dilewati.")
        return 0

    if not Path("scripts/convert_links_to_singbox.py").exists():
        print("ERROR: scripts/convert_links_to_singbox.py tidak ditemukan.", file=sys.stderr)
        return 1 if args.strict_links else 0

    run([
        sys.executable,
        "scripts/convert_links_to_singbox.py",
        "--input",
        args.link_input,
        "--output-dir",
        args.output_dir,
    ], required=args.strict_links)

    if not Path("scripts/merge_links_into_singbox.py").exists():
        print("ERROR: scripts/merge_links_into_singbox.py tidak ditemukan.", file=sys.stderr)
        return 1 if args.strict_links else 0

    merge_cmd = [
        sys.executable,
        "scripts/merge_links_into_singbox.py",
        "--link-input",
        args.link_input,
        "--output-dir",
        args.output_dir,
        "--make-latest",
    ]
    if args.strict_links:
        merge_cmd.append("--strict")
    if args.add_to_all_selectors:
        merge_cmd.append("--add-to-all-selectors")
    if args.add_to_all_urltests:
        merge_cmd.append("--add-to-all-urltests")
    if args.force_keep_duplicate_accounts:
        merge_cmd.append("--force-keep-duplicate-accounts")

    run(merge_cmd, required=args.strict_links)
    print("OK: final sing-box JSON sudah dibuat dan input/links.txt sudah di-merge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

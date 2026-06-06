#!/usr/bin/env python3
"""Write a deterministic-but-changing marker inside output/Validation.

Purpose:
- GitHub Actions only creates a commit when `git diff --cached` sees changes.
- If generated YAML content is identical to the previous run, there is no commit.
- This marker records the successful workflow run metadata so `output/` changes on every update run.

It intentionally writes only under output/Validation so OpenClash YAML files are not modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


JAKARTA = timezone(timedelta(hours=7), name="Asia/Jakarta")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_output_fingerprints(output_dir: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    wanted = {
        "fast.yaml",
        "lite.yaml",
        "lengkap.yaml",
        "lengkap_alive.yaml",
        "strict_alive.yaml",
        "manual_only.yaml",
        "report.txt",
    }
    for name in sorted(wanted):
        path = output_dir / name
        if path.is_file():
            fingerprints[name] = sha256_file(path)
    return fingerprints


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value)


def build_marker(root: Path) -> dict[str, Any]:
    output_dir = root / "output"
    now_utc = datetime.now(timezone.utc)
    now_jakarta = now_utc.astimezone(JAKARTA)

    run_id = env("GITHUB_RUN_ID")
    run_attempt = env("GITHUB_RUN_ATTEMPT")
    run_number = env("GITHUB_RUN_NUMBER")
    sha = env("GITHUB_SHA")
    ref = env("GITHUB_REF_NAME", env("GITHUB_REF"))
    mode = env("MODE", "update")
    source = env("SOURCE", env("GITHUB_EVENT_NAME", "manual"))

    # This nonce intentionally changes each successful workflow run.
    # Use GitHub run metadata when available, otherwise timestamp for local runs.
    force_commit_nonce = "-".join(
        part for part in [run_id, run_attempt, run_number, now_utc.isoformat(timespec="seconds")] if part
    )

    marker: dict[str, Any] = {
        "schema": "sumberyaml.force-output-update.v1",
        "purpose": "Force a visible GitHub output commit after a successful update run.",
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "generated_at_asia_jakarta": now_jakarta.isoformat(timespec="seconds"),
        "force_commit_nonce": force_commit_nonce,
        "github": {
            "workflow": env("GITHUB_WORKFLOW"),
            "event_name": env("GITHUB_EVENT_NAME"),
            "run_id": run_id,
            "run_attempt": run_attempt,
            "run_number": run_number,
            "actor": env("GITHUB_ACTOR"),
            "repository": env("GITHUB_REPOSITORY"),
            "ref": env("GITHUB_REF"),
            "ref_name": ref,
            "sha": sha,
            "server_url": env("GITHUB_SERVER_URL"),
        },
        "generator": {
            "mode": mode,
            "source": source,
            "enable_proxy_test": env("ENABLE_PROXY_TEST"),
            "filter_alive_only": env("FILTER_ALIVE_ONLY"),
            "strict_alive_only": env("STRICT_ALIVE_ONLY"),
            "enable_rule_focus": env("ENABLE_RULE_FOCUS"),
            "enable_smart_qos": env("ENABLE_SMART_QOS"),
            "force_output_commit": env("FORCE_OUTPUT_COMMIT", "true"),
        },
        "output_fingerprints_sha256": collect_output_fingerprints(output_dir),
    }
    return marker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    parser.add_argument(
        "--marker",
        default=os.environ.get("FORCE_OUTPUT_MARKER_FILE", "output/Validation/last_run.json"),
        help="Marker path relative to root. Default: output/Validation/last_run.json",
    )
    parser.add_argument(
        "--text-marker",
        default="output/Validation/last_run.txt",
        help="Small text marker path relative to root. Default: output/Validation/last_run.txt",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    marker_path = root / args.marker
    text_marker_path = root / args.text_marker

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    text_marker_path.parent.mkdir(parents=True, exist_ok=True)

    marker = build_marker(root)
    marker_path.write_text(json.dumps(marker, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    text_marker_path.write_text(
        "SumberYAML forced output update marker\n"
        f"generated_at_utc={marker['generated_at_utc']}\n"
        f"generated_at_asia_jakarta={marker['generated_at_asia_jakarta']}\n"
        f"mode={marker['generator']['mode']}\n"
        f"source={marker['generator']['source']}\n"
        f"run_id={marker['github']['run_id']}\n"
        f"run_attempt={marker['github']['run_attempt']}\n"
        f"sha={marker['github']['sha']}\n"
        f"nonce={marker['force_commit_nonce']}\n",
        encoding="utf-8",
    )

    print(f"Force output marker written: {marker_path.relative_to(root)}")
    print(f"Force output text marker written: {text_marker_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

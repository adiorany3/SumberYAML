#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out = root / "output/Validation"
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "generated",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "run_number": os.getenv("GITHUB_RUN_NUMBER"),
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "mode": os.getenv("MODE"),
        "source": os.getenv("SOURCE"),
        "nonce": f"{time.time_ns()}-{random.randint(100000, 999999)}",
    }
    (out / "last_run.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "last_run.txt").write_text("\n".join(f"{k}: {v}" for k, v in payload.items()) + "\n", encoding="utf-8")
    print("Force output marker written:", out / "last_run.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

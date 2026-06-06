#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, random, time
from datetime import datetime, timezone
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--root', default='.')
args = p.parse_args()
root = Path(args.root)
out = root / 'output' / 'Validation'
out.mkdir(parents=True, exist_ok=True)
now = datetime.now(timezone.utc).isoformat()
nonce = f"{time.time_ns()}-{os.getenv('GITHUB_RUN_ID','local')}-{random.randint(1000,9999)}"
data = {
    'schema': 'sumberyaml.force-output-update.v2',
    'generated_at_utc': now,
    'nonce': nonce,
    'github_run_id': os.getenv('GITHUB_RUN_ID', ''),
    'github_run_attempt': os.getenv('GITHUB_RUN_ATTEMPT', ''),
    'github_run_number': os.getenv('GITHUB_RUN_NUMBER', ''),
    'github_sha': os.getenv('GITHUB_SHA', ''),
    'mode': os.getenv('MODE', 'update'),
    'source': os.getenv('SOURCE', ''),
}
(out / 'last_run.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
(out / 'last_run.txt').write_text('\n'.join(f"{k}={v}" for k, v in data.items()) + '\n', encoding='utf-8')
print('Force output marker written:', out / 'last_run.json')

#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml

REQUIRED_REPORTS = [
    'output/Validation/clean_responsive_rules_report.json',
    'output/Validation/last_run.json',
]
REQUIRED_GROUPS = {
    'PILIHAN-UTAMA', 'AUTO-RESPONSIF', 'FALLBACK-RESPONSIF', 'INPUT-VMESS-LB',
    'REDDIT-INPUT', 'TRAFIK-SOSMED', 'TRAFIK-BANK-MARKET', 'TRAFIK-UMUM', 'BYPASS', 'BLOKIR'
}
REQUIRED_RULE_TARGETS = {'REDDIT-INPUT', 'TRAFIK-SOSMED', 'TRAFIK-BANK-MARKET', 'TRAFIK-UMUM'}

def target(rule: str):
    parts = [p.strip() for p in str(rule).split(',')]
    if parts and parts[0].upper() == 'MATCH' and len(parts) >= 2:
        return parts[1]
    if len(parts) >= 3:
        return parts[2]
    return None

def check_yaml(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f'{path} missing']
    data = yaml.safe_load(path.read_text(encoding='utf-8', errors='replace')) or {}
    groups = {str(g.get('name')) for g in (data.get('proxy-groups') or []) if isinstance(g, dict) and g.get('name')}
    rules = [str(r) for r in (data.get('rules') or [])]
    targets = {target(r) for r in rules if target(r)}
    missing_groups = REQUIRED_GROUPS - groups
    if missing_groups:
        errors.append(f'{path}: missing groups: {sorted(missing_groups)}')
    missing_targets = REQUIRED_RULE_TARGETS - targets
    if missing_targets:
        errors.append(f'{path}: missing rule targets: {sorted(missing_targets)}')
    for r in rules:
        t = target(r)
        if t and t.upper() in {'DIRECT', 'REJECT'}:
            errors.append(f'{path}: DIRECT/REJECT still used as rule target: {r}')
    return errors

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--strict', action='store_true')
    args = ap.parse_args()
    root = Path(args.root)
    errors: list[str] = []
    for rel in REQUIRED_REPORTS:
        if not (root / rel).exists():
            errors.append(f'missing report: {rel}')
    for rel in ['output/fast.yaml', 'output/lengkap.yaml']:
        errors.extend(check_yaml(root / rel))
    if errors:
        for e in errors:
            print(e)
        return 1 if args.strict else 0
    print('Latest clean responsive Reddit routing features OK')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

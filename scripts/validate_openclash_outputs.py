#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

SPECIAL = {'DIRECT', 'REJECT', 'PASS', 'COMPATIBLE'}
BLOCKED_TYPES = {'ss', 'ssr'}

def target(rule: str) -> Optional[str]:
    parts = [p.strip() for p in str(rule).split(',')]
    if not parts:
        return None
    if parts[0].upper() == 'MATCH' and len(parts) >= 2:
        return parts[1]
    if len(parts) >= 3:
        return parts[2]
    return None

def validate(path: Path) -> List[str]:
    errors: List[str] = []
    if not path.exists():
        return errors
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8', errors='replace')) or {}
    except Exception as exc:
        return [f'{path}: YAML parse failed: {exc}']
    if not isinstance(data, dict):
        return [f'{path}: YAML root is not a map']
    proxies = data.get('proxies') or []
    groups = data.get('proxy-groups') or []
    rules = data.get('rules') or []
    pnames = {str(p.get('name')) for p in proxies if isinstance(p, dict) and p.get('name')}
    gnames = {str(g.get('name')) for g in groups if isinstance(g, dict) and g.get('name')}
    allowed = pnames | gnames | SPECIAL
    for p in proxies:
        if not isinstance(p, dict):
            continue
        ptype = str(p.get('type') or '').lower()
        if ptype in BLOCKED_TYPES:
            errors.append(f'{path}: blocked proxy type still exists: {p.get("name")} ({ptype})')
    for g in groups:
        if not isinstance(g, dict):
            continue
        name = str(g.get('name') or '')
        gtype = str(g.get('type') or '')
        refs = [str(x) for x in (g.get('proxies') or [])]
        if not refs:
            errors.append(f'{path}: empty proxy group: {name}')
        for risky in ('timeout', 'lazy'):
            if risky in g:
                errors.append(f'{path}: risky group key {risky}: {name}')
        for ref in refs:
            if ref == name:
                errors.append(f'{path}: group self-reference: {name}')
            if ref not in allowed:
                errors.append(f'{path}: invalid group reference: {name} -> {ref}')
            if gtype in {'url-test', 'fallback', 'load-balance'} and ref in {'DIRECT', 'REJECT'}:
                errors.append(f'{path}: {ref} appears in non-selector group: {name}')
    for rule in rules:
        tgt = target(str(rule))
        if tgt and tgt.upper() in {'DIRECT', 'REJECT'}:
            errors.append(f'{path}: DIRECT/REJECT used as rule target: {rule}')
        if tgt and tgt not in allowed and tgt.upper() not in {'DIRECT', 'REJECT'}:
            errors.append(f'{path}: rule target not found: {rule}')
    return errors

def main() -> int:
    paths = [Path(arg) for arg in sys.argv[1:]] or [
        Path('output/lengkap.yaml'), Path('output/lengkap_alive.yaml'), Path('output/strict_alive.yaml'),
        Path('output/lite.yaml'), Path('output/fast.yaml'), Path('output/manual_only.yaml')]
    all_errors: List[str] = []
    for path in paths:
        all_errors.extend(validate(path))
    if all_errors:
        for err in all_errors:
            print(err)
        return 1
    print('OpenClash output validation OK')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

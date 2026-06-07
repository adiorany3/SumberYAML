#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, pathlib, sys


def validate(path: pathlib.Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"invalid JSON {path}: {e}"]
    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or not outbounds:
        errors.append("outbounds is empty or missing")
        return errors
    tags = []
    for ob in outbounds:
        if not isinstance(ob, dict):
            errors.append("outbound item is not object")
            continue
        tag = ob.get("tag")
        typ = ob.get("type")
        if not tag:
            errors.append("outbound without tag")
        if not typ:
            errors.append(f"outbound {tag!r} without type")
        if typ in {"ss", "ssr", "shadowsocks"}:
            errors.append(f"unsupported outbound type: {typ}")
        tags.append(tag)
    if len(tags) != len(set(tags)):
        errors.append("duplicate outbound tags")
    tagset = set(tags)
    for ob in outbounds:
        if ob.get("type") in {"selector", "urltest"}:
            members = ob.get("outbounds")
            if not isinstance(members, list) or not members:
                errors.append(f"group {ob.get('tag')} has empty outbounds")
                continue
            for m in members:
                if m not in tagset:
                    errors.append(f"group {ob.get('tag')} references missing {m}")
    route = data.get("route") or {}
    for rule in route.get("rules", []) or []:
        target = rule.get("outbound")
        if target and target not in tagset:
            errors.append(f"route references missing outbound {target}")
    for required in ["select", "sb-auto", "direct", "block"]:
        if required not in tagset:
            errors.append(f"required outbound missing: {required}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("paths", nargs="*", default=["output/SingBox/sing-box.json"])
    ns = ap.parse_args()
    root = pathlib.Path(ns.root)
    all_errors = []
    for p in ns.paths:
        errs = validate(root / p)
        if errs:
            all_errors.extend([f"{p}: {e}" for e in errs])
        else:
            print("SING-BOX OK:", p)
    if all_errors:
        for e in all_errors:
            print("ERROR:", e, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

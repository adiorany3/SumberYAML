#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"PyYAML required: {exc}")

MAIN_OUTPUTS = [
    "fast.yaml",
    "lite.yaml",
    "lengkap.yaml",
    "lengkap_alive.yaml",
    "strict_alive.yaml",
    "manual_only.yaml",
    "openclash-ready.yaml",
    "openclash-lite-ready.yaml",
    "gaming.yaml",
    "streaming.yaml",
    "social_media.yaml",
    "working.yaml",
    "general.yaml",
]

GAME_DOMAIN_SUFFIXES = [
    # PC/platform stores
    "steampowered.com",
    "steamcommunity.com",
    "steamstatic.com",
    "steamcontent.com",
    "steamserver.net",
    "steamgames.com",
    "epicgames.com",
    "epicgames.dev",
    "unrealengine.com",
    "gog.com",
    "itch.io",
    "humblebundle.com",
    # Riot / Valorant / LoL
    "riotgames.com",
    "riotcdn.net",
    "valorant.com",
    "leagueoflegends.com",
    "lolesports.com",
    "wildrift.leagueoflegends.com",
    # Roblox / Minecraft
    "roblox.com",
    "rbxcdn.com",
    "minecraft.net",
    "mojang.com",
    # Console / publishers
    "nintendo.com",
    "nintendo.net",
    "playstation.com",
    "playstation.net",
    "sonyentertainmentnetwork.com",
    "xbox.com",
    "xboxlive.com",
    "ea.com",
    "origin.com",
    "eac-cdn.com",
    "ubisoft.com",
    "ubisoftconnect.com",
    "battle.net",
    "blizzard.com",
    "rockstargames.com",
    "take2games.com",
    # Mobile online games
    "garena.com",
    "freefiremobile.com",
    "ff.garena.com",
    "pubgmobile.com",
    "krafton.com",
    "proximabeta.com",
    "mobilelegends.com",
    "mlbbgame.com",
    "m.mobilelegends.com",
    "hoyoverse.com",
    "mihoyo.com",
    "hoyolab.com",
    "genshinimpact.com",
    "honkaiimpact3.com",
    "honkai-starrail.com",
    "zenlesszonezero.com",
    "supercell.com",
    "clashofclans.com",
    "clashroyale.com",
    "brawlstars.com",
    "callofduty.com",
    "activision.com",
    "neteasegames.com",
    "easebar.com",
    "tencentgames.com",
    "levelinfinite.com",
    "arenaofvalor.com",
    "pokemongolive.com",
    "nianticlabs.com",
    # Browser / cloud gaming
    "poki.com",
    "y8.com",
    "crazygames.com",
    "kongregate.com",
    "addictinggames.com",
    "miniclip.com",
    "now.gg",
    "geforcenow.com",
    "nvidia.com",
    "parsec.app",
]

GAME_KEYWORDS = [
    "steam",
    "epicgames",
    "riotgames",
    "valorant",
    "leagueoflegends",
    "roblox",
    "minecraft",
    "xboxlive",
    "playstation",
    "battle.net",
    "blizzard",
    "garena",
    "freefire",
    "pubgmobile",
    "mobilelegends",
    "mlbb",
    "hoyoverse",
    "mihoyo",
    "genshin",
    "honkai",
    "supercell",
    "clashofclans",
    "clashroyale",
    "brawlstars",
    "callofduty",
    "activision",
    "neteasegames",
    "crazygames",
    "geforcenow",
]

GAME_RULES = [f"DOMAIN-SUFFIX,{d},BLOCK" for d in GAME_DOMAIN_SUFFIXES]
GAME_RULES.extend(f"DOMAIN-KEYWORD,{k},BLOCK" for k in GAME_KEYWORDS)

SPECIAL_OUTBOUNDS = {"DIRECT", "REJECT"}
ALLOWED_GROUP_TYPES = {"select", "url-test", "fallback"}
RISKY_TOP_KEYS = {"tcp-concurrent", "unified-delay"}
RISKY_GROUP_KEYS = {"lazy", "timeout", "strategy"}
DROP_PROXY_TYPES = {"ss", "ssr"}


def load_yaml(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        return {"__error__": f"parse error: {exc}"}
    if not isinstance(data, dict):
        return {"__error__": "root is not mapping"}
    return data


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096),
        encoding="utf-8",
    )


def remove_game_rule_providers(data: Dict[str, Any]) -> int:
    removed = 0
    providers = data.get("rule-providers")
    if isinstance(providers, dict):
        for key in list(providers.keys()):
            if str(key).upper().startswith("GAME-BLOCK"):
                providers.pop(key, None)
                removed += 1
        if not providers:
            data.pop("rule-providers", None)
    return removed


def sanitize_top_and_proxies(data: Dict[str, Any]) -> Dict[str, int]:
    stats = {"removed_risky_top_keys": 0, "removed_unsupported_proxies": 0}
    for key in list(RISKY_TOP_KEYS):
        if key in data:
            data.pop(key, None)
            stats["removed_risky_top_keys"] += 1

    proxies = data.get("proxies") or []
    clean: List[Dict[str, Any]] = []
    removed_names = set()
    seen = set()
    if isinstance(proxies, list):
        for proxy in proxies:
            if not isinstance(proxy, dict):
                continue
            name = str(proxy.get("name") or "").strip()
            typ = str(proxy.get("type") or "").strip().lower()
            if not name or typ in DROP_PROXY_TYPES:
                if name:
                    removed_names.add(name)
                stats["removed_unsupported_proxies"] += 1
                continue
            if name in seen:
                removed_names.add(name)
                stats["removed_unsupported_proxies"] += 1
                continue
            seen.add(name)
            clean.append(proxy)
    data["proxies"] = clean

    if removed_names:
        for group in data.get("proxy-groups") or []:
            if isinstance(group, dict) and isinstance(group.get("proxies"), list):
                group["proxies"] = [p for p in group["proxies"] if str(p) not in removed_names]
    return stats


def ensure_group(data: Dict[str, Any], name: str, group: Dict[str, Any]) -> None:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        data["proxy-groups"] = groups = []
    for existing in groups:
        if isinstance(existing, dict) and str(existing.get("name")) == name:
            # Keep selector but normalize risky keys and members.
            existing.clear()
            existing.update(group)
            return
    groups.append(group)


def group_names(data: Dict[str, Any]) -> set[str]:
    return {str(g.get("name")) for g in (data.get("proxy-groups") or []) if isinstance(g, dict)}


def proxy_names(data: Dict[str, Any]) -> set[str]:
    return {str(p.get("name")) for p in (data.get("proxies") or []) if isinstance(p, dict)}


def sanitize_groups(data: Dict[str, Any]) -> int:
    removed = 0
    groups = data.get("proxy-groups") or []
    if not isinstance(groups, list):
        data["proxy-groups"] = []
        return 0
    names_p = proxy_names(data)
    names_g = {str(g.get("name")) for g in groups if isinstance(g, dict)}
    for group in groups:
        if not isinstance(group, dict):
            continue
        typ = str(group.get("type") or "select")
        if typ not in ALLOWED_GROUP_TYPES:
            group["type"] = "select"
            removed += 1
        for key in list(RISKY_GROUP_KEYS):
            if key in group:
                group.pop(key, None)
                removed += 1
        members = group.get("proxies")
        if not isinstance(members, list):
            members = []
        clean_members = []
        for item in members:
            item_s = str(item)
            if typ != "select" and item_s in SPECIAL_OUTBOUNDS:
                removed += 1
                continue
            if item_s in SPECIAL_OUTBOUNDS or item_s in names_p or item_s in names_g:
                if item_s not in clean_members:
                    clean_members.append(item_s)
            else:
                removed += 1
        if not clean_members:
            fallback = "DIRECT" if typ == "select" else None
            if fallback:
                clean_members = [fallback]
        group["proxies"] = clean_members
    return removed


def ensure_block_default_groups(data: Dict[str, Any]) -> None:
    groups = group_names(data)
    proxies = proxy_names(data)

    if "DEFAULT" not in groups:
        base_members = []
        for cand in ["AUTO", "FALLBACK", "PROXY"]:
            if cand in groups:
                base_members.append(cand)
        if not base_members:
            base_members = sorted(list(proxies))[:20]
        if not base_members:
            base_members = ["DIRECT"]
        ensure_group(data, "DEFAULT", {"name": "DEFAULT", "type": "select", "proxies": base_members + (["DIRECT"] if "DIRECT" not in base_members else [])})

    # BLOCK is selector only; REJECT is allowed here but never directly in rules.
    ensure_group(data, "BLOCK", {"name": "BLOCK", "type": "select", "proxies": ["REJECT", "DIRECT", "DEFAULT"]})


def clean_existing_game_rules(rules: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    inline_set = set(GAME_RULES)
    for raw in rules:
        text = str(raw).strip()
        if not text:
            continue
        upper = text.upper()
        if upper.startswith("RULE-SET,GAME-BLOCK"):
            continue
        if text in inline_set:
            continue
        # Remove old direct provider remnants, but keep unrelated rules.
        cleaned.append(text)
    return cleaned


def insert_game_rules(data: Dict[str, Any]) -> Dict[str, int]:
    rules = data.get("rules") or []
    if not isinstance(rules, list):
        rules = []
    existing = clean_existing_game_rules(rules)
    inserted = []
    existing_set = set(existing)
    for rule in GAME_RULES:
        if rule not in existing_set:
            inserted.append(rule)
            existing_set.add(rule)
    # Game block first, before other app routing and before MATCH.
    data["rules"] = inserted + existing
    return {"inserted_game_rules": len(inserted), "total_game_rules": len(GAME_RULES)}


def validate_no_rule_provider(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    providers = data.get("rule-providers")
    if isinstance(providers, dict):
        bad = [k for k in providers if str(k).upper().startswith("GAME-BLOCK")]
        if bad:
            errors.append("GAME-BLOCK rule-providers remain: " + ", ".join(map(str, bad)))
    for rule in data.get("rules") or []:
        text = str(rule)
        if text.upper().startswith("RULE-SET,GAME-BLOCK"):
            errors.append("GAME-BLOCK RULE-SET remains: " + text)
        if text.endswith(",DIRECT") or text.endswith(",REJECT"):
            errors.append("DIRECT/REJECT direct rule target remains: " + text)
    return errors


def process_file(path: Path) -> Dict[str, Any]:
    report: Dict[str, Any] = {"file": str(path), "changed": False, "errors": []}
    data = load_yaml(path)
    if data is None:
        report["skipped"] = "missing"
        return report
    if "__error__" in data:
        report["errors"].append(data["__error__"])
        return report

    before = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)
    report["removed_game_rule_providers"] = remove_game_rule_providers(data)
    stats = sanitize_top_and_proxies(data)
    report.update(stats)
    ensure_block_default_groups(data)
    report["removed_invalid_group_items"] = sanitize_groups(data)
    report.update(insert_game_rules(data))
    report["errors"].extend(validate_no_rule_provider(data))
    after = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)
    if before != after:
        dump_yaml(path, data)
        report["changed"] = True
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply OpenClash-safe inline game blocking rules without rule-providers.")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    output = root / "output"
    reports: List[Dict[str, Any]] = []
    for name in MAIN_OUTPUTS:
        reports.append(process_file(output / name))
    validation_dir = output / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "policy": "inline-safe-game-block-no-rule-providers",
        "reason": "Use inline DOMAIN-SUFFIX/DOMAIN-KEYWORD rules because rule-providers can fail on some OpenClash/core combinations.",
        "files_processed": len([r for r in reports if not r.get("skipped")]),
        "game_rule_count": len(GAME_RULES),
        "reports": reports,
    }
    (validation_dir / "game_block_inline_safe_report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    error_count = sum(len(r.get("errors") or []) for r in reports)
    if error_count:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 1
    print(f"Applied inline-safe game blocking to {summary['files_processed']} YAML files; rules={len(GAME_RULES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

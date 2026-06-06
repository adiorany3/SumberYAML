#!/usr/bin/env python3
"""Add OpenClash-safe inline game blocking rules.

This finalizer intentionally avoids rule-providers because several OpenClash
installations fail on provider fetch/path/format issues. It writes plain Clash
`DOMAIN-SUFFIX,...,BLOCK` and selected `DOMAIN-KEYWORD,...,BLOCK` rules.

Policy:
- No direct REJECT rule targets; rules target the selector group BLOCK.
- REJECT is allowed only as a proxy option inside the selector group BLOCK.
- No load-balance/relay/script/rule-providers are introduced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Sequence, Tuple

import yaml

OUTPUT_YAML_NAMES = [
    "lengkap.yaml",
    "lengkap_alive.yaml",
    "strict_alive.yaml",
    "lite.yaml",
    "fast.yaml",
    "manual_only.yaml",
    "openclash-ready.yaml",
    "openclash-lite-ready.yaml",
    "gaming.yaml",
    "streaming.yaml",
    "social_media.yaml",
    "general.yaml",
    "working.yaml",
]

# Browser/web game domains + popular online game service domains.
# Keep lowercase, no leading dot.
GAME_DOMAIN_SUFFIXES: List[str] = sorted(set([
    # Requested explicitly
    "callofwar.com",
    # Bytro / strategy browser games similar to Call of War
    "bytro.com",
    "supremacy1914.com",
    "ironorder1919.com",
    "conflictnations.com",
    "conflictofnations.com",
    "newworldempires.com",
    "thirtykingdoms.com",
    # InnoGames / browser strategy & city games
    "tribalwars.net",
    "tribalwars.com",
    "grepolis.com",
    "forgeofempires.com",
    "elvenar.com",
    "the-west.net",
    "innogames.com",
    # Other classic web/browser games
    "ikariam.gameforge.com",
    "ikariam.com",
    "ogame.gameforge.com",
    "ogame.org",
    "travian.com",
    "travian.com.tr",
    "travian.com.au",
    "travian.co.uk",
    "travian.us",
    "travian-games.com",
    "erepublik.com",
    "torn.com",
    "nationstates.net",
    "hordes.io",
    "ev.io",
    "krunker.io",
    "shellshock.io",
    "surviv.io",
    "zombsroyale.io",
    "moomoo.io",
    "slither.io",
    "agar.io",
    "diep.io",
    "paper-io.com",
    "paper.io",
    "bonk.io",
    "venge.io",
    "warbrokers.io",
    "littlebigsnake.com",
    "skribbl.io",
    "gartic.io",
    "garticphone.com",
    "geoguessr.com",
    # Web game portals
    "poki.com",
    "crazygames.com",
    "y8.com",
    "miniclip.com",
    "kongregate.com",
    "armor-games.com",
    "armorgames.com",
    "newgrounds.com",
    "addictinggames.com",
    "coolmathgames.com",
    "friv.com",
    "kizi.com",
    "agame.com",
    "gamesgames.com",
    "silvergames.com",
    "mathplayground.com",
    "iogames.space",
    "now.gg",
    # Large online game platforms and stores
    "steampowered.com",
    "steamcommunity.com",
    "steamstatic.com",
    "steamcontent.com",
    "steamgames.com",
    "valvesoftware.com",
    "epicgames.com",
    "epicgames.dev",
    "unrealengine.com",
    "riotgames.com",
    "riotcdn.net",
    "leagueoflegends.com",
    "playvalorant.com",
    "roblox.com",
    "rbxcdn.com",
    "minecraft.net",
    "mojang.com",
    "nintendo.com",
    "nintendo.net",
    "playstation.com",
    "playstation.net",
    "xbox.com",
    "xboxlive.com",
    "ea.com",
    "origin.com",
    "ubisoft.com",
    "ubi.com",
    "battle.net",
    "blizzard.com",
    "rockstargames.com",
    "gta5-mods.com",
    # Mobile/online games often also reachable via web/app APIs
    "garena.com",
    "freefiremobile.com",
    "pubgmobile.com",
    "krafton.com",
    "mobilelegends.com",
    "moonton.com",
    "hoyoverse.com",
    "mihoyo.com",
    "genshinimpact.com",
    "honkaiimpact3.com",
    "honkai-star-rail.com",
    "zenlesszonezero.com",
    "supercell.com",
    "clashofclans.com",
    "clashroyale.com",
    "brawlstars.com",
    "callofduty.com",
    "activision.com",
    "neteasegames.com",
    "netease.com",
    # Cloud gaming / browser playable platforms
    "geforcenow.com",
    "nvidia.com",
    "xboxcloudgaming.com",
    "play.geforcenow.com",
    "boosteroid.com",
    "airgpu.com",
]))

# Keywords are intentionally conservative to avoid overblocking unrelated web.
GAME_DOMAIN_KEYWORDS: List[str] = sorted(set([
    "gameforge",
    "hoyoverse",
    "moonton",
    "steam",
    "roblox",
    "valorant",
    "pubg",
    "freefire",
    "mobilelegends",
    "callofwar",
]))

UNSUPPORTED_GROUP_TYPES = {"load-balance", "relay"}
RISKY_TOP_LEVEL_KEYS = {"rule-providers"}


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        text = fh.read()
    if not text.strip():
        return {}
    return yaml.safe_load(text) or {}


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data,
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def normalize_rule(rule: Any) -> str:
    if isinstance(rule, str):
        return rule.strip()
    return ""


def rule_target(rule: str) -> str:
    parts = [part.strip() for part in rule.split(",")]
    if len(parts) >= 3:
        return parts[-1]
    if len(parts) == 2 and parts[0].upper() in {"MATCH", "FINAL"}:
        return parts[-1]
    return ""


def is_existing_game_block_rule(rule: str) -> bool:
    if not rule:
        return False
    upper = rule.upper()
    if "GAME-BLOCK" in upper:
        return True
    parts = [part.strip() for part in rule.split(")")]
    parts = [part.strip() for part in rule.split(",")]
    if len(parts) < 3:
        return False
    kind = parts[0].upper()
    value = parts[1].lower()
    target = parts[-1]
    if target != "BLOCK":
        return False
    if kind in {"DOMAIN-SUFFIX", "DOMAIN", "DOMAIN-KEYWORD"}:
        if value in GAME_DOMAIN_SUFFIXES or value in GAME_DOMAIN_KEYWORDS:
            return True
        if any(value == d or value.endswith("." + d) for d in GAME_DOMAIN_SUFFIXES):
            return True
    return False


def ensure_block_group(data: MutableMapping[str, Any]) -> None:
    groups = as_list(data.get("proxy-groups"))
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    block_found = False

    for group in groups:
        if not isinstance(group, dict):
            continue
        name = str(group.get("name", "")).strip()
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        gtype = str(group.get("type", "select")).strip()
        if gtype in UNSUPPORTED_GROUP_TYPES:
            # Convert unsupported group types to select rather than leaving an
            # OpenClash-incompatible config behind.
            group["type"] = "select"
            group.pop("strategy", None)
        for key in ("lazy", "timeout", "tcp-concurrent", "unified-delay"):
            group.pop(key, None)
        proxies = [str(p).strip() for p in as_list(group.get("proxies")) if str(p).strip()]
        if name == "BLOCK":
            block_found = True
            group["type"] = "select"
            # Keep REJECT inside selector only.
            ordered = ["REJECT", "DIRECT"]
            for p in proxies:
                if p not in ordered:
                    ordered.append(p)
            group["proxies"] = ordered
        else:
            # DIRECT/REJECT are allowed only in selectors. They should not be
            # options for url-test/fallback groups because some OpenClash builds
            # handle that poorly.
            if group.get("type") != "select":
                proxies = [p for p in proxies if p not in {"DIRECT", "REJECT"}]
            group["proxies"] = proxies
        cleaned.append(group)

    if not block_found:
        cleaned.append({"name": "BLOCK", "type": "select", "proxies": ["REJECT", "DIRECT"]})

    data["proxy-groups"] = cleaned


def build_game_rules() -> List[str]:
    rules: List[str] = []
    for domain in GAME_DOMAIN_SUFFIXES:
        rules.append(f"DOMAIN-SUFFIX,{domain},BLOCK")
    for keyword in GAME_DOMAIN_KEYWORDS:
        rules.append(f"DOMAIN-KEYWORD,{keyword},BLOCK")
    return rules


def rewrite_rules(data: MutableMapping[str, Any]) -> Tuple[int, int]:
    original_rules = [normalize_rule(r) for r in as_list(data.get("rules"))]
    original_rules = [r for r in original_rules if r]

    # Remove old provider-based rules, old inline game rules, and risky direct REJECT targets.
    filtered: List[str] = []
    removed = 0
    for rule in original_rules:
        upper = rule.upper()
        if upper.startswith("RULE-SET,GAME-BLOCK") or "GAME-BLOCK" in upper:
            removed += 1
            continue
        if is_existing_game_block_rule(rule):
            removed += 1
            continue
        target = rule_target(rule)
        if target == "REJECT":
            # Preserve policy: target BLOCK selector instead of direct REJECT.
            parts = [p.strip() for p in rule.split(",")]
            parts[-1] = "BLOCK"
            rule = ",".join(parts)
        filtered.append(rule)

    new_game_rules = build_game_rules()
    # Insert game blocks at the top so web/app game domains are blocked before
    # category routing or MATCH rules.
    seen = set()
    merged: List[str] = []
    inserted = 0
    for rule in new_game_rules + filtered:
        if rule not in seen:
            seen.add(rule)
            merged.append(rule)
            if rule in new_game_rules:
                inserted += 1
    data["rules"] = merged
    return inserted, removed


def clean_rule_providers(data: MutableMapping[str, Any]) -> bool:
    if "rule-providers" in data:
        providers = data.get("rule-providers")
        changed = False
        if isinstance(providers, dict):
            for key in list(providers.keys()):
                if str(key).upper().startswith("GAME-BLOCK"):
                    providers.pop(key, None)
                    changed = True
            if not providers:
                data.pop("rule-providers", None)
                changed = True
        else:
            data.pop("rule-providers", None)
            changed = True
        return changed
    return False


def process_file(path: Path) -> Dict[str, Any]:
    data = load_yaml(path)
    if not isinstance(data, dict):
        return {"file": str(path), "status": "skipped", "reason": "top-level YAML is not a mapping"}

    before_text = path.read_text(encoding="utf-8") if path.exists() else ""
    provider_changed = clean_rule_providers(data)
    ensure_block_group(data)
    inserted, removed = rewrite_rules(data)
    dump_yaml(path, data)
    after_text = path.read_text(encoding="utf-8")

    return {
        "file": str(path),
        "status": "updated" if before_text != after_text else "unchanged",
        "game_rules_inserted": inserted,
        "old_game_rules_removed": removed,
        "game_rule_providers_removed": provider_changed,
    }


def find_yaml_files(root: Path, names: Sequence[str]) -> List[Path]:
    output = root / "output"
    files = []
    for name in names:
        path = output / name
        if path.exists():
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=None, help="Specific YAML files to process")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.files:
        files = [Path(f).resolve() for f in args.files if Path(f).exists()]
    else:
        files = find_yaml_files(root, OUTPUT_YAML_NAMES)

    reports = []
    for path in files:
        reports.append(process_file(path))

    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    report_path = validation_dir / "game_block_inline_safe_report.json"
    report = {
        "policy": "inline-safe-game-block-expanded-web-games",
        "target_group": "BLOCK",
        "domain_suffix_count": len(GAME_DOMAIN_SUFFIXES),
        "domain_keyword_count": len(GAME_DOMAIN_KEYWORDS),
        "explicitly_added": ["callofwar.com"],
        "files": reports,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Game block inline-safe report written: {report_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

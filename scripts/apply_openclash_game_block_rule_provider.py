#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"ERROR: PyYAML required: {exc}", file=sys.stderr)
    sys.exit(2)

DEFAULT_OWNER_REPO = os.environ.get("GITHUB_REPOSITORY", "adiorany3/SumberYAML")
DEFAULT_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
GAME_DOMAIN_PROVIDER = "GAME-BLOCK-DOMAIN"
GAME_CLASSICAL_PROVIDER = "GAME-BLOCK-CLASSICAL"
GAME_RULES = [
    f"RULE-SET,{GAME_CLASSICAL_PROVIDER},BLOCK",
    f"RULE-SET,{GAME_DOMAIN_PROVIDER},BLOCK",
]
SPECIAL_OUTBOUNDS = {"DIRECT", "REJECT"}
TOP_OUTPUTS = [
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
    "general.yaml",
    "working.yaml",
]

DOMAIN_PAYLOAD = [
    "+.steampowered.com", "+.steamcommunity.com", "+.steamstatic.com", "+.steamcontent.com",
    "+.steamserver.net", "+.steamgames.com", "+.epicgames.com", "+.epicgames.dev",
    "+.unrealengine.com", "+.riotgames.com", "+.leagueoflegends.com", "+.valorant.com",
    "+.roblox.com", "+.rbxcdn.com", "+.minecraft.net", "+.minecraftservices.com",
    "+.mojang.com", "+.nintendo.net", "+.nintendo.com", "+.playstation.com",
    "+.playstation.net", "+.sonyentertainmentnetwork.com", "+.xboxlive.com", "+.xbox.com",
    "+.ea.com", "+.origin.com", "+.ubisoft.com", "+.uplay.com", "+.battle.net",
    "+.battlenet.com", "+.blizzard.com", "+.rockstargames.com", "+.socialclub.rockstargames.com",
    "+.garena.com", "+.freefiremobile.com", "+.pubgmobile.com", "+.krafton.com",
    "+.tencentgames.com", "+.moonton.com", "+.mobilelegends.com", "+.hoyoverse.com",
    "+.mihoyo.com", "+.hoyolab.com", "+.genshinimpact.com", "+.honkaiimpact3.com",
    "+.zenlesszonezero.com", "+.supercell.com", "+.clashofclans.com", "+.clashroyale.com",
    "+.brawlstars.com", "+.nianticlabs.com", "+.pokemon.com", "+.activision.com",
    "+.callofduty.com", "+.warzone.com", "+.neteasegames.com", "+.miniclip.com",
    "+.poki.com", "+.y8.com", "+.crazygames.com", "+.kongregate.com",
    "+.armorgames.com", "+.itch.io", "+.now.gg", "+.geforcenow.com",
]

CLASSICAL_PAYLOAD = [
    "DOMAIN-KEYWORD,mobilelegends", "DOMAIN-KEYWORD,mlbb", "DOMAIN-KEYWORD,moonton",
    "DOMAIN-KEYWORD,freefire", "DOMAIN-KEYWORD,pubgmobile", "DOMAIN-KEYWORD,valorant",
    "DOMAIN-KEYWORD,leagueoflegends", "DOMAIN-KEYWORD,riotgames", "DOMAIN-KEYWORD,roblox",
    "DOMAIN-KEYWORD,steam", "DOMAIN-KEYWORD,epicgames", "DOMAIN-KEYWORD,genshin",
    "DOMAIN-KEYWORD,hoyoverse", "DOMAIN-KEYWORD,honkai", "DOMAIN-KEYWORD,minecraft",
    "DOMAIN-KEYWORD,clashofclans", "DOMAIN-KEYWORD,clashroyale", "DOMAIN-KEYWORD,brawlstars",
    "DOMAIN-KEYWORD,garena", "DOMAIN-KEYWORD,playstation", "DOMAIN-KEYWORD,xboxlive",
    "DOMAIN-KEYWORD,nintendo", "DOMAIN-KEYWORD,battlenet", "DOMAIN-KEYWORD,blizzard",
    "DOMAIN-KEYWORD,warzone", "DOMAIN-KEYWORD,callofduty", "DOMAIN-KEYWORD,rockstargames",
    "DOMAIN-KEYWORD,crazygames", "DOMAIN-KEYWORD,poki", "DOMAIN-KEYWORD,geforcenow",
]


def safe_load_yaml(path: Path) -> Dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as exc:
        print(f"WARNING: skip {path}: YAML parse error: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"WARNING: skip {path}: YAML root is not mapping")
        return None
    return data


def dump_yaml(path: Path, data: Dict[str, Any]) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)
    path.write_text(text, encoding="utf-8")


def write_provider_files(root: Path) -> Dict[str, str]:
    provider_dir = root / "rules" / "providers"
    provider_dir.mkdir(parents=True, exist_ok=True)
    domain_path = provider_dir / "game_block_domain.yaml"
    classical_path = provider_dir / "game_block_classical.yaml"
    domain_path.write_text(yaml.safe_dump({"payload": DOMAIN_PAYLOAD}, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    classical_path.write_text(yaml.safe_dump({"payload": CLASSICAL_PAYLOAD}, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return {"domain": str(domain_path), "classical": str(classical_path)}


def provider_url(repo: str, branch: str, rel: str) -> str:
    repo = repo.strip().strip("/") or DEFAULT_OWNER_REPO
    branch = branch.strip() or DEFAULT_BRANCH
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"


def ensure_block_group(data: Dict[str, Any]) -> bool:
    groups = data.setdefault("proxy-groups", [])
    if not isinstance(groups, list):
        data["proxy-groups"] = groups = []
    existing_names = {str(g.get("name")): g for g in groups if isinstance(g, dict)}
    block = existing_names.get("BLOCK")
    desired = ["REJECT", "DIRECT"]
    for extra in ["DEFAULT", "PROXY", "AUTO", "FALLBACK"]:
        if extra in existing_names and extra not in desired:
            desired.append(extra)
    if block is None:
        groups.append({"name": "BLOCK", "type": "select", "proxies": desired})
        return True
    changed = False
    if block.get("type") != "select":
        block["type"] = "select"
        changed = True
    proxies = block.get("proxies")
    if not isinstance(proxies, list):
        proxies = []
    new_proxies: List[str] = []
    for item in desired + [str(x) for x in proxies]:
        if item and item not in new_proxies:
            new_proxies.append(item)
    if proxies != new_proxies:
        block["proxies"] = new_proxies
        changed = True
    # Strip risky keys if an old finalizer created BLOCK differently.
    for key in ["url", "interval", "tolerance", "lazy", "timeout", "strategy"]:
        if key in block and block.get("type") == "select":
            block.pop(key, None)
            changed = True
    return changed


def ensure_rule_providers(data: Dict[str, Any], repo: str, branch: str) -> bool:
    providers = data.setdefault("rule-providers", {})
    if not isinstance(providers, dict):
        data["rule-providers"] = providers = {}
    desired = {
        GAME_DOMAIN_PROVIDER: {
            "type": "http",
            "behavior": "domain",
            "url": provider_url(repo, branch, "rules/providers/game_block_domain.yaml"),
            "path": "./rule_provider/game_block_domain.yaml",
            "interval": 86400,
        },
        GAME_CLASSICAL_PROVIDER: {
            "type": "http",
            "behavior": "classical",
            "url": provider_url(repo, branch, "rules/providers/game_block_classical.yaml"),
            "path": "./rule_provider/game_block_classical.yaml",
            "interval": 86400,
        },
    }
    changed = False
    for name, config in desired.items():
        if providers.get(name) != config:
            providers[name] = config
            changed = True
    return changed


def insert_game_rules(data: Dict[str, Any]) -> bool:
    rules = data.setdefault("rules", [])
    if not isinstance(rules, list):
        data["rules"] = rules = []
    old = [str(r).strip() for r in rules if str(r).strip()]
    cleaned = [r for r in old if not r.startswith("RULE-SET,GAME-BLOCK-")]
    # Keep LAN/private bypass rules first if present; then game block rules before all app routing.
    bypass_prefixes = (
        "IP-CIDR,127.", "IP-CIDR,10.", "IP-CIDR,172.16.", "IP-CIDR,192.168.",
        "IP-CIDR,169.254.", "IP-CIDR6,", "GEOIP,PRIVATE", "DOMAIN-SUFFIX,local",
    )
    insert_at = 0
    while insert_at < len(cleaned) and cleaned[insert_at].upper().startswith(bypass_prefixes):
        insert_at += 1
    new_rules = cleaned[:insert_at] + GAME_RULES + cleaned[insert_at:]
    if new_rules != old:
        data["rules"] = new_rules
        return True
    return False


def output_yaml_files(root: Path) -> List[Path]:
    output = root / "output"
    paths = []
    for name in TOP_OUTPUTS:
        path = output / name
        if path.exists():
            paths.append(path)
    # Also support extra top-level OpenClash YAML files without scanning country/proxy-only fragments.
    for path in sorted(output.glob("*.yaml")):
        if path not in paths:
            paths.append(path)
    return paths


def process_file(path: Path, repo: str, branch: str) -> Dict[str, Any]:
    data = safe_load_yaml(path)
    if data is None:
        return {"file": str(path), "changed": False, "skipped": True}
    changed = False
    changed = ensure_block_group(data) or changed
    changed = ensure_rule_providers(data, repo, branch) or changed
    changed = insert_game_rules(data) or changed
    if changed:
        dump_yaml(path, data)
    providers = data.get("rule-providers") if isinstance(data, dict) else {}
    rules = data.get("rules") if isinstance(data, dict) else []
    return {
        "file": str(path),
        "changed": changed,
        "skipped": False,
        "has_domain_provider": isinstance(providers, dict) and GAME_DOMAIN_PROVIDER in providers,
        "has_classical_provider": isinstance(providers, dict) and GAME_CLASSICAL_PROVIDER in providers,
        "game_rule_count": sum(1 for r in (rules or []) if str(r).startswith("RULE-SET,GAME-BLOCK-")),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add OpenClash rule-providers to block online games safely.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--repo", default=DEFAULT_OWNER_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    provider_paths = write_provider_files(root)
    reports = []
    for path in output_yaml_files(root):
        reports.append(process_file(path, args.repo, args.branch))
    out_dir = root / "output" / "Validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": True,
        "policy": "game-block-rule-provider-selector-only",
        "repo": args.repo,
        "branch": args.branch,
        "provider_files": provider_paths,
        "provider_names": [GAME_CLASSICAL_PROVIDER, GAME_DOMAIN_PROVIDER],
        "rule_targets": {name: "BLOCK" for name in [GAME_CLASSICAL_PROVIDER, GAME_DOMAIN_PROVIDER]},
        "processed_files": reports,
        "domain_payload_count": len(DOMAIN_PAYLOAD),
        "classical_payload_count": len(CLASSICAL_PAYLOAD),
    }
    (out_dir / "game_block_rule_provider_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

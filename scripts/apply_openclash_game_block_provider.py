#!/usr/bin/env python3
"""Create and inject a Mihomo/OpenClash rule-provider to block game apps and web games.

This script is designed for the SumberYAML workflow. It is intentionally independent
from proxy generation and never filters/removes trusted manual accounts from
input.txt or input/links.txt. It only creates a rule-provider and injects a
RULE-SET into generated YAML profiles.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

DEFAULT_YAML_TARGETS = [
    "output/openclash-ready.yaml",
    "output/lengkap.yaml",
    "output/lengkap_alive.yaml",
    "output/strict_alive.yaml",
    "output/lite.yaml",
    "output/fast.yaml",
    "output/gaming.yaml",
    "output/social_media.yaml",
    "output/streaming.yaml",
    "output/working.yaml",
    "output/general.yaml",
]

# Conservative block list focused on actual game platforms, publishers, launchers,
# cloud gaming, and common web-game portals. Avoid broad DOMAIN-KEYWORD,game by
# default because it causes too many false positives.
GAME_RULES = [
    # Steam / Valve
    "DOMAIN-SUFFIX,steampowered.com",
    "DOMAIN-SUFFIX,steamcommunity.com",
    "DOMAIN-SUFFIX,steamstatic.com",
    "DOMAIN-SUFFIX,steamcdn-a.akamaihd.net",
    "DOMAIN-SUFFIX,steamcontent.com",
    "DOMAIN-SUFFIX,steamserver.net",
    "DOMAIN-SUFFIX,valvesoftware.com",

    # Epic / Fortnite / Unreal
    "DOMAIN-SUFFIX,epicgames.com",
    "DOMAIN-SUFFIX,epicgames.dev",
    "DOMAIN-SUFFIX,epicgamescdn.com",
    "DOMAIN-SUFFIX,unrealengine.com",
    "DOMAIN-SUFFIX,fortnite.com",

    # Riot / Valorant / League of Legends
    "DOMAIN-SUFFIX,riotgames.com",
    "DOMAIN-SUFFIX,riotcdn.net",
    "DOMAIN-SUFFIX,valorant.com",
    "DOMAIN-SUFFIX,leagueoflegends.com",
    "DOMAIN-SUFFIX,lolesports.com",
    "DOMAIN-SUFFIX,leagueofgraphs.com",
    "DOMAIN-SUFFIX,pvp.net",
    "DOMAIN-SUFFIX,lolstatic.com",

    # Garena / Free Fire
    "DOMAIN-SUFFIX,garena.com",
    "DOMAIN-SUFFIX,garenanow.com",
    "DOMAIN-SUFFIX,freefiremobile.com",
    "DOMAIN-SUFFIX,ff.garena.com",

    # Moonton / Mobile Legends
    "DOMAIN-SUFFIX,moonton.com",
    "DOMAIN-SUFFIX,mobilelegends.com",
    "DOMAIN-SUFFIX,mobilelegends.com.cn",
    "DOMAIN-SUFFIX,youngjoygame.com",

    # Tencent / PUBG / Level Infinite
    "DOMAIN-SUFFIX,tencentgames.com",
    "DOMAIN-SUFFIX,pubg.com",
    "DOMAIN-SUFFIX,pubgmobile.com",
    "DOMAIN-SUFFIX,levelinfinite.com",
    "DOMAIN-SUFFIX,proximabeta.com",
    "DOMAIN-SUFFIX,igamecj.com",
    "DOMAIN-SUFFIX,game.qq.com",

    # Roblox
    "DOMAIN-SUFFIX,roblox.com",
    "DOMAIN-SUFFIX,rbxcdn.com",
    "DOMAIN-SUFFIX,robloxlabs.com",

    # Minecraft / Mojang / Xbox gaming services
    "DOMAIN-SUFFIX,minecraft.net",
    "DOMAIN-SUFFIX,mojang.com",
    "DOMAIN-SUFFIX,mojang.net",
    "DOMAIN-SUFFIX,xboxlive.com",
    "DOMAIN-SUFFIX,xboxservices.com",
    "DOMAIN-SUFFIX,xbox.com",

    # PlayStation / Nintendo
    "DOMAIN-SUFFIX,playstation.com",
    "DOMAIN-SUFFIX,playstation.net",
    "DOMAIN-SUFFIX,sonyentertainmentnetwork.com",
    "DOMAIN-SUFFIX,nintendo.com",
    "DOMAIN-SUFFIX,nintendo.net",
    "DOMAIN-SUFFIX,nintendowifi.net",

    # EA / Origin / Ubisoft / Rockstar / Activision / Blizzard
    "DOMAIN-SUFFIX,ea.com",
    "DOMAIN-SUFFIX,easports.com",
    "DOMAIN-SUFFIX,origin.com",
    "DOMAIN-SUFFIX,ubisoft.com",
    "DOMAIN-SUFFIX,ubi.com",
    "DOMAIN-SUFFIX,ubisoftconnect.com",
    "DOMAIN-SUFFIX,rockstargames.com",
    "DOMAIN-SUFFIX,socialclub.rockstargames.com",
    "DOMAIN-SUFFIX,activision.com",
    "DOMAIN-SUFFIX,callofduty.com",
    "DOMAIN-SUFFIX,battle.net",
    "DOMAIN-SUFFIX,blizzard.com",
    "DOMAIN-SUFFIX,blizzardgames.cn",

    # HoYoverse / miHoYo
    "DOMAIN-SUFFIX,hoyoverse.com",
    "DOMAIN-SUFFIX,hoyolab.com",
    "DOMAIN-SUFFIX,mihoyo.com",
    "DOMAIN-SUFFIX,mihoyo.com.cn",
    "DOMAIN-SUFFIX,gateway-mihoyo.akamaized.net",
    "DOMAIN-SUFFIX,genshinimpact.com",
    "DOMAIN-SUFFIX,honkaiimpact3.com",
    "DOMAIN-SUFFIX,honkaistarrail.com",
    "DOMAIN-SUFFIX,zenlesszonezero.com",

    # Wargaming / Warframe / War Thunder / miHoYo-like gaming publishers
    "DOMAIN-SUFFIX,wargaming.net",
    "DOMAIN-SUFFIX,worldoftanks.com",
    "DOMAIN-SUFFIX,warframe.com",
    "DOMAIN-SUFFIX,warframe.net",
    "DOMAIN-SUFFIX,gaijin.net",
    "DOMAIN-SUFFIX,warthunder.com",

    # Pokemon Go / Niantic
    "DOMAIN-SUFFIX,nianticlabs.com",
    "DOMAIN-SUFFIX,pokemongolive.com",

    # App stores gaming hubs / launchers
    "DOMAIN-SUFFIX,humblebundle.com",
    "DOMAIN-SUFFIX,gog.com",
    "DOMAIN-SUFFIX,gog-statics.com",
    "DOMAIN-SUFFIX,itch.io",
    "DOMAIN-SUFFIX,itch.zone",

    # Cloud gaming
    "DOMAIN-SUFFIX,geforcenow.com",
    "DOMAIN-SUFFIX,nvidia.com",
    "DOMAIN-SUFFIX,stadia.google.com",
    "DOMAIN-SUFFIX,play.geforcenow.com",
    "DOMAIN-SUFFIX,xboxcloudgaming.com",

    # Web game portals
    "DOMAIN-SUFFIX,poki.com",
    "DOMAIN-SUFFIX,crazygames.com",
    "DOMAIN-SUFFIX,y8.com",
    "DOMAIN-SUFFIX,miniclip.com",
    "DOMAIN-SUFFIX,addictinggames.com",
    "DOMAIN-SUFFIX,kongregate.com",
    "DOMAIN-SUFFIX,armorgames.com",
    "DOMAIN-SUFFIX,newgrounds.com",
    "DOMAIN-SUFFIX,friv.com",
    "DOMAIN-SUFFIX,agame.com",
    "DOMAIN-SUFFIX,silvergames.com",
    "DOMAIN-SUFFIX,coolmathgames.com",
    "DOMAIN-SUFFIX,mathplayground.com",
    "DOMAIN-SUFFIX,lagged.com",
    "DOMAIN-SUFFIX,now.gg",
    "DOMAIN-SUFFIX,gamedistribution.com",
    "DOMAIN-SUFFIX,gamepix.com",
    "DOMAIN-SUFFIX,html5games.com",
    "DOMAIN-SUFFIX,1001games.com",
    "DOMAIN-SUFFIX,onlinegames.io",
    "DOMAIN-SUFFIX,twoplayergames.org",
    "DOMAIN-SUFFIX,playhop.com",

    # Gaming social / community platforms that are mostly game-specific
    "DOMAIN-SUFFIX,modrinth.com",
    "DOMAIN-SUFFIX,curseforge.com",
    "DOMAIN-SUFFIX,planetminecraft.com",
    "DOMAIN-SUFFIX,op.gg",
    "DOMAIN-SUFFIX,u.gg",
    "DOMAIN-SUFFIX,mobalytics.gg",
]

# Optional ports. Disabled by default because some networks use these for non-game
# traffic, but useful if a user wants stricter blocking in OpenClash/Mihomo.
GAME_PORT_RULES = [
    "DST-PORT,27000-27200",  # Steam/Source ecosystem
    "DST-PORT,3074",        # Xbox / some console multiplayer
    "DST-PORT,3478-3480",   # PlayStation / STUN-like console gaming
    "DST-PORT,3659",        # EA games
    "DST-PORT,5222",        # Some mobile games/XMPP-like game services
]


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        item = str(item or "").strip()
        if not item or item.startswith("#"):
            continue
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def provider_url(repo: str, branch: str, provider_file: str, url_source: str) -> str:
    repo = (repo or "adiorany3/SumberYAML").strip()
    branch = (branch or "main").strip()
    if url_source == "jsdelivr":
        return f"https://cdn.jsdelivr.net/gh/{repo}@{branch}/output/RuleProviders/{provider_file}"
    return f"https://raw.githubusercontent.com/{repo}/{branch}/output/RuleProviders/{provider_file}"


def load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=120)


def ensure_provider_file(root: Path, provider_name: str, include_ports: bool) -> Path:
    provider_dir = root / "output" / "RuleProviders"
    provider_dir.mkdir(parents=True, exist_ok=True)
    rules = list(GAME_RULES)
    if include_ports:
        rules.extend(GAME_PORT_RULES)
    payload = unique(rules)
    provider_path = provider_dir / f"{provider_name}.yaml"
    write_yaml(provider_path, {"payload": payload})
    return provider_path


def ensure_rule_provider(data: dict[str, Any], provider_name: str, provider_file: str, provider_url_value: str) -> None:
    providers = data.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
        data["rule-providers"] = providers
    providers[provider_name] = {
        "type": "http",
        "behavior": "classical",
        "format": "yaml",
        "path": f"./rule_provider/{provider_file}",
        "url": provider_url_value,
        "interval": 86400,
    }


def ensure_reject_group(data: dict[str, Any]) -> None:
    # REJECT is a built-in policy in Clash/Mihomo rules. Some validators also like
    # having it in selectors, but a proxy-group entry is not required and can be invalid.
    return None


def insert_rule(data: dict[str, Any], provider_name: str, action: str) -> bool:
    rule = f"RULE-SET,{provider_name},{action}"
    rules = data.get("rules")
    if not isinstance(rules, list):
        rules = []
        data["rules"] = rules
    rules = [str(item).strip() for item in rules if str(item).strip()]
    rules = [item for item in rules if not item.startswith(f"RULE-SET,{provider_name},")]

    # Place game block after local/LAN direct rules and after adblock if present,
    # but before category/domain routing and MATCH.
    insert_at = len(rules)
    for idx, item in enumerate(rules):
        upper = item.upper()
        if upper.startswith("MATCH,") or upper.startswith("DOMAIN") or upper.startswith("RULE-SET,") or upper.startswith("GEOIP,"):
            insert_at = idx
            break

    rules.insert(insert_at, rule)
    data["rules"] = rules
    return True


def apply_to_yaml_file(path: Path, root: Path, provider_name: str, provider_file: str, provider_url_value: str, action: str) -> dict[str, Any]:
    data = load_yaml(path)
    if data is None:
        return {"file": str(path), "exists": path.exists(), "changed": False, "reason": "not_yaml_mapping"}
    before = json.dumps(data, sort_keys=True, ensure_ascii=False)
    ensure_rule_provider(data, provider_name, provider_file, provider_url_value)
    ensure_reject_group(data)
    insert_rule(data, provider_name, action)
    after = json.dumps(data, sort_keys=True, ensure_ascii=False)
    changed = before != after
    if changed:
        write_yaml(path, data)
    return {"file": str(path), "exists": True, "changed": changed, "provider": provider_name, "action": action}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and inject game block rule-provider into OpenClash YAML outputs.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--repo", default="adiorany3/SumberYAML", help="GitHub repository owner/name")
    parser.add_argument("--branch", default="main", help="Git branch used in raw URL")
    parser.add_argument("--provider-name", default="game-block", help="Rule-provider name")
    parser.add_argument("--action", default="REJECT", help="Rule action, usually REJECT")
    parser.add_argument("--url-source", choices=["raw", "jsdelivr"], default="raw", help="Provider URL source")
    parser.add_argument("--include-port-rules", action="store_true", help="Also block common game ports. Disabled by default.")
    parser.add_argument("--targets", nargs="*", default=DEFAULT_YAML_TARGETS, help="YAML files to modify")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    validation_dir = root / "output" / "Validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    provider_file = f"{args.provider_name}.yaml"
    provider_path = ensure_provider_file(root, args.provider_name, args.include_port_rules)
    provider_url_value = provider_url(args.repo, args.branch, provider_file, args.url_source)

    results = []
    for target in args.targets:
        results.append(apply_to_yaml_file(root / target, root, args.provider_name, provider_file, provider_url_value, args.action))

    summary = {
        "ok": True,
        "provider_name": args.provider_name,
        "provider_file": str(provider_path.relative_to(root)),
        "provider_url": provider_url_value,
        "action": args.action,
        "include_port_rules": bool(args.include_port_rules),
        "rule_count": len(unique(GAME_RULES + (GAME_PORT_RULES if args.include_port_rules else []))),
        "changed_files": [item["file"] for item in results if item.get("changed")],
        "results": results,
        "trusted_manual_note": "input.txt and input/links.txt are not filtered, tested, quarantined, or removed by this script.",
    }
    (validation_dir / "summary_game_block_provider.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Build purpose-specific OpenClash/Mihomo groups for SumberYAML.

Goals:
- Group nodes by purpose instead of reusing the same node set everywhere.
- Allow more nodes from generated YAML/Alive/BestPing, not only input.txt / input/links.txt.
- Keep manual accounts from input.txt / input/links.txt trusted: never filter/remove them.
- Create renamed alias copies for purpose groups, so each group can have clear labels.
- Add rules that route Indonesian/streaming/gaming/social/work/general traffic to matching groups.

This script is intentionally conservative. It does not test accounts and does not delete manual links.
It only reorganizes generated YAML files after the normal generator/merge stage.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc


DEFAULT_YAML_FILES = [
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
    "output/openclash-ready.yaml",
]

HEALTH_CSV_CANDIDATES = [
    "output/BestPing/top5_indonesia_ping.csv",
    "output/BestPing/top5_best_ping.csv",
    "output/Alive/alive.csv",
    "output/Alive/check_result.csv",
]

TEST_URL = "https://www.gstatic.com/generate_204"

LAN_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "DOMAIN-SUFFIX,lan,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,224.0.0.0/4,DIRECT,no-resolve",
    "IP-CIDR,255.255.255.255/32,DIRECT,no-resolve",
]

PURPOSE_RULES = {
    "INDONESIA-BEST": [
        "DOMAIN-SUFFIX,id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,go.id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,ac.id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,co.id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,or.id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,detik.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,kompas.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,tribunnews.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,tokopedia.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,bukalapak.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,shopee.co.id,INDONESIA-BEST",
        "DOMAIN-SUFFIX,gojek.com,INDONESIA-BEST",
        "DOMAIN-SUFFIX,grab.com,INDONESIA-BEST",
        "GEOIP,ID,INDONESIA-BEST,no-resolve",
    ],
    "STREAMING-BEST": [
        "DOMAIN-SUFFIX,youtube.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,googlevideo.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,ytimg.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,netflix.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,nflxvideo.net,STREAMING-BEST",
        "DOMAIN-SUFFIX,disneyplus.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,hotstar.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,spotify.com,STREAMING-BEST",
        "DOMAIN-SUFFIX,scdn.co,STREAMING-BEST",
    ],
    "GAMING-BEST": [
        "DOMAIN-SUFFIX,steamcontent.com,GAMING-BEST",
        "DOMAIN-SUFFIX,steampowered.com,GAMING-BEST",
        "DOMAIN-SUFFIX,steamstatic.com,GAMING-BEST",
        "DOMAIN-SUFFIX,epicgames.com,GAMING-BEST",
        "DOMAIN-SUFFIX,riotgames.com,GAMING-BEST",
        "DOMAIN-SUFFIX,garena.com,GAMING-BEST",
        "DOMAIN-SUFFIX,pubgmobile.com,GAMING-BEST",
        "DOMAIN-SUFFIX,mihoyo.com,GAMING-BEST",
        "DOMAIN-SUFFIX,hoyoverse.com,GAMING-BEST",
        "DOMAIN-SUFFIX,playstation.net,GAMING-BEST",
        "DOMAIN-SUFFIX,xboxlive.com,GAMING-BEST",
    ],
    "SOCIAL-BEST": [
        "DOMAIN-SUFFIX,facebook.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,fbcdn.net,SOCIAL-BEST",
        "DOMAIN-SUFFIX,instagram.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,whatsapp.net,SOCIAL-BEST",
        "DOMAIN-SUFFIX,tiktok.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,tiktokcdn.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,twitter.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,x.com,SOCIAL-BEST",
        "DOMAIN-SUFFIX,telegram.org,SOCIAL-BEST",
        "DOMAIN-SUFFIX,t.me,SOCIAL-BEST",
    ],
    "WORKING-BEST": [
        "DOMAIN-SUFFIX,github.com,WORKING-BEST",
        "DOMAIN-SUFFIX,githubusercontent.com,WORKING-BEST",
        "DOMAIN-SUFFIX,gitlab.com,WORKING-BEST",
        "DOMAIN-SUFFIX,google.com,WORKING-BEST",
        "DOMAIN-SUFFIX,gstatic.com,WORKING-BEST",
        "DOMAIN-SUFFIX,microsoft.com,WORKING-BEST",
        "DOMAIN-SUFFIX,office.com,WORKING-BEST",
        "DOMAIN-SUFFIX,office365.com,WORKING-BEST",
        "DOMAIN-SUFFIX,zoom.us,WORKING-BEST",
        "DOMAIN-SUFFIX,slack.com,WORKING-BEST",
        "DOMAIN-SUFFIX,cloudflare.com,WORKING-BEST",
    ],
}

PURPOSES = [
    "INDONESIA-BEST",
    "STREAMING-BEST",
    "GAMING-BEST",
    "SOCIAL-BEST",
    "WORKING-BEST",
    "GENERAL-BEST",
]

PURPOSE_PREFIX = {
    "INDONESIA-BEST": "ID",
    "STREAMING-BEST": "STREAM",
    "GAMING-BEST": "GAME",
    "SOCIAL-BEST": "SOCIAL",
    "WORKING-BEST": "WORK",
    "GENERAL-BEST": "GEN",
}

PURPOSE_KEYWORDS = {
    "INDONESIA-BEST": [
        "indonesia", "jakarta", "surabaya", "id", "🇮🇩", "telkom", "telkomsel", "biznet", "xl", "isat", "indosat", "tri", "three", "idcloudhost",
    ],
    "STREAMING-BEST": [
        "stream", "netflix", "youtube", "yt", "video", "nflx", "disney", "spotify", "media",
    ],
    "GAMING-BEST": [
        "game", "gaming", "steam", "garena", "pubg", "ml", "mobile legends", "riot", "genshin", "hoyo", "mihoyo",
    ],
    "SOCIAL-BEST": [
        "social", "sosmed", "facebook", "fb", "instagram", "ig", "whatsapp", "wa", "tiktok", "telegram", "twitter", "x.com",
    ],
    "WORKING-BEST": [
        "work", "working", "github", "zoom", "office", "microsoft", "google", "cloudflare", "coding", "dev",
    ],
    "GENERAL-BEST": ["general", "stable", "fast", "alive", "best", "url-test", "fallback"],
}

MANUAL_NAME_PATTERNS = [
    re.compile(r"^LINK\b", re.I),
    re.compile(r"\bMANUAL\b", re.I),
    re.compile(r"\bINPUT\b", re.I),
    re.compile(r"\bTRUSTED\b", re.I),
]


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def norm_name(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def is_manual_name(name: str) -> bool:
    text = norm_name(name)
    return any(pattern.search(text) for pattern in MANUAL_NAME_PATTERNS)


def ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def proxy_names(data: Dict[str, Any]) -> List[str]:
    result = []
    for item in ensure_list(data.get("proxies")):
        if isinstance(item, dict) and item.get("name"):
            result.append(norm_name(item.get("name")))
    return result


def group_names(data: Dict[str, Any]) -> Set[str]:
    result = set()
    for item in ensure_list(data.get("proxy-groups")):
        if isinstance(item, dict) and item.get("name"):
            result.add(norm_name(item.get("name")))
    return result


def map_proxies(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for item in ensure_list(data.get("proxies")):
        if isinstance(item, dict) and item.get("name"):
            result[norm_name(item.get("name"))] = item
    return result


def load_health_scores(root: Path) -> Dict[str, Dict[str, Any]]:
    scores: Dict[str, Dict[str, Any]] = {}
    rank_bonus = 0
    for rel in HEALTH_CSV_CANDIDATES:
        path = root / rel
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            continue
        for row_idx, row in enumerate(rows):
            name = norm_name(row.get("name") or row.get("proxy") or row.get("tag"))
            if not name:
                continue
            delay = parse_int(row.get("delay_ms") or row.get("delay") or row.get("latency") or row.get("ping"))
            country = clean_text(row.get("country") or row.get("cc") or row.get("region")).upper()
            status = clean_text(row.get("status")).lower()
            base = delay if delay is not None else 9999
            if status and status not in {"alive", "ok", "success", "true", ""}:
                base += 5000
            base += row_idx + rank_bonus
            prev = scores.get(name)
            if prev is None or base < prev.get("score", 999999):
                scores[name] = {
                    "score": base,
                    "delay_ms": delay,
                    "country": country,
                    "status": status,
                    "source": rel,
                }
        rank_bonus += 100
    return scores


def group_candidate_names(data: Dict[str, Any]) -> Dict[str, Set[str]]:
    candidates = {purpose: set() for purpose in PURPOSES}
    valid_names = set(proxy_names(data))
    valid_groups = group_names(data)
    all_refs = valid_names | valid_groups | {"DIRECT", "REJECT", "GLOBAL"}

    for group in ensure_list(data.get("proxy-groups")):
        if not isinstance(group, dict):
            continue
        gname = norm_name(group.get("name"))
        gtext = gname.lower()
        refs = [norm_name(x) for x in ensure_list(group.get("proxies")) if norm_name(x) in valid_names]
        for purpose, keys in PURPOSE_KEYWORDS.items():
            if any(k in gtext for k in keys):
                candidates[purpose].update(refs)

    # Keyword hints from proxy names themselves.
    for name in valid_names:
        text = name.lower()
        for purpose, keys in PURPOSE_KEYWORDS.items():
            if any(k in text for k in keys):
                candidates[purpose].add(name)

    return candidates


def is_indonesia(name: str, score: Optional[Dict[str, Any]]) -> bool:
    if score and score.get("country") in {"ID", "INDONESIA"}:
        return True
    text = name.lower()
    return any(k in text for k in PURPOSE_KEYWORDS["INDONESIA-BEST"])


def sorted_candidates(
    names: Iterable[str],
    scores: Dict[str, Dict[str, Any]],
    max_count: int,
    exclude_manual: bool = False,
) -> List[str]:
    unique = []
    seen = set()
    for name in names:
        name = norm_name(name)
        if not name or name in seen:
            continue
        if exclude_manual and is_manual_name(name):
            continue
        seen.add(name)
        unique.append(name)

    def key(name: str) -> Tuple[int, str]:
        score = scores.get(name, {}).get("score", 999999)
        return (int(score), name.lower())

    unique.sort(key=key)
    return unique[:max_count]


def select_purpose_sources(
    data: Dict[str, Any],
    root: Path,
    max_per_group: int,
    max_id: int,
) -> Dict[str, List[str]]:
    names = proxy_names(data)
    scores = load_health_scores(root)
    group_candidates = group_candidate_names(data)

    selected: Dict[str, List[str]] = {}

    id_pool = set(group_candidates.get("INDONESIA-BEST", set()))
    for name in names:
        if is_indonesia(name, scores.get(name)):
            id_pool.add(name)
    selected["INDONESIA-BEST"] = sorted_candidates(id_pool, scores, max_id, exclude_manual=False)

    for purpose in ["STREAMING-BEST", "GAMING-BEST", "SOCIAL-BEST", "WORKING-BEST"]:
        pool = set(group_candidates.get(purpose, set()))
        # If category is too small, add high quality non-manual nodes too.
        if len(pool) < max(3, min(5, max_per_group)):
            pool.update(sorted_candidates(names, scores, max_per_group * 2, exclude_manual=True))
        selected[purpose] = sorted_candidates(pool, scores, max_per_group, exclude_manual=False)

    general_pool = set(group_candidates.get("GENERAL-BEST", set()))
    general_pool.update(sorted_candidates(names, scores, max_per_group * 2, exclude_manual=True))
    if not general_pool:
        general_pool.update(names)
    selected["GENERAL-BEST"] = sorted_candidates(general_pool, scores, max_per_group, exclude_manual=False)

    return selected


def alias_name(purpose: str, index: int, original: str) -> str:
    prefix = PURPOSE_PREFIX.get(purpose, "NODE")
    clean = re.sub(r"\s+", " ", original).strip()
    clean = re.sub(r"^(ID|STREAM|GAME|SOCIAL|WORK|GEN)-\d+\s+", "", clean, flags=re.I)
    return f"{prefix}-{index:02d} {clean}"[:180]


def ensure_unique_name(base: str, used: Set[str]) -> str:
    name = base
    idx = 2
    while name in used:
        name = f"{base} #{idx}"
        idx += 1
    used.add(name)
    return name


def create_alias_proxies(
    data: Dict[str, Any],
    selected: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    proxy_map = map_proxies(data)
    used = set(proxy_map.keys())
    data.setdefault("proxies", [])
    alias_by_purpose: Dict[str, List[str]] = {}

    # Remove previously generated aliases to avoid unbounded growth on repeat runs.
    kept = []
    for item in ensure_list(data.get("proxies")):
        if not isinstance(item, dict):
            continue
        name = norm_name(item.get("name"))
        if item.get("_sumberyaml_purpose_alias") is True:
            continue
        kept.append(item)
    data["proxies"] = kept
    proxy_map = map_proxies(data)
    used = set(proxy_map.keys())

    for purpose, source_names in selected.items():
        aliases: List[str] = []
        for idx, original_name in enumerate(source_names, start=1):
            original = proxy_map.get(original_name)
            if not original:
                continue
            item = deepcopy(original)
            new_name = ensure_unique_name(alias_name(purpose, idx, original_name), used)
            item["name"] = new_name
            item["_sumberyaml_purpose_alias"] = True
            item["_sumberyaml_source_name"] = original_name
            data["proxies"].append(item)
            aliases.append(new_name)
        alias_by_purpose[purpose] = aliases

    # Keep generated metadata out of final YAML if requested by separate cleanup? OpenClash ignores unknown proxy keys? Usually not safe.
    # Therefore remove internal metadata before writing.
    for item in ensure_list(data.get("proxies")):
        if isinstance(item, dict):
            item.pop("_sumberyaml_purpose_alias", None)
            item.pop("_sumberyaml_source_name", None)

    return alias_by_purpose


def make_group(name: str, group_type: str, proxies: Sequence[str], *, tolerance: Optional[int] = None) -> Dict[str, Any]:
    group: Dict[str, Any] = {
        "name": name,
        "type": group_type,
        "proxies": list(dict.fromkeys([p for p in proxies if p])),
        "url": TEST_URL,
        "interval": 300,
        "lazy": True,
    }
    if tolerance is not None and group_type in {"url-test", "load-balance"}:
        group["tolerance"] = tolerance
    return group


def upsert_group(data: Dict[str, Any], group: Dict[str, Any]) -> None:
    groups = ensure_list(data.get("proxy-groups"))
    data["proxy-groups"] = groups
    name = norm_name(group.get("name"))
    for idx, existing in enumerate(groups):
        if isinstance(existing, dict) and norm_name(existing.get("name")) == name:
            groups[idx] = group
            return
    groups.append(group)


def insert_front_unique(items: List[str], new_items: Sequence[str]) -> List[str]:
    result = []
    seen = set()
    for item in list(new_items) + list(items):
        item = norm_name(item)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def ensure_dns(data: Dict[str, Any]) -> None:
    dns = data.get("dns") if isinstance(data.get("dns"), dict) else {}
    dns["enable"] = True
    dns["ipv6"] = False
    dns["enhanced-mode"] = dns.get("enhanced-mode") or "fake-ip"
    dns["nameserver"] = ["1.1.1.1"]
    dns["fallback"] = ["8.8.8.8"]
    data["dns"] = dns
    data["unified-delay"] = True
    data["tcp-concurrent"] = True
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    profile["store-selected"] = True
    profile["store-fake-ip"] = True
    data["profile"] = profile


def ensure_purpose_groups(data: Dict[str, Any], root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    valid_names_before = proxy_names(data)
    manual = [name for name in valid_names_before if is_manual_name(name)]

    selected = select_purpose_sources(
        data=data,
        root=root,
        max_per_group=max(1, args.max_per_group),
        max_id=max(1, args.max_indonesia),
    )
    alias_by_purpose = create_alias_proxies(data, selected)

    # Fallback: if alias group empty, use original selected names; if still empty, use manual/general nodes.
    all_proxy_names = set(proxy_names(data))
    for purpose in PURPOSES:
        aliases = [x for x in alias_by_purpose.get(purpose, []) if x in all_proxy_names]
        if not aliases:
            aliases = [x for x in selected.get(purpose, []) if x in all_proxy_names]
        if not aliases and purpose != "INDONESIA-BEST":
            aliases = [x for x in alias_by_purpose.get("GENERAL-BEST", []) if x in all_proxy_names]
        alias_by_purpose[purpose] = aliases

    for purpose in ["INDONESIA-BEST", "STREAMING-BEST", "GAMING-BEST", "SOCIAL-BEST", "WORKING-BEST", "GENERAL-BEST"]:
        if alias_by_purpose.get(purpose):
            upsert_group(data, make_group(purpose, "url-test", alias_by_purpose[purpose], tolerance=args.tolerance))

    if manual:
        upsert_group(data, make_group("best-link", "url-test", manual, tolerance=args.tolerance))
        upsert_group(data, make_group("fallback-link", "fallback", manual))

    anti_members = [
        "INDONESIA-BEST",
        "GENERAL-BEST",
        "BEST-STABLE",
        "fallback-link" if manual else "",
        "best-link" if manual else "",
        "URL-TEST",
        "FALLBACK",
    ]
    existing_groups = group_names(data)
    existing_outbounds = set(proxy_names(data)) | existing_groups | {"DIRECT"}
    anti_members = [x for x in anti_members if x and x in existing_outbounds]
    if not anti_members:
        anti_members = list(alias_by_purpose.get("GENERAL-BEST") or valid_names_before[:5])
    if anti_members:
        upsert_group(data, make_group("ANTI-BENGONG", "fallback", anti_members))

    # Update PROXY selector. Do not remove old choices; prepend purpose choices.
    groups = ensure_list(data.get("proxy-groups"))
    existing_groups = group_names(data)
    preferred = [
        "ANTI-BENGONG",
        "INDONESIA-BEST",
        "STREAMING-BEST",
        "GAMING-BEST",
        "SOCIAL-BEST",
        "WORKING-BEST",
        "GENERAL-BEST",
        "fallback-link" if manual else "",
        "best-link" if manual else "",
        "DIRECT",
    ]
    preferred = [x for x in preferred if x and (x in existing_groups or x == "DIRECT")]
    proxy_group = None
    for group in groups:
        if isinstance(group, dict) and norm_name(group.get("name")) == "PROXY":
            proxy_group = group
            break
    if proxy_group is None:
        proxy_group = {"name": "PROXY", "type": "select", "proxies": []}
        groups.insert(0, proxy_group)
    proxy_group["type"] = "select"
    proxy_group["proxies"] = insert_front_unique(ensure_list(proxy_group.get("proxies")), preferred)
    proxy_group.pop("default", None)  # legacy client safety

    ensure_dns(data)

    return {
        "manual_count": len(manual),
        "selected": {k: len(v) for k, v in selected.items()},
        "aliases": {k: len(v) for k, v in alias_by_purpose.items()},
    }


def dedupe_rules(rules: Sequence[Any]) -> List[str]:
    result = []
    seen = set()
    for rule in rules:
        text = clean_text(rule)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def ensure_rules(data: Dict[str, Any], args: argparse.Namespace) -> Dict[str, int]:
    existing = [clean_text(x) for x in ensure_list(data.get("rules")) if clean_text(x)]
    # Remove old MATCH first; re-add at end.
    existing_non_match = [r for r in existing if not r.upper().startswith("MATCH,")]

    purpose_rules = []
    for group_name in ["INDONESIA-BEST", "STREAMING-BEST", "GAMING-BEST", "SOCIAL-BEST", "WORKING-BEST"]:
        if group_name in group_names(data):
            purpose_rules.extend(PURPOSE_RULES.get(group_name, []))

    optional_quic = []
    if args.block_quic:
        optional_quic = [
            "AND,((NETWORK,UDP),(DST-PORT,443)),REJECT",
        ]

    # Keep category rules above generic existing rules, then final MATCH.
    final_rules = dedupe_rules(LAN_RULES + optional_quic + purpose_rules + existing_non_match)
    final_rules = [r for r in final_rules if not r.upper().startswith("GEOIP,LAN")]
    final_rules.append("MATCH,PROXY")
    data["rules"] = final_rules
    return {"rule_count": len(final_rules), "purpose_rule_count": len(purpose_rules)}


def clean_group_dependencies(data: Dict[str, Any]) -> Dict[str, int]:
    valid = set(proxy_names(data)) | group_names(data) | {"DIRECT", "REJECT", "GLOBAL"}
    removed = 0
    for group in ensure_list(data.get("proxy-groups")):
        if not isinstance(group, dict):
            continue
        refs = ensure_list(group.get("proxies"))
        kept = []
        seen = set()
        for ref in refs:
            ref = norm_name(ref)
            if not ref or ref not in valid or ref in seen:
                if ref and ref not in valid:
                    removed += 1
                continue
            seen.add(ref)
            kept.append(ref)
        if not kept:
            candidates = [n for n in proxy_names(data) if n]
            if candidates:
                kept = candidates[:1]
        group["proxies"] = kept
        group.pop("default", None)
    return {"removed_missing_refs": removed}


def apply_to_file(path: Path, root: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if not path.exists():
        return {"file": str(path), "exists": False}
    data = read_yaml(path)
    if not data:
        return {"file": str(path), "exists": True, "ok": False, "reason": "empty or invalid yaml"}
    if args.backup:
        backup = path.with_suffix(path.suffix + ".purpose.bak")
        if not backup.exists():
            shutil.copy2(path, backup)

    group_summary = ensure_purpose_groups(data, root, args)
    rule_summary = ensure_rules(data, args)
    dep_summary = clean_group_dependencies(data)
    write_yaml(path, data)

    return {
        "file": str(path.relative_to(root)),
        "exists": True,
        "ok": True,
        "proxy_count": len(proxy_names(data)),
        "group_count": len(group_names(data)),
        **group_summary,
        **rule_summary,
        **dep_summary,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply purpose-specific OpenClash rule/group optimizer.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--files", nargs="*", default=DEFAULT_YAML_FILES, help="YAML files to process")
    parser.add_argument("--max-per-group", type=int, default=15, help="Max nodes per non-ID purpose group")
    parser.add_argument("--max-indonesia", type=int, default=20, help="Max nodes in INDONESIA-BEST")
    parser.add_argument("--tolerance", type=int, default=80, help="url-test tolerance")
    parser.add_argument("--block-quic", action="store_true", help="Add UDP/443 reject rule for QUIC if needed")
    parser.add_argument("--backup", action="store_true", help="Create .purpose.bak backups")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    results = []
    for rel in args.files:
        results.append(apply_to_file(root / rel, root, args))

    report = {
        "ok": all((not item.get("exists")) or item.get("ok") for item in results),
        "max_per_group": args.max_per_group,
        "max_indonesia": args.max_indonesia,
        "tolerance": args.tolerance,
        "block_quic": bool(args.block_quic),
        "results": results,
    }
    out_path = root / "output/Validation/summary_purpose_groups.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

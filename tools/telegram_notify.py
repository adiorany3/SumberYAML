import argparse
import csv
import json
import os
from pathlib import Path

import requests


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_FILE = os.getenv("TELEGRAM_SEND_OUTPUT_FILE", "true").strip().lower() in [
    "1",
    "true",
    "yes",
    "y",
    "on",
]
RUN_MODE = os.getenv("RUN_MODE", "").strip().lower()


def mode_title():
    if RUN_MODE in ["test", "test_ping"]:
        return "🧪 Test ping selesai"
    if RUN_MODE in ["update_ping", "ping_update"]:
        return "🏆 Update ping selesai"
    return "✅ Update OpenClash selesai"


def tg(method):
    return f"https://api.telegram.org/bot{TOKEN}/{method}"


def send_message(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram token/chat id kosong, skip notify")
        return

    parts = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for part in parts:
        response = requests.post(
            tg("sendMessage"),
            data={
                "chat_id": CHAT_ID,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        print(response.status_code, response.text[:200])


def send_document(path, caption=""):
    if not TOKEN or not CHAT_ID or not Path(path).exists():
        return

    with open(path, "rb") as file:
        response = requests.post(
            tg("sendDocument"),
            data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={"document": file},
            timeout=120,
        )
        print(response.status_code, response.text[:200])


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path, limit=None):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        return rows[:limit] if limit else rows
    except Exception:
        return []


def read_summary():
    return read_json("output/Alive/summary_alive.json")


def read_protocol_rows():
    return read_csv_rows("output/summary_protocol.csv")


def read_top5_rows():
    for path in [
        "output/BestPing/top5_indonesia_ping.csv",
        "output/BestPing/top5_best_ping.csv",
    ]:
        rows = read_csv_rows(path, limit=5)
        if rows:
            return rows
    return []


def count_invalid_reasons():
    rows = read_csv_rows("output/Invalid/all_invalid.csv")
    result = {
        "invalid_total": len(rows),
        "invalid_uuid": 0,
        "blacklist": 0,
    }
    for row in rows:
        reason = (row.get("reason") or "").lower()
        if "uuid" in reason:
            result["invalid_uuid"] += 1
        if "blacklist" in reason:
            result["blacklist"] += 1
    return result


def source_cache_summary():
    rows = read_csv_rows("output/Source/source_status.csv")
    return {
        "source_total": len(rows),
        "source_ok": sum(1 for row in rows if row.get("status") == "ok"),
        "source_cached": sum(1 for row in rows if row.get("status") == "cached" or row.get("cache_used") == "true"),
        "source_failed": sum(1 for row in rows if row.get("status") == "failed"),
    }


def validation_summary():
    report = read_json("output/Validation/validation_report.json")
    files = report.get("files", []) if isinstance(report, dict) else []
    ok_files = [item for item in files if item.get("ok")]
    return {
        "ok": report.get("ok", False) if isinstance(report, dict) else False,
        "file_count": len(files),
        "ok_count": len(ok_files),
    }


def success_message():
    summary = read_summary()
    protocol_rows = read_protocol_rows()
    invalid = count_invalid_reasons()
    sources = source_cache_summary()
    validation = validation_summary()
    lite = read_json("output/Lite/summary_lite.json")
    fast = read_json("output/Fast/summary_fast.json")
    profiles = read_json("output/Categories/summary_usage_profiles.json")
    strict = read_json("output/Strict/summary_strict_alive.json")
    reuse = read_json("output/Reuse/reuse_previous_output.json")

    lines = [
        mode_title(),
        "",
        f"Total valid: <code>{summary.get('total', '-')}</code>",
        f"Alive: <code>{summary.get('alive', '-')}</code>",
        f"Strict alive: <code>{summary.get('strict_alive', strict.get('proxy_count', '-'))}</code> / rounds <code>{summary.get('require_success_rounds', strict.get('require_success_rounds', '-'))}/{summary.get('test_rounds', strict.get('test_rounds', '-'))}</code>",
        f"Dead: <code>{summary.get('dead', '-')}</code>",
        f"Untested: <code>{summary.get('untested', '-')}</code>",
        f"Tester: <code>{summary.get('tester', '-')}</code>",
        f"Filter output: <code>{summary.get('final_output_filter', '-')}</code>",
        f"Best Ping: <code>{summary.get('best_ping_count', '-')}</code> node",
        f"Strict YAML: <code>{strict.get('proxy_count', summary.get('strict_output_count', 0))}</code> node",
        f"Lite YAML: <code>{lite.get('proxy_count', 0)}</code> node",
        f"Fast YAML: <code>{fast.get('proxy_count', 0)}</code> node",
        f"Responsive: <code>{summary.get('responsive_count', fast.get('responsive_count', '-'))}</code> node",
        f"Profil stabil: <code>{len((profiles.get('profiles') or {})) if isinstance(profiles, dict) else 0}</code> group",
        f"Invalid total: <code>{invalid['invalid_total']}</code> | UUID: <code>{invalid['invalid_uuid']}</code> | Blacklist: <code>{invalid['blacklist']}</code>",
        f"Source: OK <code>{sources['source_ok']}</code> | Cache <code>{sources['source_cached']}</code> | Failed <code>{sources['source_failed']}</code>",
        f"YAML validation: <code>{'OK' if validation['ok'] else 'CHECK'}</code> ({validation['ok_count']}/{validation['file_count']})",
        f"Run mode: <code>{summary.get('run_mode', RUN_MODE or '-')}</code>",
        "",
    ]

    if reuse.get("reuse_previous_output"):
        lines.extend([
            "♻️ Reuse output sebelumnya: <code>AKTIF</code>",
            f"Alasan: <code>{str(reuse.get('reason', '-'))[:500]}</code>",
            f"Proxy lengkap: <code>{reuse.get('openclash_proxy_count', '-')}</code> | strict: <code>{reuse.get('strict_proxy_count', '-')}</code> | lite: <code>{reuse.get('lite_proxy_count', '-')}</code>",
            "",
        ])

    if protocol_rows:
        lines.append("Per protokol:")
        for row in protocol_rows:
            lines.append(
                f"- {row.get('protocol', '-').upper()}: "
                f"alive <code>{row.get('alive_count', '0')}</code>, "
                f"dead <code>{row.get('dead_count', '0')}</code>, "
                f"output <code>{row.get('final_output_count', '0')}</code>"
            )

    top5_rows = read_top5_rows()
    if top5_rows:
        lines.extend(["", "Top 5 URL-Test:"])
        for idx, row in enumerate(top5_rows, start=1):
            score = row.get("rank_score") or row.get("delay_ms") or "-"
            lines.append(
                f"- #{idx} {row.get('name', '-')} "
                f"(<code>{row.get('delay_ms', '-')} ms</code>, score <code>{score}</code>, "
                f"{row.get('protocol', '-').upper()}, {row.get('country', '-')})"
            )

    tester_message = summary.get("tester_message")
    if tester_message:
        lines.extend(["", f"Info: <code>{str(tester_message)[:500]}</code>"])

    lines.extend(
        [
            "",
            "File utama: <code>output/lengkap.yaml</code>",
            "File alive: <code>output/lengkap_alive.yaml</code>",
            "File strict: <code>output/strict_alive.yaml</code>",
            "File ringan: <code>output/lite.yaml</code>",
            "File responsif: <code>output/fast.yaml</code>",
            "Laporan: <code>output/Alive/check_result.csv</code>",
        ]
    )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["success", "failure"], required=True)
    args = parser.parse_args()

    if args.stage == "failure":
        send_message("❌ Update OpenClash gagal\nCek log di GitHub Actions.")
        return

    send_message(success_message())

    if SEND_FILE:
        send_document("output/lengkap.yaml", "✅ lengkap.yaml terbaru")
        send_document("output/lengkap_alive.yaml", "✅ lengkap_alive.yaml")
        send_document("output/fast.yaml", "⚡ fast.yaml responsif")
        send_document("output/strict_alive.yaml", "🛡️ strict_alive.yaml")
        send_document("output/lite.yaml", "⚡ lite.yaml")
        send_document("output/Alive/check_result.csv", "🧪 check_result.csv")
        send_document("output/Alive/alive.csv", "✅ alive.csv")
        send_document("output/Alive/dead.csv", "❌ dead.csv")
        send_document("output/BestPing/top5_indonesia_ping.csv", "🏆 top5_indonesia_ping.csv")
        send_document("output/BestPing/top5_indonesia_ping.yaml", "🏆 top5_indonesia_ping.yaml")
        send_document("output/Source/source_status.csv", "📡 source_status.csv")


if __name__ == "__main__":
    main()

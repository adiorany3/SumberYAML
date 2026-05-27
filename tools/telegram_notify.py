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


def read_summary():
    path = Path("output/Alive/summary_alive.json")
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_protocol_rows():
    path = Path("output/summary_protocol.csv")
    if not path.exists():
        return []

    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def read_top10_rows():
    path = Path("output/BestPing/top10_indonesia.csv")
    if not path.exists():
        return []

    try:
        with path.open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))[:10]
    except Exception:
        return []


def success_message():
    summary = read_summary()
    protocol_rows = read_protocol_rows()

    lines = [
        mode_title(),
        "",
        f"Total valid: `{summary.get('total', '-')}`",
        f"Hidup: `{summary.get('alive', '-')}`",
        f"Mati: `{summary.get('dead', '-')}`",
        f"Untested: `{summary.get('untested', '-')}`",
        f"Tester: `{summary.get('tester', '-')}`",
        f"Filter alive only: `{summary.get('filter_alive_only', '-')}`",
        f"Run mode: `{summary.get('run_mode', RUN_MODE or '-')}`",
        "",
    ]

    if protocol_rows:
        lines.append("Per protokol:")
        for row in protocol_rows:
            lines.append(
                f"- {row.get('protocol', '-').upper()}: "
                f"alive `{row.get('alive_count', '0')}`, "
                f"dead `{row.get('dead_count', '0')}`, "
                f"output `{row.get('final_output_count', '0')}`"
            )

    top10_rows = read_top10_rows()
    if top10_rows:
        lines.extend(["", "Top 10 Balance:"])
        for idx, row in enumerate(top10_rows, start=1):
            lines.append(
                f"- #{idx} {row.get('name', '-')} "
                f"(`{row.get('delay_ms', '-')} ms`, "
                f"{row.get('protocol', '-').upper()}, "
                f"{row.get('country', '-')})"
            )

    tester_message = summary.get("tester_message")
    if tester_message:
        lines.extend(["", f"Info: `{tester_message[:500]}`"])

    lines.extend(
        [
            "",
            "File utama: `output/lengkap.yaml`",
            "Laporan: `output/Alive/check_result.csv`",
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
        send_document("output/Alive/check_result.csv", "🧪 check_result.csv")
        send_document("output/Alive/alive.csv", "✅ alive.csv")
        send_document("output/Alive/dead.csv", "❌ dead.csv")
        send_document("output/BestPing/top10_indonesia.csv", "🏆 top10_indonesia.csv")
        send_document("output/BestPing/top10_indonesia.yaml", "🏆 top10_indonesia.yaml")


if __name__ == "__main__":
    main()

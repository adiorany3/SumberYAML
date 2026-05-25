import argparse
import csv
import os
import time
from pathlib import Path

import requests


def env(name, default=""):
    return os.getenv(name, default).strip()


def telegram_request(method, data=None, files=None, timeout=60):
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN kosong. Notifikasi dilewati.")
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    response = requests.post(url, data=data or {}, files=files, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload


def send_message(chat_id, text):
    if not chat_id:
        print("TELEGRAM_CHAT_ID kosong. Notifikasi dilewati.")
        return
    max_len = 3900
    parts = [text[i:i + max_len] for i in range(0, len(text), max_len)] or [""]
    for part in parts:
        telegram_request(
            "sendMessage",
            data={
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )


def send_document(chat_id, file_path, caption=""):
    path = Path(file_path)
    if not chat_id or not path.exists() or not path.is_file():
        return False
    with path.open("rb") as f:
        telegram_request(
            "sendDocument",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"document": (path.name, f)},
            timeout=120,
        )
    return True


def read_protocol_summary():
    path = Path("output/summary_protocol.csv")
    if not path.exists():
        return [], {}
    rows = []
    totals = {
        "raw": 0,
        "valid": 0,
        "invalid": 0,
        "duplicate": 0,
        "renamed": 0,
    }
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            totals["raw"] += int(row.get("raw_count") or 0)
            totals["valid"] += int(row.get("yaml_valid_count") or 0)
            totals["invalid"] += int(row.get("invalid_count") or 0)
            totals["duplicate"] += int(row.get("duplicate_count") or 0)
            totals["renamed"] += int(row.get("renamed_count") or 0)
    return rows, totals


def count_countries():
    path = Path("output/Country/summary_country.csv")
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def workflow_url():
    server = env("GITHUB_SERVER_URL", "https://github.com")
    repo = env("GITHUB_REPOSITORY")
    run_id = env("GITHUB_RUN_ID")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def success_text():
    rows, totals = read_protocol_summary()
    countries = count_countries()
    main_file = Path("output/lengkap.yaml")
    size_kb = main_file.stat().st_size / 1024 if main_file.exists() else 0
    lines = []
    for row in rows:
        lines.append(
            f"- {row.get('protocol', '').upper()}: valid {row.get('yaml_valid_count', '0')} | "
            f"raw {row.get('raw_count', '0')} | invalid {row.get('invalid_count', '0')} | "
            f"duplikat {row.get('duplicate_count', '0')} | rename {row.get('renamed_count', '0')}"
        )
    detail = "\n".join(lines) if lines else "- Summary protocol tidak ditemukan."
    url = workflow_url()
    url_line = f"\nWorkflow: {url}" if url else ""
    branch = env("GITHUB_REF_NAME")
    sha = env("GITHUB_SHA")[:7]
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return (
        "✅ <b>Update OpenClash GitHub selesai</b>\n\n"
        f"File utama: <code>output/lengkap.yaml</code>\n"
        f"Ukuran file: <b>{size_kb:.1f} KB</b>\n"
        f"Total valid: <b>{totals.get('valid', 0)}</b> proxy\n"
        f"Total negara: <b>{countries}</b>\n"
        f"Duplikat dihapus: <b>{totals.get('duplicate', 0)}</b>\n"
        f"Name direname: <b>{totals.get('renamed', 0)}</b>\n"
        f"Invalid: <b>{totals.get('invalid', 0)}</b>\n"
        f"Branch: <code>{branch}</code>\n"
        f"Commit: <code>{sha}</code>\n"
        f"Waktu: <b>{now}</b>\n"
        f"{url_line}\n\n"
        "<b>Ringkasan protocol:</b>\n"
        f"{detail}"
    )


def failure_text():
    url = workflow_url()
    url_line = f"\nWorkflow: {url}" if url else ""
    branch = env("GITHUB_REF_NAME")
    sha = env("GITHUB_SHA")[:7]
    return (
        "❌ <b>Update OpenClash GitHub gagal</b>\n\n"
        f"Branch: <code>{branch}</code>\n"
        f"Commit: <code>{sha}</code>"
        f"{url_line}\n\n"
        "Silakan cek log GitHub Actions."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["success", "failure"], required=True)
    args = parser.parse_args()

    chat_id = env("TELEGRAM_CHAT_ID") or env("TELEGRAM_ALLOWED_CHAT_ID")
    if not env("TELEGRAM_BOT_TOKEN") or not chat_id:
        print("Secret Telegram belum lengkap. Notifikasi dilewati.")
        return

    if args.stage == "success":
        send_message(chat_id, success_text())
        send_file = env("TELEGRAM_SEND_OUTPUT_FILE", "true").lower() in {"1", "true", "yes", "y", "on"}
        if send_file:
            send_document(chat_id, "output/lengkap.yaml", caption="lengkap.yaml hasil update GitHub terbaru")
    else:
        send_message(chat_id, failure_text())


if __name__ == "__main__":
    main()

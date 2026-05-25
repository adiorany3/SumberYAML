import json
import os
import time
import traceback

import requests


def env(name, default=""):
    return os.getenv(name, default).strip()


TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_CHAT_ID = env("TELEGRAM_ALLOWED_CHAT_ID") or env("TELEGRAM_CHAT_ID")
TELEGRAM_POLL_TIMEOUT = int(env("TELEGRAM_POLL_TIMEOUT", "30"))

GITHUB_TOKEN = env("GITHUB_TOKEN")
GITHUB_OWNER = env("GITHUB_OWNER")
GITHUB_REPO = env("GITHUB_REPO")
GITHUB_REF = env("GITHUB_REF", "main")
GITHUB_WORKFLOW_FILE = env("GITHUB_WORKFLOW_FILE", "update-openclash.yml")


def telegram_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def telegram_request(method, data=None, timeout=60):
    response = requests.post(telegram_url(method), data=data or {}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload


def send_message(chat_id, text):
    telegram_request(
        "sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )


def allowed_chat(chat_id):
    if not TELEGRAM_ALLOWED_CHAT_ID:
        return True
    allowed = {item.strip() for item in TELEGRAM_ALLOWED_CHAT_ID.split(",") if item.strip()}
    return str(chat_id) in allowed


def github_headers():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN belum diisi.")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_base():
    if not GITHUB_OWNER or not GITHUB_REPO:
        raise RuntimeError("GITHUB_OWNER dan GITHUB_REPO wajib diisi.")
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


def dispatch_workflow():
    url = f"{github_base()}/actions/workflows/{GITHUB_WORKFLOW_FILE}/dispatches"
    payload = {
        "ref": GITHUB_REF,
        "inputs": {"source": "telegram"},
    }
    response = requests.post(url, headers=github_headers(), json=payload, timeout=30)
    if response.status_code not in (200, 201, 202, 204):
        raise RuntimeError(f"GitHub dispatch gagal: {response.status_code} {response.text}")
    return True


def latest_workflow_run():
    url = f"{github_base()}/actions/workflows/{GITHUB_WORKFLOW_FILE}/runs"
    response = requests.get(
        url,
        headers=github_headers(),
        params={"branch": GITHUB_REF, "per_page": 1},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    runs = data.get("workflow_runs", [])
    return runs[0] if runs else None


def handle_update(chat_id):
    dispatch_workflow()
    send_message(
        chat_id,
        "✅ <b>GitHub Actions sudah dipicu</b>\n"
        "Update akan berjalan di repository GitHub. Setelah selesai, workflow akan mengirim notifikasi dan file <code>lengkap.yaml</code>.",
    )


def handle_status(chat_id):
    run = latest_workflow_run()
    if not run:
        send_message(chat_id, "Belum ada riwayat workflow.")
        return
    status = run.get("status")
    conclusion = run.get("conclusion") or "-"
    url = run.get("html_url", "")
    created = run.get("created_at", "")
    send_message(
        chat_id,
        "<b>Status GitHub Actions terakhir</b>\n"
        f"Status: <code>{status}</code>\n"
        f"Conclusion: <code>{conclusion}</code>\n"
        f"Created: <code>{created}</code>\n"
        f"URL: {url}",
    )


def handle_help(chat_id):
    send_message(
        chat_id,
        "<b>Command tersedia:</b>\n"
        "/update - jalankan update via GitHub Actions\n"
        "/status - cek workflow GitHub terakhir\n"
        "/id - tampilkan chat_id Telegram\n"
        "/help - bantuan"
    )


def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diisi.")
    offset = None
    print("Telegram GitHub dispatch bot aktif.")
    while True:
        try:
            data = {
                "timeout": TELEGRAM_POLL_TIMEOUT,
                "allowed_updates": json.dumps(["message"]),
            }
            if offset is not None:
                data["offset"] = offset
            payload = telegram_request("getUpdates", data=data, timeout=TELEGRAM_POLL_TIMEOUT + 15)
            for update in payload.get("result", []):
                offset = update.get("update_id", 0) + 1
                message = update.get("message") or {}
                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                text = (message.get("text") or "").strip()
                if not chat_id or not text:
                    continue
                if not allowed_chat(chat_id):
                    print(f"Ignored unauthorized chat_id: {chat_id}")
                    continue
                command = text.split()[0].split("@")[0].lower()
                try:
                    if command == "/update":
                        handle_update(chat_id)
                    elif command == "/status":
                        handle_status(chat_id)
                    elif command == "/id":
                        send_message(chat_id, f"Chat ID Anda: <code>{chat_id}</code>")
                    elif command in ("/start", "/help"):
                        handle_help(chat_id)
                    else:
                        send_message(chat_id, "Command tidak dikenal. Gunakan /help.")
                except Exception as exc:
                    send_message(chat_id, f"❌ Error: <code>{str(exc)}</code>")
                    print(traceback.format_exc())
        except KeyboardInterrupt:
            print("Bot dihentikan.")
            break
        except Exception as exc:
            print("Polling error:", exc)
            time.sleep(5)


if __name__ == "__main__":
    run_bot()

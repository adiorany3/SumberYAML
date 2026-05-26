import json
import os
import posixpath
import threading
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import streamlit as st
import streamlit.components.v1 as components


# =========================
# STREAMLIT ROBOT UI SETUP
# =========================
st.set_page_config(
    page_title="Yamlku Bot",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Tampilan hanya robot animasi. Bot Telegram tetap berjalan di background.
st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;}
        [data-testid="stDecoration"] {visibility: hidden;}
        [data-testid="stStatusWidget"] {visibility: hidden;}

        html, body, [data-testid="stAppViewContainer"] {
            min-height: 100vh;
            background:
                radial-gradient(circle at 50% 25%, rgba(85, 160, 255, 0.18), transparent 32%),
                linear-gradient(180deg, #070b16 0%, #0a1020 48%, #05070d 100%);
        }

        .block-container {
            max-width: 100% !important;
            padding: 0 !important;
            margin: 0 !important;
        }

        .robot-stage {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .robot-wrap {
            width: min(48vw, 280px);
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            animation: robot-float 3s ease-in-out infinite;
        }

        .robot-glow {
            position: absolute;
            width: 80%;
            height: 80%;
            border-radius: 999px;
            background: rgba(70, 155, 255, 0.16);
            filter: blur(32px);
            animation: glow-pulse 2.4s ease-in-out infinite;
        }

        .robot-svg {
            position: relative;
            width: 100%;
            height: 100%;
            filter: drop-shadow(0 24px 42px rgba(0, 0, 0, 0.45));
        }

        .robot-eye {
            animation: eye-blink 4s ease-in-out infinite;
            transform-origin: center;
        }

        .robot-antenna-light {
            animation: light-pulse 1.4s ease-in-out infinite;
        }

        .robot-arm-left {
            transform-origin: 58px 145px;
            animation: arm-wave-left 2.4s ease-in-out infinite;
        }

        .robot-arm-right {
            transform-origin: 222px 145px;
            animation: arm-wave-right 2.4s ease-in-out infinite;
        }

        @keyframes robot-float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-14px); }
        }

        @keyframes glow-pulse {
            0%, 100% { opacity: 0.58; transform: scale(0.96); }
            50% { opacity: 1; transform: scale(1.08); }
        }

        @keyframes eye-blink {
            0%, 44%, 52%, 100% { transform: scaleY(1); opacity: 1; }
            48% { transform: scaleY(0.12); opacity: 0.85; }
        }

        @keyframes light-pulse {
            0%, 100% { opacity: 0.45; }
            50% { opacity: 1; }
        }

        @keyframes arm-wave-left {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(-8deg); }
        }

        @keyframes arm-wave-right {
            0%, 100% { transform: rotate(0deg); }
            50% { transform: rotate(8deg); }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# CONFIG HELPERS
# =========================
def get_setting(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        if name in st.secrets:
            value = st.secrets.get(name, default)
            return str(value).strip()
    except Exception:
        pass
    return str(os.getenv(name, default)).strip()


def get_int_setting(name: str, default: int) -> int:
    try:
        return int(get_setting(name, str(default)) or default)
    except Exception:
        return default


TELEGRAM_BOT_TOKEN = get_setting("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_CHAT_ID = get_setting("TELEGRAM_ALLOWED_CHAT_ID") or get_setting("TELEGRAM_CHAT_ID")
TELEGRAM_POLL_TIMEOUT = get_int_setting("TELEGRAM_POLL_TIMEOUT", 25)

# Token GitHub untuk memicu workflow_dispatch.
GITHUB_TOKEN = (
    get_setting("GITHUB_TOKEN")
    or get_setting("GH_TOKEN")
    or get_setting("GITHUB_PAT")
)

# Bisa pakai GITHUB_REPOSITORY="owner/repo" atau GITHUB_OWNER + GITHUB_REPO.
GITHUB_REPOSITORY = get_setting("GITHUB_REPOSITORY")
GITHUB_OWNER = get_setting("GITHUB_OWNER")
GITHUB_REPO = get_setting("GITHUB_REPO")

if GITHUB_REPOSITORY and "/" in GITHUB_REPOSITORY:
    repo_owner, repo_name = GITHUB_REPOSITORY.split("/", 1)
    GITHUB_OWNER = GITHUB_OWNER or repo_owner
    GITHUB_REPO = GITHUB_REPO or repo_name

GITHUB_REF = get_setting("GITHUB_REF", "main")
GITHUB_WORKFLOW_FILE = get_setting("GITHUB_WORKFLOW_FILE", "update-openclash.yml")


# =========================
# UTILITY FUNCTIONS
# =========================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_workflow_id(value: str) -> str:
    """GitHub API accepts the workflow filename, e.g. update-openclash.yml.
    If user fills .github/workflows/update-openclash.yml, use basename only.
    """
    value = (value or "update-openclash.yml").strip().replace("\\", "/")
    return posixpath.basename(value)


WORKFLOW_ID = normalize_workflow_id(GITHUB_WORKFLOW_FILE)


class BotState:
    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = now_iso()
        self.last_update_at = "-"
        self.last_error = "-"
        self.last_command = "-"
        self.thread_alive = False

    def set(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def snapshot(self):
        with self.lock:
            return {
                "started_at": self.started_at,
                "last_update_at": self.last_update_at,
                "last_error": self.last_error,
                "last_command": self.last_command,
                "thread_alive": self.thread_alive,
            }


BOT_STATE = BotState()


def telegram_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def telegram_request(method: str, data=None, timeout: int = 60):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di Streamlit Secrets.")

    response = requests.post(
        telegram_url(method),
        data=data or {},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload.get("ok"):
        raise RuntimeError(str(payload))

    return payload


def send_message(chat_id, text: str):
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


def allowed_chat(chat_id) -> bool:
    if not TELEGRAM_ALLOWED_CHAT_ID:
        return True

    allowed = {
        item.strip()
        for item in str(TELEGRAM_ALLOWED_CHAT_ID).split(",")
        if item.strip()
    }
    return str(chat_id) in allowed


def github_headers():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN/GH_TOKEN/GITHUB_PAT belum diisi di Streamlit Secrets.")

    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_base() -> str:
    if not GITHUB_OWNER or not GITHUB_REPO:
        raise RuntimeError(
            "GITHUB_REPOSITORY belum diisi. Format yang benar: owner/repo. "
            "Alternatif: isi GITHUB_OWNER dan GITHUB_REPO."
        )

    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


def parse_github_error(response) -> str:
    text = response.text

    try:
        data = response.json()
        message = data.get("message") or text
        documentation_url = data.get("documentation_url") or ""
    except Exception:
        message = text
        documentation_url = ""

    hint = ""

    if response.status_code == 401:
        hint = "Token GitHub salah/kedaluwarsa. Buat Personal Access Token baru."
    elif response.status_code == 403:
        hint = "Token GitHub tidak punya izin Actions: Read and write, atau akses repo ditolak."
    elif response.status_code == 404:
        hint = (
            "Repo/workflow tidak ditemukan, workflow belum ada di default branch, "
            "nama workflow salah, atau token tidak punya akses repo."
        )
    elif response.status_code == 422:
        hint = "Branch/ref salah atau input workflow_dispatch tidak cocok. Cek GITHUB_REF."

    return (
        f"GitHub API error {response.status_code}: {message}\n"
        f"Hint: {hint}\n"
        f"Docs: {documentation_url}"
    ).strip()


def get_workflow():
    workflow = quote(WORKFLOW_ID, safe="")
    url = f"{github_base()}/actions/workflows/{workflow}"

    response = requests.get(
        url,
        headers=github_headers(),
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(parse_github_error(response))

    return response.json()


def dispatch_workflow(mode='update', enable_proxy_test='true', filter_alive_only='true'):
    workflow_info = get_workflow()

    if workflow_info.get("state") != "active":
        raise RuntimeError(
            f"Workflow ditemukan, tetapi state bukan active: {workflow_info.get('state')}"
        )

    workflow = quote(WORKFLOW_ID, safe="")
    url = f"{github_base()}/actions/workflows/{workflow}/dispatches"

    payload = {
        "ref": GITHUB_REF,
        "inputs": {
            "source": "telegram-streamlit",
            "mode": mode,
            "enable_proxy_test": enable_proxy_test,
            "filter_alive_only": filter_alive_only,
        },
    }

    response = requests.post(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )

    if response.status_code not in (200, 201, 202, 204):
        raise RuntimeError(parse_github_error(response))

    return {
        "message": "dispatched",
        "workflow": workflow_info.get("name", WORKFLOW_ID),
    }


def latest_workflow_run():
    workflow = quote(WORKFLOW_ID, safe="")
    url = f"{github_base()}/actions/workflows/{workflow}/runs"

    response = requests.get(
        url,
        headers=github_headers(),
        params={
            "branch": GITHUB_REF,
            "per_page": 1,
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(parse_github_error(response))

    data = response.json()
    runs = data.get("workflow_runs", [])
    return runs[0] if runs else None


# =========================
# COMMAND HANDLERS
# =========================
def handle_update(chat_id):
    result = dispatch_workflow()

    send_message(
        chat_id,
        "✅ <b>Update berhasil dipicu dari Streamlit</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow: <code>{WORKFLOW_ID}</code>\n"
        f"Branch/ref: <code>{GITHUB_REF}</code>\n\n"
        "Tunggu notifikasi final dari GitHub Actions setelah file <code>output/lengkap.yaml</code> selesai dibuat.",
    )

    return result


def handle_test(chat_id):
    """Trigger GitHub Actions untuk menjalankan test proxy hidup/mati.

    Bedanya dengan /update:
    - /test tetap membuat laporan Alive/Dead.
    - /test tidak memaksa output utama hanya proxy hidup, supaya aman untuk diagnosis.
    - Notifikasi final tetap dikirim oleh GitHub Actions setelah workflow selesai.
    """
    result = dispatch_workflow(
        mode="test",
        enable_proxy_test="true",
        filter_alive_only="false",
    )

    send_message(
        chat_id,
        "🧪 <b>Test proxy berhasil dipicu dari Streamlit</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow: <code>{WORKFLOW_ID}</code>\n"
        f"Branch/ref: <code>{GITHUB_REF}</code>\n\n"
        "GitHub Actions akan membuat laporan:\n"
        "- <code>output/Alive/check_result.csv</code>\n"
        "- <code>output/Alive/alive.csv</code>\n"
        "- <code>output/Alive/dead.csv</code>\n\n"
        "Tunggu notifikasi final dari GitHub Actions.",
    )

    return result


def handle_status(chat_id):
    run = latest_workflow_run()

    if not run:
        send_message(chat_id, "Belum ada riwayat workflow.")
        return

    status = run.get("status")
    conclusion = run.get("conclusion") or "-"
    html_url = run.get("html_url", "")
    created_at = run.get("created_at", "")

    send_message(
        chat_id,
        "<b>Status GitHub Actions terakhir</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow: <code>{WORKFLOW_ID}</code>\n"
        f"Status: <code>{status}</code>\n"
        f"Conclusion: <code>{conclusion}</code>\n"
        f"Created: <code>{created_at}</code>\n"
        f"URL: {html_url}",
    )


def handle_check(chat_id):
    issues = []

    if not TELEGRAM_BOT_TOKEN:
        issues.append("TELEGRAM_BOT_TOKEN kosong")
    if not GITHUB_TOKEN:
        issues.append("GITHUB_TOKEN/GH_TOKEN/GITHUB_PAT kosong")
    if not GITHUB_OWNER or not GITHUB_REPO:
        issues.append("GITHUB_REPOSITORY kosong atau formatnya bukan owner/repo")
    if not GITHUB_REF:
        issues.append("GITHUB_REF kosong")
    if not WORKFLOW_ID:
        issues.append("GITHUB_WORKFLOW_FILE kosong")

    if issues:
        send_message(
            chat_id,
            "❌ <b>Konfigurasi belum lengkap</b>\n- " + "\n- ".join(issues),
        )
        return

    workflow_info = get_workflow()

    send_message(
        chat_id,
        "✅ <b>Konfigurasi Streamlit Dispatcher OK</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow file: <code>{WORKFLOW_ID}</code>\n"
        f"Workflow name: <code>{workflow_info.get('name')}</code>\n"
        f"State: <code>{workflow_info.get('state')}</code>\n"
        f"Path: <code>{workflow_info.get('path')}</code>\n"
        f"Ref: <code>{GITHUB_REF}</code>",
    )


def handle_help(chat_id):
    send_message(
        chat_id,
        "<b>Command tersedia:</b>\n"
        "/update - jalankan update via GitHub Actions\n"
        "/test - cek proxy hidup/mati via GitHub Actions\n"
        "/status - cek workflow GitHub terakhir\n"
        "/check - cek konfigurasi token/repo/workflow\n"
        "/id - tampilkan chat ID\n"
        "/help - bantuan",
    )


def handle_command(chat_id, text: str):
    command = text.split()[0].split("@")[0].lower()
    BOT_STATE.set(last_command=command, last_update_at=now_iso())

    if command == "/update":
        return handle_update(chat_id)
    if command == "/test":
        return handle_test(chat_id)
    if command == "/status":
        return handle_status(chat_id)
    if command == "/check":
        return handle_check(chat_id)
    if command == "/id":
        return send_message(chat_id, f"Chat ID Anda: <code>{chat_id}</code>")
    if command in ("/start", "/help"):
        return handle_help(chat_id)

    return send_message(chat_id, "Command tidak dikenal. Gunakan /help.")


# =========================
# TELEGRAM POLLING THREAD
# =========================
def polling_loop():
    offset = None
    BOT_STATE.set(thread_alive=True)

    while True:
        try:
            if not TELEGRAM_BOT_TOKEN:
                BOT_STATE.set(
                    last_error="TELEGRAM_BOT_TOKEN belum diisi di Streamlit Secrets.",
                    thread_alive=True,
                )
                time.sleep(20)
                continue

            data = {
                "timeout": TELEGRAM_POLL_TIMEOUT,
                "allowed_updates": json.dumps(["message"]),
            }

            if offset is not None:
                data["offset"] = offset

            payload = telegram_request(
                "getUpdates",
                data=data,
                timeout=TELEGRAM_POLL_TIMEOUT + 15,
            )

            for update in payload.get("result", []):
                offset = update.get("update_id", 0) + 1

                message = update.get("message") or {}
                chat = message.get("chat") or {}
                chat_id = chat.get("id")
                text = (message.get("text") or "").strip()

                if not chat_id or not text:
                    continue

                if not allowed_chat(chat_id):
                    continue

                try:
                    handle_command(chat_id, text)
                    BOT_STATE.set(last_error="-")
                except Exception as exc:
                    BOT_STATE.set(last_error=str(exc))
                    send_message(chat_id, f"❌ Error:\n<code>{str(exc)}</code>")
                    print(traceback.format_exc())

        except Exception as exc:
            BOT_STATE.set(last_error=str(exc), thread_alive=True)
            print("Polling error:", exc)
            time.sleep(5)


@st.cache_resource(show_spinner=False)
def start_bot_once():
    thread = threading.Thread(
        target=polling_loop,
        name="telegram-github-dispatcher",
        daemon=True,
    )
    thread.start()
    return thread


thread = start_bot_once()
BOT_STATE.set(thread_alive=thread.is_alive())

# Tampilan publik: robot animasi saja.
# Pakai components.html agar SVG tidak muncul sebagai teks biasa di Streamlit.
ROBOT_HTML = """
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
    html, body {
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: transparent;
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .robot-stage {
        min-height: 520px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        background: transparent;
    }

    .robot-wrap {
        width: min(54vw, 320px);
        max-width: 320px;
        aspect-ratio: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        animation: robot-float 3s ease-in-out infinite;
    }

    .robot-glow {
        position: absolute;
        width: 80%;
        height: 80%;
        border-radius: 999px;
        background: rgba(70, 155, 255, 0.16);
        filter: blur(32px);
        animation: glow-pulse 2.4s ease-in-out infinite;
    }

    .robot-svg {
        position: relative;
        width: 100%;
        height: 100%;
        filter: drop-shadow(0 24px 42px rgba(0, 0, 0, 0.45));
    }

    .robot-eye {
        animation: eye-blink 4s ease-in-out infinite;
        transform-origin: center;
    }

    .robot-antenna-light {
        animation: light-pulse 1.4s ease-in-out infinite;
    }

    .robot-arm-left {
        transform-origin: 58px 145px;
        animation: arm-wave-left 2.4s ease-in-out infinite;
    }

    .robot-arm-right {
        transform-origin: 222px 145px;
        animation: arm-wave-right 2.4s ease-in-out infinite;
    }

    @keyframes robot-float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-14px); }
    }

    @keyframes glow-pulse {
        0%, 100% { opacity: 0.58; transform: scale(0.96); }
        50% { opacity: 1; transform: scale(1.08); }
    }

    @keyframes eye-blink {
        0%, 44%, 52%, 100% { transform: scaleY(1); opacity: 1; }
        48% { transform: scaleY(0.12); opacity: 0.85; }
    }

    @keyframes light-pulse {
        0%, 100% { opacity: 0.45; }
        50% { opacity: 1; }
    }

    @keyframes arm-wave-left {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(-8deg); }
    }

    @keyframes arm-wave-right {
        0%, 100% { transform: rotate(0deg); }
        50% { transform: rotate(8deg); }
    }
</style>
</head>
<body>
    <div class="robot-stage" aria-label="Animated robot">
        <div class="robot-wrap">
            <div class="robot-glow"></div>
            <svg class="robot-svg" viewBox="0 0 280 280" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Robot animation">
                <defs>
                    <linearGradient id="bodyGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stop-color="#f7fbff"/>
                        <stop offset="100%" stop-color="#9fb8d9"/>
                    </linearGradient>
                    <linearGradient id="screenGrad" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stop-color="#17233c"/>
                        <stop offset="100%" stop-color="#07101f"/>
                    </linearGradient>
                </defs>

                <ellipse cx="140" cy="242" rx="68" ry="14" fill="rgba(0,0,0,0.28)"/>

                <line x1="140" y1="62" x2="140" y2="36" stroke="#b7c8df" stroke-width="8" stroke-linecap="round"/>
                <circle class="robot-antenna-light" cx="140" cy="28" r="11" fill="#4dd5ff"/>

                <g class="robot-arm-left">
                    <rect x="35" y="128" width="42" height="24" rx="12" fill="#8ca6c9"/>
                    <circle cx="34" cy="140" r="12" fill="#c8d8ec"/>
                </g>

                <g class="robot-arm-right">
                    <rect x="203" y="128" width="42" height="24" rx="12" fill="#8ca6c9"/>
                    <circle cx="246" cy="140" r="12" fill="#c8d8ec"/>
                </g>

                <rect x="72" y="68" width="136" height="130" rx="38" fill="url(#bodyGrad)"/>
                <rect x="91" y="95" width="98" height="58" rx="24" fill="url(#screenGrad)"/>

                <circle class="robot-eye" cx="120" cy="124" r="9" fill="#52e6ff"/>
                <circle class="robot-eye" cx="160" cy="124" r="9" fill="#52e6ff"/>
                <path d="M124 145 Q140 157 156 145" fill="none" stroke="#52e6ff" stroke-width="5" stroke-linecap="round"/>

                <rect x="105" y="170" width="70" height="16" rx="8" fill="#dce8f7"/>
                <circle cx="119" cy="178" r="4" fill="#6d87aa"/>
                <circle cx="140" cy="178" r="4" fill="#6d87aa"/>
                <circle cx="161" cy="178" r="4" fill="#6d87aa"/>
            </svg>
        </div>
    </div>
</body>
</html>
"""

components.html(
    ROBOT_HTML,
    height=540,
    scrolling=False,
)

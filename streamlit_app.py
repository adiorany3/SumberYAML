import base64
import csv
import io
import json
import os
import re
import posixpath
import threading
import time
import traceback
from datetime import datetime, timezone
from urllib.parse import quote
from html import escape

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

# Panel Best Ping di Streamlit dan command Telegram /best.
BEST_PING_SOURCE_LABEL = get_setting("BEST_PING_SOURCE_LABEL", "Indonesia")
BEST_PING_LIMIT = get_int_setting("BEST_PING_LIMIT", 8)
# Opsional: isi ID jika hanya ingin menampilkan server negara Indonesia.
# Kosongkan agar menampilkan proxy alive tercepat dari semua negara.
BEST_PING_COUNTRY_FILTER = get_setting("BEST_PING_COUNTRY_FILTER", "").upper()


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
# BEST PING HELPERS
# =========================
def github_contents_url(path: str) -> str:
    clean_path = quote(path.strip('/'), safe='/')
    return f"{github_base()}/contents/{clean_path}"


def fetch_github_file_text(path: str) -> str:
    """Ambil file output dari repo GitHub.

    Menggunakan GitHub Contents API agar tetap bisa membaca repo private selama token benar.
    Jika gagal, fallback ke raw.githubusercontent.com untuk repo public.
    """
    api_error = None

    try:
        response = requests.get(
            github_contents_url(path),
            headers=github_headers(),
            params={"ref": GITHUB_REF},
            timeout=30,
        )

        if response.ok:
            data = response.json()
            content = data.get("content", "")
            encoding = data.get("encoding", "")

            if encoding == "base64" and content:
                return base64.b64decode(content).decode("utf-8", errors="replace")

            download_url = data.get("download_url")
            if download_url:
                raw_response = requests.get(download_url, timeout=30)
                raw_response.raise_for_status()
                return raw_response.text

            raise RuntimeError(f"File {path} ditemukan, tetapi content kosong.")

        api_error = parse_github_error(response)
    except Exception as exc:
        api_error = str(exc)

    raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_REF}/{path.strip('/')}"
    raw_response = requests.get(raw_url, timeout=30)

    if raw_response.ok:
        return raw_response.text

    raise RuntimeError(
        f"Gagal membaca {path}.\n"
        f"API error: {api_error}\n"
        f"Raw status: {raw_response.status_code}"
    )


def parse_delay_ms(value):
    if value is None:
        return None

    value_text = str(value).strip().lower()
    if not value_text:
        return None

    match = re.search(r"\d+", value_text)
    if not match:
        return None

    try:
        return int(match.group(0))
    except Exception:
        return None


def normalize_csv_row(row: dict) -> dict:
    delay = parse_delay_ms(row.get("delay_ms"))
    return {
        "protocol": str(row.get("protocol", "-")).strip() or "-",
        "name": str(row.get("name", "-")).strip() or "-",
        "country": str(row.get("country", "-")).strip() or "-",
        "server": str(row.get("server", "-")).strip() or "-",
        "port": str(row.get("port", "-")).strip() or "-",
        "network": str(row.get("network", "-")).strip() or "-",
        "status": str(row.get("status", "-")).strip().lower() or "-",
        "delay_ms": delay,
        "reason": str(row.get("reason", "")).strip(),
    }


def parse_check_csv(csv_text: str):
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    rows = []

    for row in reader:
        rows.append(normalize_csv_row(row))

    return rows


def count_proxy_names_from_lengkap_yaml() -> int:
    try:
        yaml_text = fetch_github_file_text("output/lengkap.yaml")
    except Exception:
        return 0

    matches = re.findall(r"(?m)^\s*-\s+name:\s*.+$", yaml_text)
    return len(matches)


@st.cache_data(ttl=60, show_spinner=False)
def load_best_ping_data(limit: int = None):
    limit = int(limit or BEST_PING_LIMIT or 8)
    paths = [
        "output/Alive/alive.csv",
        "output/Alive/check_result.csv",
    ]

    last_error = None
    rows = []
    source_path = "-"

    for path in paths:
        try:
            csv_text = fetch_github_file_text(path)
            rows = parse_check_csv(csv_text)
            source_path = path
            break
        except Exception as exc:
            last_error = exc

    if not rows and last_error:
        raise RuntimeError(str(last_error))

    alive_rows = [
        row for row in rows
        if row.get("status") == "alive" and row.get("delay_ms") is not None
    ]

    if BEST_PING_COUNTRY_FILTER:
        alive_rows = [
            row for row in alive_rows
            if row.get("country", "").upper() == BEST_PING_COUNTRY_FILTER
        ]

    alive_rows.sort(key=lambda item: item.get("delay_ms") or 999999)

    summary = {}
    try:
        summary_text = fetch_github_file_text("output/Alive/summary_alive.json")
        summary = json.loads(summary_text)
    except Exception:
        summary = {}

    return {
        "rows": alive_rows[:limit],
        "all_alive_count": len(alive_rows),
        "source_path": source_path,
        "summary": summary,
        "yaml_proxy_count": count_proxy_names_from_lengkap_yaml(),
        "source_label": BEST_PING_SOURCE_LABEL or "Indonesia",
        "country_filter": BEST_PING_COUNTRY_FILTER,
    }


def best_ping_text_for_telegram(limit: int = 10) -> str:
    data = load_best_ping_data(limit=limit)
    rows = data.get("rows", [])
    source_label = data.get("source_label", "Indonesia")
    country_filter = data.get("country_filter", "")

    if not rows:
        filter_text = f" untuk negara {country_filter}" if country_filter else ""
        return (
            f"📡 <b>Best Ping From {escape(source_label)}</b>\n"
            f"Belum ada data proxy alive{filter_text}.\n\n"
            "Jalankan <code>/test</code> atau <code>/update</code> dulu, lalu coba <code>/best</code> lagi."
        )

    lines = [
        f"🏆 <b>Best Ping From {escape(source_label)}</b>",
        f"Sumber: <code>{escape(data.get('source_path', '-'))}</code>",
        f"Proxy di lengkap.yaml: <code>{data.get('yaml_proxy_count', 0)}</code>",
        "",
    ]

    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"{idx}. <b>{escape(row['name'])}</b>\n"
            f"   Delay: <code>{row['delay_ms']} ms</code> | "
            f"{escape(row['protocol'])} | {escape(row['country'])} | "
            f"<code>{escape(row['server'])}:{escape(row['port'])}</code>"
        )

    return "\n".join(lines)

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


def handle_best(chat_id):
    send_message(chat_id, best_ping_text_for_telegram(limit=10))


def handle_help(chat_id):
    send_message(
        chat_id,
        "<b>Command tersedia:</b>\n"
        "/update - jalankan update via GitHub Actions\n"
        "/test - cek proxy hidup/mati via GitHub Actions\n"
        "/best - tampilkan best ping dari output/lengkap.yaml\n"
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
    if command == "/best":
        return handle_best(chat_id)
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

# =========================
# TAMAGOTCHI ROBOT UI
# =========================

PET_DEFAULTS = {
    "hunger": 82,
    "energy": 78,
    "happiness": 84,
    "hygiene": 76,
    "level": 1,
    "xp": 0,
    "last_tick": time.time(),
    "last_action_text": "Halo! Aku Yamlku Bot. Rawat aku sambil aku jaga update config kamu.",
}


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, int(round(value))))


def init_pet_state():
    if "pet" not in st.session_state:
        st.session_state.pet = dict(PET_DEFAULTS)


def decay_pet_state():
    pet = st.session_state.pet
    now = time.time()
    elapsed = max(0, now - float(pet.get("last_tick", now)))

    # Decay pelan, terasa seperti Tamagotchi tanpa terlalu cepat rusak.
    pet["hunger"] = clamp(pet.get("hunger", 80) - elapsed / 210)
    pet["energy"] = clamp(pet.get("energy", 80) - elapsed / 260)
    pet["happiness"] = clamp(pet.get("happiness", 80) - elapsed / 320)
    pet["hygiene"] = clamp(pet.get("hygiene", 80) - elapsed / 420)
    pet["last_tick"] = now


def add_xp(amount: int):
    pet = st.session_state.pet
    pet["xp"] = int(pet.get("xp", 0)) + amount

    while pet["xp"] >= 100:
        pet["xp"] -= 100
        pet["level"] = int(pet.get("level", 1)) + 1
        pet["last_action_text"] = f"Naik level! Sekarang aku level {pet['level']}."


def set_pet_action(message: str):
    st.session_state.pet["last_action_text"] = message
    st.session_state.pet["last_tick"] = time.time()


def action_feed():
    pet = st.session_state.pet
    pet["hunger"] = clamp(pet["hunger"] + 30)
    pet["happiness"] = clamp(pet["happiness"] + 7)
    pet["energy"] = clamp(pet["energy"] - 3)
    pet["hygiene"] = clamp(pet["hygiene"] - 3)
    set_pet_action("Nyam! Baterai data proxy makin siap diproses.")
    add_xp(12)


def action_play():
    pet = st.session_state.pet
    pet["happiness"] = clamp(pet["happiness"] + 28)
    pet["energy"] = clamp(pet["energy"] - 14)
    pet["hunger"] = clamp(pet["hunger"] - 9)
    pet["hygiene"] = clamp(pet["hygiene"] - 6)
    set_pet_action("Asik! Aku main sambil scan config.")
    add_xp(16)


def action_sleep():
    pet = st.session_state.pet
    pet["energy"] = clamp(pet["energy"] + 36)
    pet["hunger"] = clamp(pet["hunger"] - 5)
    pet["happiness"] = clamp(pet["happiness"] + 3)
    set_pet_action("Mode tidur aktif. Sistem adem, siap update lagi.")
    add_xp(9)


def action_clean():
    pet = st.session_state.pet
    pet["hygiene"] = clamp(pet["hygiene"] + 38)
    pet["happiness"] = clamp(pet["happiness"] + 5)
    set_pet_action("Bersih! Cache debu digital sudah dibuang.")
    add_xp(10)


def action_charge():
    pet = st.session_state.pet
    pet["energy"] = clamp(pet["energy"] + 26)
    pet["hunger"] = clamp(pet["hunger"] - 2)
    set_pet_action("Charging selesai. Antena Telegram siap standby.")
    add_xp(10)


def action_reset():
    st.session_state.pet = dict(PET_DEFAULTS)
    st.session_state.pet["last_tick"] = time.time()


def pet_mood():
    pet = st.session_state.pet
    if pet["energy"] < 20:
        return "sleepy", "Mengantuk"
    if pet["hunger"] < 22:
        return "hungry", "Lapar"
    if pet["hygiene"] < 22:
        return "dirty", "Kotor"
    if pet["happiness"] < 24:
        return "sad", "Sedih"
    avg = (pet["hunger"] + pet["energy"] + pet["happiness"] + pet["hygiene"]) / 4
    if avg >= 78:
        return "happy", "Bahagia"
    return "normal", "Normal"


def render_robot_html(mood: str, mood_label: str, message: str, level: int, xp: int) -> str:
    accent = {
        "happy": "#63f7b4",
        "normal": "#52e6ff",
        "sleepy": "#b9a7ff",
        "hungry": "#ffd166",
        "dirty": "#b5c09a",
        "sad": "#8fc3ff",
    }.get(mood, "#52e6ff")

    glow = {
        "happy": "rgba(99,247,180,0.25)",
        "normal": "rgba(82,230,255,0.20)",
        "sleepy": "rgba(185,167,255,0.22)",
        "hungry": "rgba(255,209,102,0.22)",
        "dirty": "rgba(181,192,154,0.18)",
        "sad": "rgba(143,195,255,0.17)",
    }.get(mood, "rgba(82,230,255,0.20)")

    if mood == "sleepy":
        eyes = f'''
            <path class="robot-eye" d="M111 124 Q120 118 129 124" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
            <path class="robot-eye" d="M151 124 Q160 118 169 124" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>
        '''
        mouth = f'<path d="M124 145 Q140 149 156 145" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>'
        extra = '<text x="190" y="88" class="zzz">Zz</text><text x="212" y="66" class="zzz small">z</text>'
    elif mood == "sad":
        eyes = f'''
            <circle class="robot-eye" cx="120" cy="124" r="8" fill="{accent}"/>
            <circle class="robot-eye" cx="160" cy="124" r="8" fill="{accent}"/>
        '''
        mouth = f'<path d="M124 149 Q140 137 156 149" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>'
        extra = f'<path class="tear" d="M170 132 C180 145 170 152 164 144 C162 139 166 135 170 132Z" fill="{accent}" opacity="0.72"/>'
    elif mood == "hungry":
        eyes = f'''
            <circle class="robot-eye" cx="120" cy="124" r="8" fill="{accent}"/>
            <circle class="robot-eye" cx="160" cy="124" r="8" fill="{accent}"/>
        '''
        mouth = f'<circle cx="140" cy="146" r="7" fill="none" stroke="{accent}" stroke-width="5"/>'
        extra = '<text x="193" y="88" class="food">0101</text>'
    else:
        eyes = f'''
            <circle class="robot-eye" cx="120" cy="124" r="9" fill="{accent}"/>
            <circle class="robot-eye" cx="160" cy="124" r="9" fill="{accent}"/>
        '''
        mouth = f'<path d="M124 145 Q140 158 156 145" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>'
        extra = ''

    dirt = ''
    if mood == "dirty":
        dirt = '''
            <circle cx="97" cy="84" r="5" fill="#7c806d" opacity="0.55"/>
            <circle cx="190" cy="176" r="6" fill="#7c806d" opacity="0.45"/>
            <circle cx="87" cy="166" r="4" fill="#7c806d" opacity="0.50"/>
        '''

    safe_message = escape(message)
    safe_mood_label = escape(mood_label)

    return f"""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
    html, body {{
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: transparent;
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #eef6ff;
    }}

    .pet-card {{
        width: min(94vw, 720px);
        margin: 0 auto;
        padding: 22px 18px 18px;
        border-radius: 32px;
        background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.035));
        border: 1px solid rgba(255,255,255,0.13);
        box-shadow: 0 28px 80px rgba(0,0,0,0.32);
        backdrop-filter: blur(18px);
    }}

    .robot-stage {{
        min-height: 345px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        position: relative;
    }}

    .robot-wrap {{
        width: min(62vw, 285px);
        max-width: 285px;
        aspect-ratio: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        animation: robot-float 3s ease-in-out infinite;
    }}

    .robot-wrap.happy {{ animation: robot-happy 1.45s ease-in-out infinite; }}
    .robot-wrap.sleepy {{ animation: robot-sleepy 4s ease-in-out infinite; }}
    .robot-wrap.hungry {{ animation: robot-shake 0.9s ease-in-out infinite; }}
    .robot-wrap.sad {{ animation: robot-sad 3.2s ease-in-out infinite; }}

    .robot-glow {{
        position: absolute;
        width: 84%;
        height: 84%;
        border-radius: 999px;
        background: {glow};
        filter: blur(34px);
        animation: glow-pulse 2.4s ease-in-out infinite;
    }}

    .robot-svg {{
        position: relative;
        width: 100%;
        height: 100%;
        filter: drop-shadow(0 24px 42px rgba(0, 0, 0, 0.45));
    }}

    .robot-eye {{
        animation: eye-blink 4s ease-in-out infinite;
        transform-origin: center;
    }}

    .robot-antenna-light {{
        animation: light-pulse 1.4s ease-in-out infinite;
    }}

    .robot-arm-left {{
        transform-origin: 58px 145px;
        animation: arm-wave-left 2.4s ease-in-out infinite;
    }}

    .robot-arm-right {{
        transform-origin: 222px 145px;
        animation: arm-wave-right 2.4s ease-in-out infinite;
    }}

    .speech {{
        margin: -10px auto 0;
        width: min(92%, 540px);
        padding: 14px 16px;
        border-radius: 20px;
        background: rgba(5, 12, 24, 0.62);
        border: 1px solid rgba(255,255,255,0.12);
        text-align: center;
        line-height: 1.45;
    }}

    .title {{
        display: flex;
        justify-content: center;
        gap: 10px;
        align-items: center;
        font-weight: 800;
        letter-spacing: 0.3px;
        font-size: 18px;
        margin-bottom: 10px;
    }}

    .pill {{
        font-size: 12px;
        font-weight: 700;
        padding: 5px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.15);
        color: {accent};
    }}

    .zzz, .food {{
        fill: {accent};
        font-weight: 800;
        font-size: 22px;
        opacity: 0.85;
        animation: float-text 2.1s ease-in-out infinite;
    }}
    .zzz.small {{ font-size: 14px; animation-delay: 0.35s; }}
    .tear {{ animation: tear-drop 1.8s ease-in-out infinite; }}

    @keyframes robot-float {{
        0%, 100% {{ transform: translateY(0); }}
        50% {{ transform: translateY(-13px); }}
    }}

    @keyframes robot-happy {{
        0%, 100% {{ transform: translateY(0) rotate(-1deg); }}
        50% {{ transform: translateY(-18px) rotate(1deg); }}
    }}

    @keyframes robot-sleepy {{
        0%, 100% {{ transform: translateY(0) rotate(-2deg); opacity: 0.86; }}
        50% {{ transform: translateY(3px) rotate(2deg); opacity: 1; }}
    }}

    @keyframes robot-shake {{
        0%, 100% {{ transform: translateX(0); }}
        25% {{ transform: translateX(-3px); }}
        75% {{ transform: translateX(3px); }}
    }}

    @keyframes robot-sad {{
        0%, 100% {{ transform: translateY(8px); }}
        50% {{ transform: translateY(1px); }}
    }}

    @keyframes glow-pulse {{
        0%, 100% {{ opacity: 0.58; transform: scale(0.96); }}
        50% {{ opacity: 1; transform: scale(1.08); }}
    }}

    @keyframes eye-blink {{
        0%, 44%, 52%, 100% {{ transform: scaleY(1); opacity: 1; }}
        48% {{ transform: scaleY(0.12); opacity: 0.85; }}
    }}

    @keyframes light-pulse {{
        0%, 100% {{ opacity: 0.45; }}
        50% {{ opacity: 1; }}
    }}

    @keyframes arm-wave-left {{
        0%, 100% {{ transform: rotate(0deg); }}
        50% {{ transform: rotate(-9deg); }}
    }}

    @keyframes arm-wave-right {{
        0%, 100% {{ transform: rotate(0deg); }}
        50% {{ transform: rotate(9deg); }}
    }}

    @keyframes float-text {{
        0%, 100% {{ transform: translateY(0); opacity: .58; }}
        50% {{ transform: translateY(-7px); opacity: 1; }}
    }}

    @keyframes tear-drop {{
        0%, 100% {{ transform: translateY(0); opacity: .45; }}
        50% {{ transform: translateY(8px); opacity: 1; }}
    }}
</style>
</head>
<body>
    <div class="pet-card">
        <div class="title">
            <span>🤖 YAMLKU BOT PET</span>
            <span class="pill">{safe_mood_label}</span>
            <span class="pill">LV {level}</span>
            <span class="pill">XP {xp}/100</span>
        </div>
        <div class="robot-stage" aria-label="Tamagotchi robot">
            <div class="robot-wrap {mood}">
                <div class="robot-glow"></div>
                <svg class="robot-svg" viewBox="0 0 280 280" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Robot pet animation">
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
                    <circle class="robot-antenna-light" cx="140" cy="28" r="11" fill="{accent}"/>

                    <g class="robot-arm-left">
                        <rect x="35" y="128" width="42" height="24" rx="12" fill="#8ca6c9"/>
                        <circle cx="34" cy="140" r="12" fill="#c8d8ec"/>
                    </g>

                    <g class="robot-arm-right">
                        <rect x="203" y="128" width="42" height="24" rx="12" fill="#8ca6c9"/>
                        <circle cx="246" cy="140" r="12" fill="#c8d8ec"/>
                    </g>

                    <rect x="72" y="68" width="136" height="130" rx="38" fill="url(#bodyGrad)"/>
                    {dirt}
                    <rect x="91" y="95" width="98" height="58" rx="24" fill="url(#screenGrad)"/>

                    {eyes}
                    {mouth}
                    {extra}

                    <rect x="105" y="170" width="70" height="16" rx="8" fill="#dce8f7"/>
                    <circle cx="119" cy="178" r="4" fill="#6d87aa"/>
                    <circle cx="140" cy="178" r="4" fill="#6d87aa"/>
                    <circle cx="161" cy="178" r="4" fill="#6d87aa"/>
                </svg>
            </div>
        </div>
        <div class="speech">{safe_message}</div>
    </div>
</body>
</html>
"""


def render_metric(label: str, value: int, icon: str):
    st.markdown(
        f"""
        <div class="pet-metric">
            <div class="pet-metric-head"><span>{icon} {label}</span><strong>{value}%</strong></div>
            <div class="pet-bar"><div class="pet-fill" style="width: {value}%;"></div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <style>
        .block-container {
            max-width: 760px !important;
            padding: 28px 14px 44px !important;
            margin: 0 auto !important;
        }

        .stButton > button {
            width: 100%;
            min-height: 46px;
            border-radius: 16px;
            border: 1px solid rgba(255,255,255,0.16);
            background: rgba(255,255,255,0.08);
            color: #eef6ff;
            font-weight: 700;
            box-shadow: 0 12px 30px rgba(0,0,0,0.18);
        }

        .stButton > button:hover {
            border-color: rgba(100, 230, 255, 0.55);
            background: rgba(82,230,255,0.12);
            color: #ffffff;
        }

        .pet-panel {
            margin-top: 14px;
            padding: 16px;
            border-radius: 24px;
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.12);
            backdrop-filter: blur(18px);
        }

        .pet-metric {
            margin: 9px 0;
        }

        .pet-metric-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: #eaf4ff;
            font-size: 14px;
            margin-bottom: 7px;
        }

        .pet-bar {
            height: 12px;
            border-radius: 999px;
            background: rgba(255,255,255,0.10);
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.08);
        }

        .pet-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #52e6ff, #63f7b4);
            box-shadow: 0 0 18px rgba(82,230,255,0.35);
        }

        .pet-small-note {
            color: rgba(238,246,255,0.72);
            text-align: center;
            font-size: 13px;
            margin-top: 10px;
        }

        .pet-section-title {
            color: #eef6ff;
            font-weight: 800;
            margin: 10px 0 2px;
            text-align: center;
        }

        .best-ping-card {
            margin-top: 12px;
            padding: 16px;
            border-radius: 24px;
            background: linear-gradient(180deg, rgba(99,247,180,0.12), rgba(82,230,255,0.055));
            border: 1px solid rgba(99,247,180,0.18);
            box-shadow: 0 18px 42px rgba(0,0,0,0.20);
            color: #eef6ff;
        }

        .best-ping-top {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 10px;
        }

        .best-ping-title {
            font-size: 15px;
            font-weight: 900;
            letter-spacing: 0.2px;
        }

        .best-ping-delay {
            white-space: nowrap;
            font-size: 20px;
            font-weight: 900;
            color: #63f7b4;
        }

        .best-ping-meta {
            color: rgba(238,246,255,0.74);
            font-size: 13px;
            line-height: 1.5;
        }

        .best-ping-list {
            margin-top: 10px;
            display: grid;
            gap: 8px;
        }

        .best-ping-row {
            display: grid;
            grid-template-columns: 34px 1fr auto;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
            border-radius: 16px;
            background: rgba(255,255,255,0.055);
            border: 1px solid rgba(255,255,255,0.08);
        }

        .best-ping-rank {
            font-weight: 900;
            color: #63f7b4;
        }

        .best-ping-name {
            font-weight: 800;
            font-size: 13px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .best-ping-sub {
            color: rgba(238,246,255,0.66);
            font-size: 12px;
            margin-top: 2px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


init_pet_state()
decay_pet_state()
pet = st.session_state.pet
mood, mood_label = pet_mood()

components.html(
    render_robot_html(
        mood=mood,
        mood_label=mood_label,
        message=pet.get("last_action_text", "Halo!"),
        level=int(pet.get("level", 1)),
        xp=int(pet.get("xp", 0)),
    ),
    height=520,
    scrolling=False,
)

st.markdown('<div class="pet-panel">', unsafe_allow_html=True)
left, right = st.columns(2)
with left:
    render_metric("Kenyang", int(pet["hunger"]), "🍜")
    render_metric("Bahagia", int(pet["happiness"]), "🎮")
with right:
    render_metric("Energi", int(pet["energy"]), "🔋")
    render_metric("Bersih", int(pet["hygiene"]), "🧼")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="pet-section-title">Rawat robot</div>', unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🍜 Makan", use_container_width=True):
        action_feed()
        st.rerun()
with col2:
    if st.button("🎮 Main", use_container_width=True):
        action_play()
        st.rerun()
with col3:
    if st.button("😴 Tidur", use_container_width=True):
        action_sleep()
        st.rerun()

col4, col5, col6 = st.columns(3)
with col4:
    if st.button("🧼 Bersihkan", use_container_width=True):
        action_clean()
        st.rerun()
with col5:
    if st.button("🔋 Charge", use_container_width=True):
        action_charge()
        st.rerun()
with col6:
    if st.button("🔁 Reset", use_container_width=True):
        action_reset()
        st.rerun()

st.markdown('<div class="pet-section-title">Aksi bot</div>', unsafe_allow_html=True)
bot_col1, bot_col2 = st.columns(2)
with bot_col1:
    if st.button("🔄 Update Config", use_container_width=True):
        try:
            dispatch_workflow(mode="update", enable_proxy_test="true", filter_alive_only="true")
            set_pet_action("Update config berhasil dipicu. Aku menunggu hasil GitHub Actions.")
            st.success("Update GitHub Actions berhasil dipicu.")
            add_xp(18)
        except Exception as exc:
            set_pet_action("Aku gagal memicu update. Cek token/repo/workflow ya.")
            st.error(str(exc))
        st.rerun()
with bot_col2:
    if st.button("🧪 Test Proxy", use_container_width=True):
        try:
            dispatch_workflow(mode="test", enable_proxy_test="true", filter_alive_only="false")
            set_pet_action("Test proxy berhasil dipicu. Aku akan tunggu laporan alive/dead.")
            st.success("Test proxy GitHub Actions berhasil dipicu.")
            add_xp(18)
        except Exception as exc:
            set_pet_action("Aku gagal memicu test proxy. Cek workflow input dan secrets.")
            st.error(str(exc))
        st.rerun()

st.markdown('<div class="pet-section-title">Best Ping From Indonesia</div>', unsafe_allow_html=True)

best_col1, best_col2 = st.columns(2)
with best_col1:
    if st.button("📡 Refresh Best Ping", use_container_width=True):
        try:
            load_best_ping_data.clear()
        except Exception:
            pass
        st.rerun()
with best_col2:
    if st.button("🏆 Test + Update Ping", use_container_width=True):
        try:
            dispatch_workflow(mode="test", enable_proxy_test="true", filter_alive_only="false")
            set_pet_action("Best ping sedang dites ulang lewat GitHub Actions.")
            st.success("Test ping berhasil dipicu. Tunggu output Alive/Dead diperbarui.")
            add_xp(12)
        except Exception as exc:
            set_pet_action("Aku gagal memicu test best ping. Cek workflow dan secrets.")
            st.error(str(exc))
        st.rerun()


def render_best_ping_component_html(best_data: dict, best_rows: list, summary: dict) -> str:
    """Render panel Best Ping lewat components.html agar HTML tidak tampil sebagai teks."""
    source_label = escape(str(best_data.get("source_label", "Indonesia")))
    source_path = escape(str(best_data.get("source_path", "-")))
    country_filter = escape(str(best_data.get("country_filter") or "Semua negara"))
    yaml_proxy_count = int(best_data.get("yaml_proxy_count", 0) or 0)
    alive_count = escape(str(summary.get("alive", best_data.get("all_alive_count", 0))))
    dead_count = escape(str(summary.get("dead", "-")))
    untested_count = escape(str(summary.get("untested", "-")))

    if not best_rows:
        return f"""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
    html, body {{ margin:0; padding:0; background:transparent; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:#eef6ff; }}
    .empty-card {{ box-sizing:border-box; width:100%; padding:18px; border-radius:24px; background:linear-gradient(180deg, rgba(99,247,180,0.12), rgba(82,230,255,0.055)); border:1px solid rgba(99,247,180,0.18); text-align:center; line-height:1.5; }}
    .title {{ font-weight:900; margin-bottom:6px; }}
    .sub {{ color:rgba(238,246,255,.76); font-size:13px; }}
</style>
</head>
<body>
    <div class="empty-card">
        <div class="title">📡 Best Ping From {source_label}</div>
        <div class="sub">Belum ada data proxy alive. Klik <b>Test + Update Ping</b> atau kirim <b>/test</b> di Telegram.</div>
    </div>
</body>
</html>
"""

    top = best_rows[0]
    top_name = escape(str(top.get("name", "-")))
    top_protocol = escape(str(top.get("protocol", "-")).upper())
    top_country = escape(str(top.get("country", "-")))
    top_delay = escape(str(top.get("delay_ms", "-")))

    rows_html = []
    for idx, row in enumerate(best_rows, start=1):
        name = escape(str(row.get("name", "-")))
        protocol = escape(str(row.get("protocol", "-")).upper())
        country = escape(str(row.get("country", "-")))
        server = escape(str(row.get("server", "-")))
        port = escape(str(row.get("port", "-")))
        delay = escape(str(row.get("delay_ms", "-")))
        rows_html.append(
            f"""
            <div class="best-ping-row">
                <div class="best-ping-rank">#{idx}</div>
                <div class="best-ping-info">
                    <div class="best-ping-name" title="{name}">{name}</div>
                    <div class="best-ping-sub">{protocol} · {country} · {server}:{port}</div>
                </div>
                <div class="best-ping-delay">{delay} ms</div>
            </div>
            """
        )

    return f"""
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
    html, body {{
        margin: 0;
        padding: 0;
        background: transparent;
        color: #eef6ff;
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    .best-ping-card {{
        width: 100%;
        padding: 16px;
        border-radius: 24px;
        background: linear-gradient(180deg, rgba(99,247,180,0.12), rgba(82,230,255,0.055));
        border: 1px solid rgba(99,247,180,0.18);
        box-shadow: 0 18px 42px rgba(0,0,0,0.20);
        color: #eef6ff;
        overflow: hidden;
    }}
    .best-ping-top {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 10px;
    }}
    .best-ping-title {{
        font-size: 15px;
        font-weight: 900;
        letter-spacing: 0.2px;
    }}
    .best-ping-main-delay {{
        white-space: nowrap;
        font-size: 20px;
        font-weight: 900;
        color: #63f7b4;
    }}
    .best-ping-meta {{
        color: rgba(238,246,255,0.74);
        font-size: 13px;
        line-height: 1.5;
    }}
    .best-ping-meta code {{
        color: #dffaff;
        background: rgba(255,255,255,0.08);
        padding: 1px 5px;
        border-radius: 6px;
    }}
    .best-ping-list {{
        margin-top: 10px;
        display: grid;
        gap: 8px;
    }}
    .best-ping-row {{
        display: grid;
        grid-template-columns: 38px minmax(0, 1fr) auto;
        gap: 10px;
        align-items: center;
        padding: 10px 12px;
        border-radius: 16px;
        background: rgba(255,255,255,0.055);
        border: 1px solid rgba(255,255,255,0.08);
    }}
    .best-ping-rank {{
        font-weight: 900;
        color: #63f7b4;
    }}
    .best-ping-info {{ min-width: 0; }}
    .best-ping-name {{
        font-weight: 800;
        font-size: 13px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
    .best-ping-sub {{
        color: rgba(238,246,255,0.66);
        font-size: 12px;
        margin-top: 2px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
    .best-ping-delay {{
        white-space: nowrap;
        font-size: 14px;
        font-weight: 900;
        color: #63f7b4;
    }}
</style>
</head>
<body>
    <div class="best-ping-card">
        <div class="best-ping-top">
            <div>
                <div class="best-ping-title">🏆 Tercepat dari {source_label}</div>
                <div class="best-ping-meta">{top_name} · {top_protocol} · {top_country}</div>
            </div>
            <div class="best-ping-main-delay">{top_delay} ms</div>
        </div>
        <div class="best-ping-meta">
            Sumber data: <code>{source_path}</code><br>
            Proxy di <code>output/lengkap.yaml</code>: <b>{yaml_proxy_count}</b><br>
            Alive: <b>{alive_count}</b> · Dead: <b>{dead_count}</b> · Untested: <b>{untested_count}</b><br>
            Filter negara: <b>{country_filter}</b>
        </div>
        <div class="best-ping-list">
            {''.join(rows_html)}
        </div>
    </div>
</body>
</html>
"""


try:
    best_data = load_best_ping_data(limit=BEST_PING_LIMIT)
    best_rows = best_data.get("rows", [])
    summary = best_data.get("summary", {}) or {}

    # Jangan pakai st.markdown untuk HTML kompleks ini. components.html mencegah HTML muncul sebagai teks.
    component_height = 240 + max(1, len(best_rows)) * 68
    components.html(
        render_best_ping_component_html(best_data, best_rows, summary),
        height=min(component_height, 860),
        scrolling=True,
    )
except Exception as exc:
    st.info(
        "Best ping belum bisa ditampilkan. Pastikan output/Alive/check_result.csv atau output/Alive/alive.csv sudah ada di GitHub."
    )
    with st.expander("Detail error best ping"):
        st.code(str(exc))

st.markdown(
    '<div class="pet-small-note">Telegram tetap aktif di background: /check, /update, /test, /best, /status, /id, /help.</div>',
    unsafe_allow_html=True,
)

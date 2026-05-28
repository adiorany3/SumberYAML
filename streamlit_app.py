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
    page_title="Raptor X Bot",
    page_icon="🦖",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Tampilan robot dinosaurus interaktif. Bot Telegram tetap berjalan di background.
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
BEST_PING_LIMIT = get_int_setting("BEST_PING_LIMIT", 5)
# Opsional: isi ID jika hanya ingin menampilkan server negara Indonesia.
# Kosongkan agar menampilkan proxy alive tercepat dari semua negara.
BEST_PING_COUNTRY_FILTER = get_setting("BEST_PING_COUNTRY_FILTER", "ID").upper()

# Status GitHub Actions di Streamlit online.
SHOW_WORKFLOW_STATUS_PANEL = get_setting("SHOW_WORKFLOW_STATUS_PANEL", "true").strip().lower() in ["1", "true", "yes", "y", "on"]
WORKFLOW_STATUS_REFRESH_SECONDS = get_int_setting("WORKFLOW_STATUS_REFRESH_SECONDS", 60)


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


BOT_COMMANDS = [
    {"command": "update", "description": "Update config + test ping + rebuild lengkap.yaml"},
    {"command": "update_ping", "description": "Update ping + rebuild URL-TEST TOP 5 INDONESIA"},
    {"command": "test", "description": "Cek proxy hidup/mati"},
    {"command": "test_ping", "description": "Test ping dan update laporan Alive/Dead"},
    {"command": "best", "description": "Tampilkan 5 ping tercepat"},
    {"command": "status", "description": "Cek workflow GitHub terakhir"},
    {"command": "check", "description": "Cek konfigurasi token/repo/workflow"},
    {"command": "id", "description": "Tampilkan chat ID"},
    {"command": "help", "description": "Tampilkan bantuan"},
]


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


def telegram_request(method: str, data=None, json_data=None, timeout: int = 60):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di Streamlit Secrets.")

    kwargs = {"timeout": timeout}
    if json_data is not None:
        kwargs["json"] = json_data
    else:
        kwargs["data"] = data or {}

    response = requests.post(
        telegram_url(method),
        **kwargs,
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


def register_bot_commands():
    """Daftarkan command agar muncul di menu slash Telegram.

    Telegram kadang perlu chat ditutup/dibuka ulang setelah setMyCommands.
    Command tetap bisa diketik manual walaupun menu slash belum refresh.
    """
    if not TELEGRAM_BOT_TOKEN:
        return None

    return telegram_request(
        "setMyCommands",
        json_data={"commands": BOT_COMMANDS},
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


def dispatch_workflow(mode='update', enable_proxy_test='true', filter_alive_only='true', strict_alive_only='true'):
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
            "strict_alive_only": strict_alive_only,
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
    """Ambil data Best Ping untuk panel Streamlit dan command Telegram /best.

    Prioritas baru:
    1. output/BestPing/top5_indonesia_ping.csv
    2. output/BestPing/top5_best_ping.csv
    3. output/Alive/alive.csv
    4. output/Alive/check_result.csv

    Catatan penting:
    - File di output/BestPing sudah hasil filter Top 5 dari generator, jadi jangan difilter ulang.
      Kalau difilter ulang, data fallback global bisa kosong di panel.
    - File di output/Alive masih perlu difilter status=alive dan country=ID.
    """
    limit = int(limit or BEST_PING_LIMIT or 5)

    candidates = [
        {
            "csv": "output/BestPing/top5_indonesia_ping.csv",
            "summary": "output/BestPing/summary_top5_indonesia_ping.json",
            "prefiltered": True,
        },
        {
            "csv": "output/BestPing/top5_best_ping.csv",
            "summary": "output/BestPing/summary_top5_best_ping.json",
            "prefiltered": True,
        },
        {
            "csv": "output/Alive/alive.csv",
            "summary": "output/Alive/summary_alive.json",
            "prefiltered": False,
        },
        {
            "csv": "output/Alive/check_result.csv",
            "summary": "output/Alive/summary_alive.json",
            "prefiltered": False,
        },
    ]

    last_error = None
    rows = []
    source_path = "-"
    summary_path = ""
    used_prefiltered = False

    for item in candidates:
        path = item["csv"]
        try:
            csv_text = fetch_github_file_text(path)
            parsed_rows = parse_check_csv(csv_text)

            if item["prefiltered"]:
                usable_rows = [
                    row for row in parsed_rows
                    if row.get("delay_ms") is not None and row.get("name")
                ]
            else:
                usable_rows = [
                    row for row in parsed_rows
                    if row.get("status") == "alive" and row.get("delay_ms") is not None
                ]
                if BEST_PING_COUNTRY_FILTER:
                    usable_rows = [
                        row for row in usable_rows
                        if row.get("country", "").upper() == BEST_PING_COUNTRY_FILTER
                    ]

            if usable_rows:
                rows = usable_rows
                source_path = path
                summary_path = item.get("summary", "")
                used_prefiltered = bool(item["prefiltered"])
                break

            # File ada tetapi kosong. Simpan sumbernya untuk pesan diagnostik.
            if source_path == "-":
                source_path = path
                summary_path = item.get("summary", "")
                used_prefiltered = bool(item["prefiltered"])
        except Exception as exc:
            last_error = exc

    if not rows and last_error and source_path == "-":
        raise RuntimeError(str(last_error))

    rows.sort(key=lambda item: item.get("delay_ms") or 999999)

    summary = {}
    if summary_path:
        try:
            summary_text = fetch_github_file_text(summary_path)
            summary = json.loads(summary_text)
        except Exception:
            summary = {}

    # Jika summary BestPing tidak punya alive/dead, ambil ringkasan Alive sebagai pelengkap.
    if not summary.get("alive"):
        try:
            alive_summary_text = fetch_github_file_text("output/Alive/summary_alive.json")
            alive_summary = json.loads(alive_summary_text)
            for key in ["alive", "dead", "untested", "tested", "total"]:
                if key not in summary and key in alive_summary:
                    summary[key] = alive_summary[key]
        except Exception:
            pass

    return {
        "rows": rows[:limit],
        "all_alive_count": len(rows),
        "source_path": source_path,
        "summary": summary,
        "yaml_proxy_count": count_proxy_names_from_lengkap_yaml(),
        "source_label": BEST_PING_SOURCE_LABEL or "Indonesia",
        "country_filter": BEST_PING_COUNTRY_FILTER,
        "used_prefiltered_bestping": used_prefiltered,
    }



def parse_iso_datetime_text(value: str) -> str:
    """Ubah timestamp GitHub menjadi format yang mudah dibaca."""
    value = str(value or "").strip()
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return value


def read_json_from_github(path: str) -> dict:
    try:
        raw = fetch_github_file_text(path)
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_csv_rows_from_github(path: str) -> list:
    try:
        raw = fetch_github_file_text(path)
        return list(csv.DictReader(io.StringIO(raw or "")))
    except Exception:
        return []


def source_status_summary_for_streamlit() -> dict:
    rows = read_csv_rows_from_github("output/Source/source_status.csv")
    return {
        "source_total": len(rows),
        "source_ok": sum(1 for row in rows if str(row.get("status", "")).lower() == "ok"),
        "source_cached": sum(1 for row in rows if str(row.get("status", "")).lower() == "cached" or str(row.get("cache_used", "")).lower() == "true"),
        "source_failed": sum(1 for row in rows if str(row.get("status", "")).lower() == "failed"),
    }


def validation_status_summary_for_streamlit() -> dict:
    report = read_json_from_github("output/Validation/validation_report.json")
    files = report.get("files", []) if isinstance(report, dict) else []
    ok_count = sum(1 for item in files if isinstance(item, dict) and item.get("ok"))
    return {
        "ok": bool(report.get("ok", False)) if isinstance(report, dict) else False,
        "file_count": len(files),
        "ok_count": ok_count,
    }


@st.cache_data(ttl=25, show_spinner=False)
def load_workflow_status_data() -> dict:
    """Ambil status GitHub Actions terbaru dan ringkasan output yang sudah di-commit."""
    run = latest_workflow_run()
    if not run:
        return {"has_run": False}

    status = str(run.get("status") or "-")
    conclusion = str(run.get("conclusion") or "-")
    is_finished = status == "completed"

    summary_alive = {}
    summary_strict = {}
    summary_lite = {}
    summary_fast = {}
    summary_best = {}
    summary_profiles = {}
    validation = {}
    sources = {}
    reuse = {}
    best_rows = []

    # Ringkasan output hanya dibaca ketika run sukses agar tidak menampilkan data lama sebagai hasil gagal.
    if is_finished and conclusion == "success":
        summary_alive = read_json_from_github("output/Alive/summary_alive.json")
        summary_strict = read_json_from_github("output/Strict/summary_strict_alive.json")
        summary_lite = read_json_from_github("output/Lite/summary_lite.json")
        summary_fast = read_json_from_github("output/Fast/summary_fast.json")
        summary_best = read_json_from_github("output/BestPing/summary_top5_indonesia_ping.json")
        summary_profiles = read_json_from_github("output/Categories/summary_usage_profiles.json")
        validation = validation_status_summary_for_streamlit()
        sources = source_status_summary_for_streamlit()
        reuse = read_json_from_github("output/Reuse/reuse_previous_output.json")
        try:
            best_data = load_best_ping_data(limit=BEST_PING_LIMIT)
            best_rows = best_data.get("rows", [])
        except Exception:
            best_rows = []

    return {
        "has_run": True,
        "run": run,
        "status": status,
        "conclusion": conclusion,
        "is_finished": is_finished,
        "summary_alive": summary_alive,
        "summary_strict": summary_strict,
        "summary_lite": summary_lite,
        "summary_fast": summary_fast,
        "summary_best": summary_best,
        "summary_profiles": summary_profiles,
        "validation": validation,
        "sources": sources,
        "reuse": reuse,
        "best_rows": best_rows,
    }


def workflow_status_badge(status: str, conclusion: str) -> tuple:
    if status in ["queued", "in_progress", "waiting", "pending"]:
        return "GitHub Actions sedang berjalan", "⏳", "running"
    if status == "completed" and conclusion == "success":
        return "GitHub Actions selesai - sukses", "✅", "success"
    if status == "completed":
        return f"GitHub Actions selesai - {conclusion}", "❌", "failed"
    return f"GitHub Actions: {status}", "ℹ️", "unknown"


def workflow_auto_refresh(seconds: int = 60):
    seconds = max(15, int(seconds or 60))
    components.html(
        f"""
        <script>
            setTimeout(function() {{
                try {{ window.parent.location.reload(); }} catch (e) {{}}
            }}, {seconds * 1000});
        </script>
        """,
        height=0,
    )


def render_workflow_status_panel():
    """Tampilkan info GitHub Actions hanya di halaman admin setelah login."""
    if not SHOW_WORKFLOW_STATUS_PANEL:
        return
    if not is_admin_route() or st.session_state.get("admin_authenticated") is not True:
        return
    if not GITHUB_OWNER or not GITHUB_REPO:
        return

    st.markdown('<div class="pet-section-title">Status GitHub Actions</div>', unsafe_allow_html=True)

    try:
        data = load_workflow_status_data()
    except Exception as exc:
        st.info("Status GitHub Actions belum bisa dibaca. Pastikan GITHUB_TOKEN/GITHUB_REPOSITORY sudah benar di Streamlit Secrets.")
        if is_admin_route():
            with st.expander("Detail error status GitHub Actions"):
                st.code(str(exc))
        return

    if not data.get("has_run"):
        st.info("Belum ada riwayat GitHub Actions.")
        return

    run = data.get("run", {}) or {}
    status = data.get("status", "-")
    conclusion = data.get("conclusion", "-")
    title, icon, state_class = workflow_status_badge(status, conclusion)
    html_url = run.get("html_url", "")
    run_number = run.get("run_number", "-")
    created_at = parse_iso_datetime_text(run.get("created_at"))
    updated_at = parse_iso_datetime_text(run.get("updated_at"))
    display_title = escape(str(run.get("display_title") or run.get("name") or WORKFLOW_ID))

    if status in ["queued", "in_progress", "waiting", "pending"]:
        set_pet_action("GitHub Actions masih berjalan. Status akan dicek otomatis.")
        workflow_auto_refresh(WORKFLOW_STATUS_REFRESH_SECONDS)
        st.markdown(
            f"""
            <div class="pet-panel">
                <div style="font-weight:900;color:#eef6ff;font-size:16px;">{icon} {escape(title)}</div>
                <div class="pet-small-note" style="text-align:left;margin-top:8px;">
                    Run <b>#{run_number}</b> · {display_title}<br>
                    Dibuat: <b>{escape(created_at)}</b><br>
                    Update terakhir: <b>{escape(updated_at)}</b><br>
                    Auto refresh setiap <b>{int(WORKFLOW_STATUS_REFRESH_SECONDS)}</b> detik selama workflow berjalan.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if html_url:
            st.markdown(f"[Buka workflow di GitHub]({html_url})")
        return

    summary_alive = data.get("summary_alive", {}) or {}
    summary_strict = data.get("summary_strict", {}) or {}
    summary_lite = data.get("summary_lite", {}) or {}
    summary_fast = data.get("summary_fast", {}) or {}
    summary_best = data.get("summary_best", {}) or {}
    summary_profiles = data.get("summary_profiles", {}) or {}
    validation = data.get("validation", {}) or {}
    sources = data.get("sources", {}) or {}
    reuse = data.get("reuse", {}) or {}
    best_rows = data.get("best_rows", []) or []

    total_valid = summary_alive.get("total", summary_alive.get("valid", "-"))
    alive = summary_alive.get("alive", "-")
    dead = summary_alive.get("dead", "-")
    untested = summary_alive.get("untested", "-")
    strict_count = summary_strict.get("proxy_count", summary_alive.get("strict_alive", "-"))
    strict_rounds = f"{summary_strict.get('require_success_rounds', '-')}/{summary_strict.get('test_rounds', '-')}"
    lite_count = summary_lite.get("proxy_count", "-")
    fast_count = summary_fast.get("proxy_count", "-")
    responsive_count = summary_fast.get("responsive_count", summary_alive.get("responsive_count", "-"))
    profiles = summary_profiles.get("profiles", {}) if isinstance(summary_profiles, dict) else {}
    profile_count = len([1 for item in profiles.values() if isinstance(item, dict) and item.get("proxy_count", 0)])
    best_count = summary_best.get("best_ping_count", len(best_rows))
    validation_text = "OK" if validation.get("ok") else "CHECK"
    reuse_note = ""
    if reuse.get("reuse_previous_output"):
        reuse_note = (
            f"<br>♻️ Reuse output sebelumnya: <b>AKTIF</b> · "
            f"Alasan: <b>{escape(str(reuse.get('reason', '-'))[:220])}</b>"
        )

    if conclusion == "success":
        set_pet_action("GitHub Actions selesai. Strict alive dan best ping sudah diperbarui.")
        status_color = "#63f7b4"
    else:
        set_pet_action("GitHub Actions selesai tetapi ada error. Buka detail workflow untuk cek log.")
        status_color = "#ff8a8a"

    top_line = "-"
    if best_rows:
        first = best_rows[0]
        top_line = f"#{1} {first.get('name', '-')} · {first.get('delay_ms', '-')} ms · {str(first.get('protocol', '-')).upper()} · {first.get('country', '-')}"

    st.markdown(
        f"""
        <div class="pet-panel">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
                <div>
                    <div style="font-weight:900;color:{status_color};font-size:17px;">{icon} {escape(title)}</div>
                    <div class="pet-small-note" style="text-align:left;margin-top:6px;">Run <b>#{run_number}</b> · {display_title}</div>
                </div>
                <div style="white-space:nowrap;font-weight:900;color:#eef6ff;">{escape(updated_at)}</div>
            </div>
            <div style="height:10px;"></div>
            <div class="pet-small-note" style="text-align:left;line-height:1.7;">
                Total valid: <b>{escape(str(total_valid))}</b> · Alive: <b>{escape(str(alive))}</b> · Dead: <b>{escape(str(dead))}</b> · Untested: <b>{escape(str(untested))}</b><br>
                Strict alive: <b>{escape(str(strict_count))}</b> node · Ronde: <b>{escape(strict_rounds)}</b> · Lite: <b>{escape(str(lite_count))}</b> node · Fast: <b>{escape(str(fast_count))}</b> node<br>
                Responsive: <b>{escape(str(responsive_count))}</b> node · Profil stabil: <b>{escape(str(profile_count))}</b> group · Best Ping Indonesia: <b>{escape(str(best_count))}</b> node · Tercepat: <b>{escape(top_line)}</b><br>
                Source OK: <b>{sources.get('source_ok', '-')}</b> · Cache: <b>{sources.get('source_cached', '-')}</b> · Failed: <b>{sources.get('source_failed', '-')}</b><br>
                YAML validation: <b>{escape(validation_text)}</b> ({validation.get('ok_count', '-')}/{validation.get('file_count', '-')}){reuse_note}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if html_url:
        st.markdown(f"[Buka workflow di GitHub]({html_url})")


def best_ping_text_for_telegram(limit: int = 5) -> str:
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
        "Group URL-Test: <code>URL-TEST TOP 5 INDONESIA</code>",
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


def handle_update_ping(chat_id):
    """Command khusus untuk update hasil ping dan rebuild balance top 10 di lengkap.yaml."""
    result = dispatch_workflow(
        mode="update_ping",
        enable_proxy_test="true",
        filter_alive_only="true",
    )

    send_message(
        chat_id,
        "🏆 <b>Update ping berhasil dipicu dari Telegram</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow: <code>{WORKFLOW_ID}</code>\n"
        f"Branch/ref: <code>{GITHUB_REF}</code>\n\n"
        "GitHub Actions akan menjalankan test ping, memperbarui laporan Alive/Dead, "
        "dan memasukkan 5 ping tercepat ke grup URL-Test <code>URL-TEST TOP 5 INDONESIA</code> di <code>output/lengkap.yaml</code>.\n\n"
        "Tunggu notifikasi final dari GitHub Actions.",
    )

    return result


def handle_test_ping(chat_id):
    """Alias eksplisit untuk test ping tanpa memfilter output utama."""
    result = dispatch_workflow(
        mode="test_ping",
        enable_proxy_test="true",
        filter_alive_only="false",
    )

    send_message(
        chat_id,
        "🧪 <b>Test ping berhasil dipicu dari Telegram</b>\n"
        f"Repo: <code>{GITHUB_OWNER}/{GITHUB_REPO}</code>\n"
        f"Workflow: <code>{WORKFLOW_ID}</code>\n"
        f"Branch/ref: <code>{GITHUB_REF}</code>\n\n"
        "GitHub Actions akan membuat/memperbarui laporan ping:\n"
        "- <code>output/Alive/check_result.csv</code>\n"
        "- <code>output/Alive/alive.csv</code>\n"
        "- <code>output/Alive/dead.csv</code>\n"
        "- <code>output/BestPing/top5_best_ping.csv</code>\n\n"
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
    send_message(chat_id, best_ping_text_for_telegram(limit=BEST_PING_LIMIT))


def handle_help(chat_id):
    send_message(
        chat_id,
        "<b>Command tersedia:</b>\n"
        "/update - update config + test ping + rebuild lengkap.yaml\n"
        "/update_ping - update ping + rebuild URL-TEST TOP 5 INDONESIA\n"
        "/test - cek proxy hidup/mati via GitHub Actions\n"
        "/test_ping - test ping saja dan update laporan Alive/Dead\n"
        "/best - tampilkan 5 ping tercepat\n"
        "/commands - refresh menu command Telegram\n"
        "/status - cek workflow GitHub terakhir\n"
        "/check - cek konfigurasi token/repo/workflow\n"
        "/id - tampilkan chat ID\n"
        "/help - bantuan",
    )


def handle_commands(chat_id):
    register_bot_commands()
    send_message(
        chat_id,
        "✅ <b>Menu command Telegram sudah didaftarkan ulang.</b>\n\n"
        "Kalau <code>/update_ping</code> dan <code>/test_ping</code> belum terlihat di menu slash, "
        "tutup chat bot lalu buka lagi, atau ketik command secara manual.",
    )


def handle_command(chat_id, text: str):
    command = text.split()[0].split("@")[0].lower()
    BOT_STATE.set(last_command=command, last_update_at=now_iso())

    if command == "/update":
        return handle_update(chat_id)
    if command in ("/update_ping", "/updateping", "/ping_update", "/pingupdate"):
        return handle_update_ping(chat_id)
    if command == "/test":
        return handle_test(chat_id)
    if command in ("/test_ping", "/testping", "/ping"):
        return handle_test_ping(chat_id)
    if command in ("/commands", "/setcommands", "/menu"):
        return handle_commands(chat_id)
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
    try:
        register_bot_commands()
    except Exception as exc:
        BOT_STATE.set(last_error=f"Gagal register command Telegram: {exc}")
        print("Register commands error:", exc)

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
# INTERACTIVE ROBOT DINOSAUR UI
# =========================

PET_DEFAULTS = {
    "hunger": 82,
    "energy": 78,
    "happiness": 84,
    "hygiene": 76,
    "level": 1,
    "xp": 0,
    "last_tick": time.time(),
    "last_action_text": "Halo! Aku Raptor X. Aku bisa diajak interaksi sambil menjaga update config kamu.",
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
        pet["last_action_text"] = f"Raptor upgrade! Sekarang aku level {pet['level']}."


def set_pet_action(message: str):
    st.session_state.pet["last_action_text"] = message
    st.session_state.pet["last_tick"] = time.time()


def action_feed():
    pet = st.session_state.pet
    pet["hunger"] = clamp(pet["hunger"] + 30)
    pet["happiness"] = clamp(pet["happiness"] + 7)
    pet["energy"] = clamp(pet["energy"] - 3)
    pet["hygiene"] = clamp(pet["hygiene"] - 3)
    set_pet_action("Krrrk! Energi data masuk. Sensor proxy makin siaga.")
    add_xp(12)


def action_play():
    pet = st.session_state.pet
    pet["happiness"] = clamp(pet["happiness"] + 28)
    pet["energy"] = clamp(pet["energy"] - 14)
    pet["hunger"] = clamp(pet["hunger"] - 9)
    pet["hygiene"] = clamp(pet["hygiene"] - 6)
    set_pet_action("Mode latihan aktif! Aku berlari kecil sambil scan config.")
    add_xp(16)


def action_sleep():
    pet = st.session_state.pet
    pet["energy"] = clamp(pet["energy"] + 36)
    pet["hunger"] = clamp(pet["hunger"] - 5)
    pet["happiness"] = clamp(pet["happiness"] + 3)
    set_pet_action("Sleep mode aktif. Servo dingin, baterai dipulihkan.")
    add_xp(9)


def action_clean():
    pet = st.session_state.pet
    pet["hygiene"] = clamp(pet["hygiene"] + 38)
    pet["happiness"] = clamp(pet["happiness"] + 5)
    set_pet_action("Sensor optik bersih. Debu digital sudah dibuang.")
    add_xp(10)


def action_charge():
    pet = st.session_state.pet
    pet["energy"] = clamp(pet["energy"] + 26)
    pet["hunger"] = clamp(pet["hunger"] - 2)
    set_pet_action("Charging selesai. Modul Telegram dan radar ping siap standby.")
    add_xp(10)


def action_reset():
    st.session_state.pet = dict(PET_DEFAULTS)
    st.session_state.pet["last_tick"] = time.time()


def action_talk(user_text: str):
    """Respons interaktif sederhana untuk Raptor X di Streamlit.

    Ini tidak memakai API AI eksternal sehingga aman untuk Streamlit online.
    Respons dibuat rule-based berdasarkan kata kunci yang diketik user.
    """
    text = str(user_text or "").strip()
    if not text:
        set_pet_action("Aku mendengar suara kosong. Coba beri perintah: status, ping, update, atau roar.")
        return

    lowered = text.lower()
    pet = st.session_state.pet

    if any(key in lowered for key in ["status", "kondisi", "gimana", "apa kabar"]):
        set_pet_action(
            f"Status Raptor X: nutrisi {int(pet['hunger'])}%, baterai {int(pet['energy'])}%, bonding {int(pet['happiness'])}%, sensor {int(pet['hygiene'])}%."
        )
        pet["happiness"] = clamp(pet["happiness"] + 5)
        add_xp(8)
        return

    if any(key in lowered for key in ["ping", "best", "proxy", "server"]):
        set_pet_action("Radar ping aktif. Untuk data real, buka mode admin lalu klik Refresh Best Ping atau Test + Update Ping.")
        pet["energy"] = clamp(pet["energy"] - 4)
        pet["happiness"] = clamp(pet["happiness"] + 6)
        add_xp(10)
        return

    if any(key in lowered for key in ["update", "config", "yaml", "github"]):
        set_pet_action("Aku siap bantu update config. Masuk halaman admin untuk memicu GitHub Actions dengan aman.")
        pet["energy"] = clamp(pet["energy"] - 5)
        pet["happiness"] = clamp(pet["happiness"] + 5)
        add_xp(10)
        return

    if any(key in lowered for key in ["roar", "auman", "aum", "rawr"]):
        set_pet_action("RAAWRR! Mode dinosaurus aktif. LED mata menyala dan ekor bergerak cepat.")
        pet["happiness"] = clamp(pet["happiness"] + 12)
        pet["energy"] = clamp(pet["energy"] - 7)
        add_xp(12)
        return

    if any(key in lowered for key in ["lapar", "makan", "feed", "energi"]):
        action_feed()
        return

    if any(key in lowered for key in ["tidur", "sleep", "istirahat"]):
        action_sleep()
        return

    if any(key in lowered for key in ["bersih", "clean", "sensor"]):
        action_clean()
        return

    set_pet_action(f"Aku menangkap pesan: '{text}'. Coba beri perintah: status, ping, update, roar, makan, tidur, atau bersih.")
    pet["happiness"] = clamp(pet["happiness"] + 4)
    add_xp(6)


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
        "happy": "rgba(99,247,180,0.28)",
        "normal": "rgba(82,230,255,0.22)",
        "sleepy": "rgba(185,167,255,0.24)",
        "hungry": "rgba(255,209,102,0.24)",
        "dirty": "rgba(181,192,154,0.20)",
        "sad": "rgba(143,195,255,0.18)",
    }.get(mood, "rgba(82,230,255,0.22)")

    if mood == "sleepy":
        eye = f'<path class="dino-eye" d="M137 110 Q148 105 159 110" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>'
        mouth = f'<path d="M78 137 Q112 145 151 137" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" opacity="0.8"/>'
        extra = '<text x="340" y="78" class="float-text">Zz</text><text x="377" y="54" class="float-text small">z</text>'
    elif mood == "sad":
        eye = f'<circle class="dino-eye" cx="148" cy="110" r="8" fill="{accent}"/><path d="M133 98 Q148 91 163 98" stroke="#26364f" stroke-width="5" fill="none" stroke-linecap="round"/>'
        mouth = f'<path d="M83 141 Q112 127 148 140" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>'
        extra = f'<path class="tear" d="M166 118 C178 135 166 143 159 132 C156 126 162 122 166 118Z" fill="{accent}" opacity="0.76"/>'
    elif mood == "hungry":
        eye = f'<circle class="dino-eye" cx="148" cy="110" r="8" fill="{accent}"/>'
        mouth = f'<path class="jaw" d="M58 136 C88 158 133 159 165 140" fill="none" stroke="{accent}" stroke-width="6" stroke-linecap="round"/>'
        extra = '<text x="326" y="76" class="float-text food">0101</text>'
    else:
        eye = f'<circle class="dino-eye" cx="148" cy="110" r="9" fill="{accent}"/><circle cx="151" cy="107" r="3" fill="#ffffff" opacity="0.88"/>'
        mouth = f'<path class="jaw" d="M73 134 Q112 154 156 137" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>'
        extra = ''

    dirt = ''
    if mood == "dirty":
        dirt = (
            '<circle cx="238" cy="160" r="8" fill="#73785f" opacity="0.50"/>'
            '<circle cx="315" cy="136" r="6" fill="#73785f" opacity="0.45"/>'
            '<circle cx="405" cy="190" r="7" fill="#73785f" opacity="0.42"/>'
            '<circle cx="118" cy="95" r="5" fill="#73785f" opacity="0.45"/>'
        )

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

    * {{ box-sizing: border-box; }}

    .pet-card {{
        width: min(94vw, 760px);
        margin: 0 auto;
        padding: 22px 18px 18px;
        border-radius: 32px;
        background:
            radial-gradient(circle at 50% 12%, {glow}, transparent 42%),
            linear-gradient(180deg, rgba(255,255,255,0.11), rgba(255,255,255,0.035));
        border: 1px solid rgba(255,255,255,0.13);
        box-shadow: 0 28px 80px rgba(0,0,0,0.34);
        backdrop-filter: blur(18px);
    }}

    .title {{
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        gap: 10px;
        align-items: center;
        font-weight: 900;
        letter-spacing: 0.3px;
        font-size: 18px;
        margin-bottom: 8px;
    }}

    .pill {{
        font-size: 12px;
        font-weight: 800;
        padding: 5px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(255,255,255,0.15);
        color: {accent};
    }}

    .dino-stage {{
        min-height: 345px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        position: relative;
    }}

    .dino-wrap {{
        width: min(92vw, 520px);
        max-width: 520px;
        aspect-ratio: 1.44;
        position: relative;
        animation: dino-float 3s ease-in-out infinite;
    }}

    .dino-wrap.happy {{ animation: dino-happy 1.45s ease-in-out infinite; }}
    .dino-wrap.sleepy {{ animation: dino-sleepy 4s ease-in-out infinite; }}
    .dino-wrap.hungry {{ animation: dino-shake 0.88s ease-in-out infinite; }}
    .dino-wrap.sad {{ animation: dino-sad 3.2s ease-in-out infinite; }}

    .dino-glow {{
        position: absolute;
        inset: 16% 10% 10%;
        border-radius: 999px;
        background: {glow};
        filter: blur(38px);
        animation: glow-pulse 2.4s ease-in-out infinite;
    }}

    .dino-svg {{
        position: relative;
        width: 100%;
        height: 100%;
        filter: drop-shadow(0 26px 42px rgba(0, 0, 0, 0.48));
    }}

    .tail {{ transform-origin: 350px 158px; animation: tail-wag 1.7s ease-in-out infinite; }}
    .head {{ transform-origin: 180px 150px; animation: head-nod 2.4s ease-in-out infinite; }}
    .jaw {{ transform-origin: 124px 135px; animation: jaw-talk 2.8s ease-in-out infinite; }}
    .dino-eye {{ animation: eye-blink 4.4s ease-in-out infinite; transform-origin: center; }}
    .leg-front {{ transform-origin: 270px 215px; animation: leg-step 2.6s ease-in-out infinite; }}
    .leg-back {{ transform-origin: 355px 215px; animation: leg-step 2.6s ease-in-out infinite reverse; }}
    .arm {{ transform-origin: 230px 160px; animation: arm-wave 2.1s ease-in-out infinite; }}
    .sensor {{ animation: light-pulse 1.4s ease-in-out infinite; }}
    .energy-line {{ animation: data-flow 1.8s linear infinite; }}

    .speech {{
        margin: -6px auto 0;
        width: min(94%, 600px);
        padding: 14px 16px;
        border-radius: 20px;
        background: rgba(5, 12, 24, 0.66);
        border: 1px solid rgba(255,255,255,0.12);
        text-align: center;
        line-height: 1.45;
        color: #eef6ff;
    }}

    .float-text {{
        fill: {accent};
        font-weight: 900;
        font-size: 26px;
        opacity: 0.88;
        animation: float-text 2.1s ease-in-out infinite;
    }}
    .float-text.small {{ font-size: 15px; animation-delay: 0.35s; }}
    .food {{ font-size: 20px; letter-spacing: 1px; }}
    .tear {{ animation: tear-drop 1.8s ease-in-out infinite; }}

    @keyframes dino-float {{
        0%, 100% {{ transform: translateY(0); }}
        50% {{ transform: translateY(-12px); }}
    }}

    @keyframes dino-happy {{
        0%, 100% {{ transform: translateY(0) rotate(-0.6deg); }}
        50% {{ transform: translateY(-17px) rotate(0.8deg); }}
    }}

    @keyframes dino-sleepy {{
        0%, 100% {{ transform: translateY(0) rotate(-1deg); opacity: 0.88; }}
        50% {{ transform: translateY(4px) rotate(1deg); opacity: 1; }}
    }}

    @keyframes dino-shake {{
        0%, 100% {{ transform: translateX(0); }}
        25% {{ transform: translateX(-4px); }}
        75% {{ transform: translateX(4px); }}
    }}

    @keyframes dino-sad {{
        0%, 100% {{ transform: translateY(8px); }}
        50% {{ transform: translateY(2px); }}
    }}

    @keyframes tail-wag {{
        0%, 100% {{ transform: rotate(-3deg); }}
        50% {{ transform: rotate(7deg); }}
    }}

    @keyframes head-nod {{
        0%, 100% {{ transform: rotate(0deg) translateY(0); }}
        50% {{ transform: rotate(-2deg) translateY(-4px); }}
    }}

    @keyframes jaw-talk {{
        0%, 82%, 100% {{ transform: rotate(0deg); }}
        88% {{ transform: rotate(5deg); }}
        94% {{ transform: rotate(-2deg); }}
    }}

    @keyframes leg-step {{
        0%, 100% {{ transform: rotate(0deg); }}
        50% {{ transform: rotate(3deg); }}
    }}

    @keyframes arm-wave {{
        0%, 100% {{ transform: rotate(-2deg); }}
        50% {{ transform: rotate(11deg); }}
    }}

    @keyframes glow-pulse {{
        0%, 100% {{ opacity: 0.58; transform: scale(0.96); }}
        50% {{ opacity: 1; transform: scale(1.08); }}
    }}

    @keyframes eye-blink {{
        0%, 44%, 52%, 100% {{ transform: scaleY(1); opacity: 1; }}
        48% {{ transform: scaleY(0.10); opacity: 0.82; }}
    }}

    @keyframes light-pulse {{
        0%, 100% {{ opacity: 0.45; }}
        50% {{ opacity: 1; }}
    }}

    @keyframes data-flow {{
        0% {{ stroke-dashoffset: 42; opacity: .45; }}
        50% {{ opacity: 1; }}
        100% {{ stroke-dashoffset: 0; opacity: .45; }}
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
            <span>🦖 RAPTOR X BOT</span>
            <span class="pill">{safe_mood_label}</span>
            <span class="pill">LV {level}</span>
            <span class="pill">XP {xp}/100</span>
        </div>

        <div class="dino-stage" aria-label="Robot dinosaurus interaktif">
            <div class="dino-wrap {mood}">
                <div class="dino-glow"></div>
                <svg class="dino-svg" viewBox="0 0 520 360" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Interactive robot dinosaur animation">
                    <defs>
                        <linearGradient id="bodyGrad" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0%" stop-color="#f9fcff"/>
                            <stop offset="48%" stop-color="#b7c7dc"/>
                            <stop offset="100%" stop-color="#72839d"/>
                        </linearGradient>
                        <linearGradient id="darkGrad" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0%" stop-color="#17233c"/>
                            <stop offset="100%" stop-color="#060b14"/>
                        </linearGradient>
                        <linearGradient id="jointGrad" x1="0" y1="0" x2="1" y2="1">
                            <stop offset="0%" stop-color="#d8e6f5"/>
                            <stop offset="100%" stop-color="#6f829d"/>
                        </linearGradient>
                    </defs>

                    <ellipse cx="282" cy="303" rx="150" ry="22" fill="rgba(0,0,0,0.32)"/>

                    <g class="tail">
                        <path d="M356 162 C410 138 462 121 500 91" fill="none" stroke="#8fa3bf" stroke-width="35" stroke-linecap="round"/>
                        <path d="M366 158 C414 139 459 124 492 98" fill="none" stroke="#e7f2ff" stroke-width="18" stroke-linecap="round" opacity="0.92"/>
                        <path class="energy-line" d="M382 154 C423 138 454 125 484 105" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round" stroke-dasharray="10 12"/>
                    </g>

                    <g class="leg-back">
                        <path d="M338 211 C356 241 357 270 344 291" fill="none" stroke="#7688a4" stroke-width="27" stroke-linecap="round"/>
                        <circle cx="337" cy="217" r="24" fill="url(#jointGrad)"/>
                        <circle cx="337" cy="217" r="10" fill="{accent}" opacity="0.75"/>
                        <path d="M343 291 L403 300" fill="none" stroke="#101723" stroke-width="18" stroke-linecap="round"/>
                        <path d="M397 300 L416 294 M397 300 L420 305 M397 300 L413 315" stroke="#111827" stroke-width="8" stroke-linecap="round"/>
                    </g>

                    <g class="leg-front">
                        <path d="M259 210 C277 239 273 271 252 291" fill="none" stroke="#7d91ad" stroke-width="28" stroke-linecap="round"/>
                        <circle cx="258" cy="216" r="25" fill="url(#jointGrad)"/>
                        <circle cx="258" cy="216" r="10" fill="{accent}" opacity="0.78"/>
                        <path d="M252 291 L309 301" fill="none" stroke="#101723" stroke-width="18" stroke-linecap="round"/>
                        <path d="M302 301 L324 294 M302 301 L329 306 M302 301 L320 316" stroke="#111827" stroke-width="8" stroke-linecap="round"/>
                    </g>

                    <path d="M188 135 C226 86 311 91 365 142 C386 162 382 205 351 223 C295 255 210 238 176 198 C159 178 163 155 188 135Z" fill="url(#bodyGrad)"/>
                    <path d="M214 126 C250 105 310 108 345 143" fill="none" stroke="rgba(255,255,255,.58)" stroke-width="12" stroke-linecap="round"/>
                    <path class="energy-line" d="M222 179 C260 159 304 160 343 180" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-dasharray="12 14"/>
                    <rect x="245" y="139" width="74" height="28" rx="14" fill="url(#darkGrad)" opacity="0.95"/>
                    <rect x="258" y="149" width="45" height="8" rx="4" fill="{accent}" opacity="0.88"/>
                    <circle class="sensor" cx="331" cy="153" r="10" fill="{accent}" opacity="0.76"/>
                    <circle cx="331" cy="153" r="20" fill="none" stroke="{accent}" stroke-width="3" opacity="0.28"/>
                    {dirt}

                    <g class="arm">
                        <path d="M219 178 C198 189 192 210 202 222" fill="none" stroke="#7f93af" stroke-width="15" stroke-linecap="round"/>
                        <path d="M203 222 L184 232 M203 222 L207 241" stroke="#101723" stroke-width="7" stroke-linecap="round"/>
                        <circle cx="220" cy="178" r="12" fill="url(#jointGrad)"/>
                    </g>

                    <path d="M176 151 C158 133 153 112 166 91" fill="none" stroke="#8398b6" stroke-width="25" stroke-linecap="round"/>
                    <path class="energy-line" d="M174 150 C159 130 159 111 171 94" fill="none" stroke="{accent}" stroke-width="4" stroke-linecap="round" stroke-dasharray="9 10"/>

                    <g class="head">
                        <path d="M88 66 C126 38 185 47 204 89 C214 111 199 136 170 145 C133 157 83 150 48 126 C27 112 33 86 88 66Z" fill="url(#bodyGrad)"/>
                        <path d="M48 126 C88 135 128 139 165 135 C133 161 85 162 52 145 C41 140 38 132 48 126Z" fill="#e5eef9" opacity="0.95"/>
                        <path d="M74 75 C113 55 162 59 188 90" fill="none" stroke="rgba(255,255,255,.64)" stroke-width="10" stroke-linecap="round"/>
                        <rect x="105" y="76" width="68" height="36" rx="18" fill="url(#darkGrad)" opacity="0.95"/>
                        {eye}
                        {mouth}
                        <circle class="sensor" cx="72" cy="104" r="7" fill="{accent}" opacity="0.84"/>
                        <circle cx="72" cy="104" r="15" fill="none" stroke="{accent}" stroke-width="3" opacity="0.28"/>
                        <path d="M62 127 L72 143 L82 129 M91 132 L100 147 L110 132 M120 134 L129 148 L139 132" fill="none" stroke="#101723" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity="0.90"/>
                    </g>

                    {extra}
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
    render_metric("Nutrisi", int(pet["hunger"]), "🥩")
    render_metric("Bonding", int(pet["happiness"]), "🤝")
with right:
    render_metric("Baterai", int(pet["energy"]), "🔋")
    render_metric("Sensor", int(pet["hygiene"]), "📡")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="pet-section-title">Interaksi Raptor X</div>', unsafe_allow_html=True)
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🥩 Beri Energi", use_container_width=True):
        action_feed()
        st.rerun()
with col2:
    if st.button("🎾 Latih Raptor", use_container_width=True):
        action_play()
        st.rerun()
with col3:
    if st.button("😴 Sleep Mode", use_container_width=True):
        action_sleep()
        st.rerun()

col4, col5, col6 = st.columns(3)
with col4:
    if st.button("📡 Bersihkan Sensor", use_container_width=True):
        action_clean()
        st.rerun()
with col5:
    if st.button("⚡ Charge Core", use_container_width=True):
        action_charge()
        st.rerun()
with col6:
    if st.button("🔁 Reset", use_container_width=True):
        action_reset()
        st.rerun()


st.markdown('<div class="pet-section-title">Ajak bicara Raptor X</div>', unsafe_allow_html=True)
with st.form("raptor_chat_form", clear_on_submit=True):
    user_talk = st.text_input(
        "Ketik perintah",
        placeholder="contoh: status, ping, update, roar, makan, tidur, bersih",
        label_visibility="collapsed",
    )
    submitted_talk = st.form_submit_button("💬 Kirim ke Raptor X", use_container_width=True)

if submitted_talk:
    action_talk(user_talk)
    st.rerun()


# =========================
# ADMIN PAGE
# =========================
# Bagian Aksi Bot dan Best Ping disembunyikan dari halaman publik.
# Buka dengan: https://yamlku.streamlit.app/?admin=1
ADMIN_PASSWORD = get_setting("ADMIN_PASSWORD", "")
ADMIN_QUERY_KEY = get_setting("ADMIN_QUERY_KEY", "admin") or "admin"
ADMIN_QUERY_VALUE = get_setting("ADMIN_QUERY_VALUE", "1") or "1"


def get_query_param_value(key: str, default: str = "") -> str:
    """Kompatibel untuk Streamlit versi lama dan baru."""
    try:
        value = st.query_params.get(key, default)
        if isinstance(value, list):
            return str(value[0]) if value else default
        return str(value)
    except Exception:
        try:
            params = st.experimental_get_query_params()
            value = params.get(key, [default])
            if isinstance(value, list):
                return str(value[0]) if value else default
            return str(value)
        except Exception:
            return default


def is_admin_route() -> bool:
    value = get_query_param_value(ADMIN_QUERY_KEY, "").strip().lower()
    allowed_values = {
        ADMIN_QUERY_VALUE.strip().lower(),
        "1",
        "true",
        "yes",
        "admin",
    }
    return bool(value) and value in allowed_values


def ensure_admin_authenticated() -> bool:
    if not is_admin_route():
        return False

    if not ADMIN_PASSWORD:
        st.warning(
            "Halaman admin terkunci. Isi ADMIN_PASSWORD di Streamlit Secrets dulu."
        )
        st.code('ADMIN_PASSWORD = "password_admin_anda"')
        return False

    if st.session_state.get("admin_authenticated") is True:
        return True

    st.markdown('<div class="pet-section-title">Admin Login</div>', unsafe_allow_html=True)
    with st.form("admin_login_form"):
        password = st.text_input("Password admin", type="password")
        submitted = st.form_submit_button("Masuk Admin")

    if submitted:
        if password == ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            set_pet_action("Mode admin aktif. Panel kontrol sudah dibuka.")
            st.rerun()
        else:
            st.error("Password admin salah.")

    return False


def render_admin_actions():
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


def render_admin_best_ping():
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
            "Best ping belum bisa ditampilkan. Pastikan output/BestPing/top5_indonesia_ping.csv sudah ada. Jika belum, jalankan /update_ping atau tombol Test + Update Ping."
        )
        with st.expander("Detail error best ping"):
            st.code(str(exc))


if ensure_admin_authenticated():
    render_workflow_status_panel()
    render_admin_actions()
    render_admin_best_ping()
    if st.button("🚪 Keluar Admin", use_container_width=True):
        st.session_state.admin_authenticated = False
        st.rerun()

    st.markdown(
        '<div class="pet-small-note">Mode admin aktif. Telegram tetap aktif di background: /check, /update, /update_ping, /test, /test_ping, /best, /status, /id, /help.</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="pet-small-note">Mode publik. Raptor X bisa diajak interaksi; panel Aksi Bot dan Best Ping hanya tersedia di halaman admin.</div>',
        unsafe_allow_html=True,
    )
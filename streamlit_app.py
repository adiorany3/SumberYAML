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
# STREAMLIT HACKER UI SETUP
# =========================
st.set_page_config(
    page_title="Yamlku Hacker Console",
    page_icon="💻",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Tampilan hacker terminal. Bot Telegram tetap berjalan di background.
st.markdown(
    """
    <style>
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;}
        [data-testid="stDecoration"] {visibility: hidden;}
        [data-testid="stStatusWidget"] {visibility: hidden;}

        :root {
            --hacker-green: #00ff88;
            --hacker-green-soft: rgba(0, 255, 136, 0.16);
            --hacker-green-line: rgba(0, 255, 136, 0.28);
            --hacker-cyan: #19d8ff;
            --hacker-bg: #020403;
            --hacker-panel: rgba(3, 18, 10, 0.82);
            --hacker-text: #d8ffe9;
            --hacker-muted: rgba(216, 255, 233, 0.68);
        }

        html, body, [data-testid="stAppViewContainer"] {
            min-height: 100vh;
            background:
                radial-gradient(circle at 20% 10%, rgba(0, 255, 136, 0.12), transparent 28%),
                radial-gradient(circle at 82% 18%, rgba(25, 216, 255, 0.10), transparent 30%),
                linear-gradient(180deg, #020403 0%, #041108 48%, #010201 100%);
            color: var(--hacker-text);
        }

        [data-testid="stAppViewContainer"]::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            background-image:
                linear-gradient(rgba(0, 255, 136, 0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 255, 136, 0.026) 1px, transparent 1px);
            background-size: 32px 32px;
            mask-image: linear-gradient(180deg, rgba(0,0,0,0.95), rgba(0,0,0,0.35));
        }

        [data-testid="stAppViewContainer"]::after {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            background: repeating-linear-gradient(
                180deg,
                rgba(255, 255, 255, 0.025) 0,
                rgba(255, 255, 255, 0.025) 1px,
                transparent 1px,
                transparent 5px
            );
            mix-blend-mode: screen;
            opacity: 0.32;
        }

        .block-container {
            max-width: 900px !important;
            padding: 30px 14px 50px !important;
            margin: 0 auto !important;
            position: relative;
            z-index: 1;
        }

        h1, h2, h3, p, label, span, div {
            font-family: "JetBrains Mono", "Fira Code", Consolas, Menlo, Monaco, monospace;
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

# Admin route/login configuration.
# Harus didefinisikan sebelum public terminal dirender karena status admin ditampilkan di halaman publik.
ADMIN_PASSWORD = get_setting("ADMIN_PASSWORD", "")
ADMIN_QUERY_KEY = get_setting("ADMIN_QUERY_KEY", "admin") or "admin"
ADMIN_QUERY_VALUE = get_setting("ADMIN_QUERY_VALUE", "1") or "1"

# Panel QR sing-box hanya dirender di halaman admin setelah login.
SHOW_SINGBOX_QR_PANEL = get_setting("SHOW_SINGBOX_QR_PANEL", "true").strip().lower() in ["1", "true", "yes", "y", "on"]
SINGBOX_DEFAULT_PROFILE_NAME = get_setting("SINGBOX_DEFAULT_PROFILE_NAME", "SumberYAML Lengkap")
SINGBOX_DEFAULT_JSON_PATH = get_setting("SINGBOX_DEFAULT_JSON_PATH", "output/SingBox/lengkap.json")
SINGBOX_DEFAULT_QR_ERROR_CORRECTION = get_setting("SINGBOX_DEFAULT_QR_ERROR_CORRECTION", "M").upper()
SINGBOX_KNOWN_JSON_PATHS = [
    "output/SingBox/lengkap.json",
    "output/SingBox/latest.json",
    "output/SingBox/lengkap-new-dns.json",
    "output/SingBox/lengkap-legacy-tun.json",
    "output/SingBox/fast.json",
    "output/SingBox/gaming.json",
    "output/SingBox/streaming.json",
    "output/SingBox/social_media.json",
    "output/SingBox/working.json",
    "output/SingBox/general.json",
]


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




# =========================
# SING-BOX QR ADMIN HELPERS
# =========================
def normalize_github_blob_url(url: str) -> str:
    """Convert common github.com/.../blob/... link to raw.githubusercontent.com link."""
    cleaned = str(url or "").strip()

    if "github.com" in cleaned and "/blob/" in cleaned:
        cleaned = cleaned.replace(
            "https://github.com/",
            "https://raw.githubusercontent.com/",
        )
        cleaned = cleaned.replace("/blob/", "/")

    return cleaned


def build_raw_github_url(path: str) -> str:
    clean_path = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not clean_path:
        clean_path = SINGBOX_DEFAULT_JSON_PATH

    if not GITHUB_OWNER or not GITHUB_REPO:
        return ""

    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_REF}/{clean_path}"


def build_singbox_remote_profile_uri(raw_url: str, profile_name: str) -> str:
    """Build sing-box remote profile deep link for QR/import."""
    clean_url = normalize_github_blob_url(raw_url)
    encoded_url = quote(clean_url.strip(), safe="")
    encoded_name = quote((profile_name or "SumberYAML SingBox").strip(), safe="")
    return f"sing-box://import-remote-profile?url={encoded_url}#{encoded_name}"


def make_qr_png_bytes(data: str, error_correction: str = "M") -> bytes:
    """Generate QR PNG bytes lazily so public page does not require qrcode import."""
    try:
        import qrcode
    except Exception as exc:
        raise RuntimeError(
            "Library qrcode belum terpasang. Tambahkan `qrcode[pil]` dan `pillow` ke requirements.txt."
        ) from exc

    correction_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    qr = qrcode.QRCode(
        version=None,
        error_correction=correction_map.get(str(error_correction).upper(), qrcode.constants.ERROR_CORRECT_M),
        box_size=9,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def parse_json_text_for_admin(text: str) -> tuple:
    try:
        data = json.loads(text or "{}")
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        return data, pretty, None
    except Exception as exc:
        return None, text or "", str(exc)


def singbox_metric_counts(config) -> tuple:
    if not isinstance(config, dict):
        return 0, 0, 0

    inbounds = config.get("inbounds", [])
    outbounds = config.get("outbounds", [])
    rules = []

    if isinstance(config.get("route"), dict):
        rules = config.get("route", {}).get("rules", [])

    return (
        len(inbounds) if isinstance(inbounds, list) else 0,
        len(outbounds) if isinstance(outbounds, list) else 0,
        len(rules) if isinstance(rules, list) else 0,
    )


def validate_singbox_profile_config(config) -> list:
    warnings = []

    if not isinstance(config, dict):
        return ["Config belum terbaca sebagai object JSON."]

    outbounds = config.get("outbounds")
    inbounds = config.get("inbounds")
    route = config.get("route")
    dns = config.get("dns")

    if not isinstance(outbounds, list) or not outbounds:
        warnings.append("Field `outbounds` kosong/tidak ada. Profile sing-box biasanya wajib punya outbounds.")
    if inbounds is not None and not isinstance(inbounds, list):
        warnings.append("Field `inbounds` harus berupa array/list.")
    if route is not None and not isinstance(route, dict):
        warnings.append("Field `route` harus berupa object JSON.")
    if dns is not None and not isinstance(dns, dict):
        warnings.append("Field `dns` harus berupa object JSON.")

    known_tags = set()
    referenced_tags = []

    if isinstance(outbounds, list):
        for item in outbounds:
            if not isinstance(item, dict):
                warnings.append("Ada item outbound yang bukan object JSON.")
                continue

            tag = item.get("tag")
            outbound_type = item.get("type")

            if tag:
                if tag in known_tags:
                    warnings.append(f"Outbound tag duplikat: `{tag}`.")
                known_tags.add(tag)

            if outbound_type in {"block", "dns"}:
                warnings.append(
                    "Masih ada special outbound lama `block`/`dns`. Untuk sing-box 1.11+ gunakan rule action."
                )

            if outbound_type in {"selector", "urltest"}:
                group_outbounds = item.get("outbounds", [])
                if isinstance(group_outbounds, list):
                    referenced_tags.extend([str(value) for value in group_outbounds])

    builtins = {"direct", "DIRECT"}
    missing_refs = sorted({tag for tag in referenced_tags if tag not in known_tags and tag not in builtins})
    if missing_refs:
        preview = ", ".join(missing_refs[:8])
        if len(missing_refs) > 8:
            preview += f", +{len(missing_refs) - 8} lainnya"
        warnings.append(f"Ada referensi outbound group yang tidak ditemukan: {preview}.")

    return warnings


def render_qr_status_card(message: str, variant: str = "ok"):
    color = "#00ff88" if variant == "ok" else "#ffcc66" if variant == "warn" else "#ff8a8a"
    safe_message = escape(str(message))
    st.markdown(
        f"""
        <div class="pet-panel" style="border-color:{color};margin-top:10px;">
            <div style="font-weight:900;color:{color};">{safe_message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
# HACKER TERMINAL UI
# =========================

TERMINAL_DEFAULT_MESSAGE = "SYSTEM ONLINE — Telegram worker aktif di background."


def init_terminal_state():
    if "terminal_message" not in st.session_state:
        st.session_state.terminal_message = TERMINAL_DEFAULT_MESSAGE


def set_pet_action(message: str):
    """Backward-compatible status setter.

    Beberapa fungsi admin lama masih memanggil set_pet_action().
    Nama fungsi dipertahankan agar backend tidak perlu diubah, tetapi outputnya
    sekarang masuk ke terminal status, bukan robot/pet.
    """
    st.session_state.terminal_message = str(message or TERMINAL_DEFAULT_MESSAGE)


def add_xp(amount: int):
    """No-op compatibility hook setelah fitur robot/pet dihapus."""
    return None


def render_terminal_line(label: str, value: str, status: str = "ok"):
    safe_label = escape(str(label))
    safe_value = escape(str(value))
    safe_status = escape(str(status).upper())
    st.markdown(
        f"""
        <div class="terminal-line">
            <span class="terminal-label">{safe_label}</span>
            <span class="terminal-value">{safe_value}</span>
            <span class="terminal-badge">{safe_status}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <style>
        .stButton > button {
            width: 100%;
            min-height: 46px;
            border-radius: 10px;
            border: 1px solid rgba(0, 255, 136, 0.32);
            background: linear-gradient(180deg, rgba(0, 255, 136, 0.11), rgba(0, 0, 0, 0.42));
            color: #d8ffe9;
            font-weight: 800;
            letter-spacing: 0.2px;
            box-shadow: 0 0 18px rgba(0, 255, 136, 0.08);
        }

        .stButton > button:hover {
            border-color: rgba(0, 255, 136, 0.78);
            background: linear-gradient(180deg, rgba(0, 255, 136, 0.18), rgba(0, 0, 0, 0.46));
            color: #ffffff;
            box-shadow: 0 0 24px rgba(0, 255, 136, 0.20);
        }

        .stTextInput input {
            border-radius: 10px;
            border: 1px solid rgba(0, 255, 136, 0.32) !important;
            background: rgba(0, 0, 0, 0.38) !important;
            color: #d8ffe9 !important;
            font-family: "JetBrains Mono", "Fira Code", Consolas, monospace !important;
        }

        .hacker-hero {
            position: relative;
            overflow: hidden;
            border-radius: 22px;
            padding: 24px 22px;
            background:
                radial-gradient(circle at 18% 22%, rgba(0, 255, 136, 0.14), transparent 32%),
                linear-gradient(135deg, rgba(0, 20, 10, 0.94), rgba(0, 0, 0, 0.84));
            border: 1px solid rgba(0, 255, 136, 0.28);
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.46), inset 0 0 42px rgba(0, 255, 136, 0.045);
        }

        .hacker-hero::before {
            content: "01001001 01001110 01001001 01001011 01000001 01001110 01010011 01000001 01010100 01010101";
            position: absolute;
            top: 12px;
            right: -90px;
            width: 520px;
            color: rgba(0, 255, 136, 0.11);
            font-size: 12px;
            line-height: 1.8;
            transform: rotate(10deg);
            white-space: normal;
            pointer-events: none;
        }

        .hacker-kicker {
            color: #00ff88;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            margin-bottom: 10px;
        }

        .hacker-title {
            color: #eafff2;
            font-size: clamp(28px, 6vw, 52px);
            line-height: 1.0;
            font-weight: 950;
            letter-spacing: -0.055em;
            margin: 0;
            text-shadow: 0 0 24px rgba(0, 255, 136, 0.20);
        }

        .hacker-subtitle {
            margin-top: 12px;
            color: rgba(216, 255, 233, 0.72);
            font-size: 14px;
            line-height: 1.65;
            max-width: 680px;
        }

        .terminal-panel,
        .pet-panel {
            margin-top: 14px;
            padding: 16px;
            border-radius: 18px;
            background: rgba(0, 11, 5, 0.76);
            border: 1px solid rgba(0, 255, 136, 0.22);
            box-shadow: inset 0 0 28px rgba(0, 255, 136, 0.045), 0 18px 45px rgba(0, 0, 0, 0.28);
            backdrop-filter: blur(18px);
        }

        .terminal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            color: #00ff88;
            font-size: 13px;
            font-weight: 900;
            margin-bottom: 12px;
            border-bottom: 1px solid rgba(0, 255, 136, 0.16);
            padding-bottom: 10px;
        }

        .terminal-dots {
            display: flex;
            gap: 7px;
        }

        .terminal-dot {
            width: 9px;
            height: 9px;
            border-radius: 999px;
            background: #00ff88;
            box-shadow: 0 0 12px rgba(0, 255, 136, 0.65);
        }

        .terminal-line {
            display: grid;
            grid-template-columns: minmax(120px, 0.42fr) minmax(0, 1fr) auto;
            align-items: center;
            gap: 10px;
            padding: 10px 0;
            border-bottom: 1px solid rgba(0, 255, 136, 0.09);
            font-size: 13px;
        }

        .terminal-line:last-child {
            border-bottom: 0;
        }

        .terminal-label {
            color: rgba(216, 255, 233, 0.62);
            text-transform: uppercase;
            font-weight: 800;
        }

        .terminal-value {
            color: #eafff2;
            overflow-wrap: anywhere;
        }

        .terminal-badge {
            justify-self: end;
            min-width: 54px;
            text-align: center;
            padding: 3px 7px;
            border-radius: 999px;
            color: #031108;
            background: #00ff88;
            font-size: 11px;
            font-weight: 950;
            box-shadow: 0 0 12px rgba(0, 255, 136, 0.24);
        }

        .terminal-output {
            margin-top: 12px;
            padding: 14px;
            border-radius: 14px;
            background: rgba(0, 0, 0, 0.48);
            border: 1px solid rgba(0, 255, 136, 0.16);
            color: #00ff88;
            font-size: 13px;
            line-height: 1.7;
            min-height: 72px;
            white-space: normal;
        }

        .terminal-output::before {
            content: "> ";
            color: #19d8ff;
            font-weight: 900;
        }

        .pet-small-note {
            color: rgba(216, 255, 233, 0.64);
            text-align: center;
            font-size: 13px;
            margin-top: 12px;
            line-height: 1.6;
        }

        .pet-section-title {
            color: #00ff88;
            font-weight: 950;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 18px 0 8px;
            text-align: center;
            text-shadow: 0 0 14px rgba(0, 255, 136, 0.30);
        }

        .best-ping-card {
            margin-top: 12px;
            padding: 16px;
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(0, 255, 136, 0.10), rgba(0, 0, 0, 0.54));
            border: 1px solid rgba(0, 255, 136, 0.24);
            box-shadow: 0 18px 42px rgba(0,0,0,0.30);
            color: #d8ffe9;
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
            color: #00ff88;
        }

        .best-ping-meta {
            color: rgba(216,255,233,0.72);
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
            border-radius: 13px;
            background: rgba(0,255,136,0.045);
            border: 1px solid rgba(0,255,136,0.13);
        }

        .best-ping-rank {
            font-weight: 900;
            color: #00ff88;
        }

        .best-ping-name {
            font-weight: 800;
            font-size: 13px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .best-ping-sub {
            color: rgba(216,255,233,0.60);
            font-size: 12px;
            margin-top: 2px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


init_terminal_state()

st.markdown(
    """
    <div class="hacker-hero">
        <div class="hacker-kicker">SECURE STREAMLIT CONTROL NODE</div>
        <h1 class="hacker-title">YAMLKU<br>HACKER CONSOLE</h1>
        <div class="hacker-subtitle">
            Nothing here, go out right now
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Public page intentionally hides internal service information.
# Telegram/GitHub/workflow/admin status tetap aktif di backend,
# tetapi tidak ditampilkan di halaman publik.


# =========================
# ADMIN PAGE
# =========================
# Bagian Aksi Bot dan Best Ping disembunyikan dari halaman publik.
# Buka dengan: https://yamlku.streamlit.app/?admin=1


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
            set_pet_action("Mode admin aktif. Terminal kontrol sudah dibuka.")
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
                set_pet_action("Update config berhasil dipicu. Menunggu hasil GitHub Actions.")
                st.success("Update GitHub Actions berhasil dipicu.")
                add_xp(18)
            except Exception as exc:
                set_pet_action("Gagal memicu update. Cek token/repo/workflow.")
                st.error(str(exc))
            st.rerun()
    with bot_col2:
        if st.button("🧪 Test Proxy", use_container_width=True):
            try:
                dispatch_workflow(mode="test", enable_proxy_test="true", filter_alive_only="false")
                set_pet_action("Test proxy berhasil dipicu. Menunggu laporan alive/dead.")
                st.success("Test proxy GitHub Actions berhasil dipicu.")
                add_xp(18)
            except Exception as exc:
                set_pet_action("Gagal memicu test proxy. Cek workflow input dan secrets.")
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
                set_pet_action("Gagal memicu test best ping. Cek workflow dan secrets.")
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


def render_admin_singbox_qr():
    """Panel QR sing-box. Hanya dipanggil setelah admin login."""
    if not SHOW_SINGBOX_QR_PANEL:
        return

    st.markdown('<div class="pet-section-title">Sing-box Profile QR</div>', unsafe_allow_html=True)

    if not GITHUB_OWNER or not GITHUB_REPO:
        st.info("QR sing-box belum bisa dibuat karena GITHUB_REPOSITORY/GITHUB_OWNER/GITHUB_REPO belum terisi.")
        return

    default_paths = list(dict.fromkeys([SINGBOX_DEFAULT_JSON_PATH] + SINGBOX_KNOWN_JSON_PATHS))
    mode_col, name_col = st.columns([0.52, 0.48])

    with mode_col:
        path_mode = st.radio(
            "Sumber JSON sing-box",
            ["File output repo", "Raw URL manual"],
            horizontal=True,
            key="singbox_qr_source_mode",
        )

    with name_col:
        profile_name = st.text_input(
            "Nama profile",
            value=SINGBOX_DEFAULT_PROFILE_NAME,
            key="singbox_qr_profile_name",
        )

    selected_path = SINGBOX_DEFAULT_JSON_PATH
    raw_url = build_raw_github_url(selected_path)

    if path_mode == "File output repo":
        selected_path = st.selectbox(
            "Pilih file JSON di repo",
            default_paths + ["Custom path..."],
            index=0,
            key="singbox_qr_selected_path",
        )
        if selected_path == "Custom path...":
            selected_path = st.text_input(
                "Custom path JSON",
                value=SINGBOX_DEFAULT_JSON_PATH,
                placeholder="output/SingBox/lengkap.json",
                key="singbox_qr_custom_path",
            )
        raw_url = build_raw_github_url(selected_path)
    else:
        raw_url = st.text_input(
            "Raw URL JSON sing-box",
            value=build_raw_github_url(SINGBOX_DEFAULT_JSON_PATH),
            help="Boleh paste URL github.com/.../blob/...; akan diubah otomatis menjadi raw URL.",
            key="singbox_qr_manual_raw_url",
        )
        raw_url = normalize_github_blob_url(raw_url)
        selected_path = "manual-url"

    error_correction = st.selectbox(
        "QR error correction",
        ["L", "M", "Q", "H"],
        index=["L", "M", "Q", "H"].index(SINGBOX_DEFAULT_QR_ERROR_CORRECTION) if SINGBOX_DEFAULT_QR_ERROR_CORRECTION in ["L", "M", "Q", "H"] else 1,
        help="M seimbang. H lebih tahan rusak, tetapi QR lebih padat.",
        key="singbox_qr_error_correction",
    )

    import_uri = build_singbox_remote_profile_uri(raw_url, profile_name)
    source_label = profile_name.strip() or str(selected_path).split("/")[-1].replace(".json", "") or "singbox"
    safe_file_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_label).strip("-") or "singbox-profile"

    left, right = st.columns([1.05, 0.95], gap="large")

    with left:
        st.markdown(
            """
            <div class="pet-panel">
                <div style="font-weight:900;color:#00ff88;">Mode import valid</div>
                <div class="pet-small-note" style="text-align:left;margin-top:8px;">
                    QR dibuat sebagai <b>remote profile deep link</b>, bukan raw JSON, sehingga cocok untuk import sing-box/SFA.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("Raw JSON URL:")
        st.code(raw_url or "GITHUB_REPOSITORY belum lengkap", language="text")
        st.write("Payload QR:")
        st.code(import_uri, language="text")

        st.link_button(
            "📲 Buka langsung di sing-box",
            import_uri,
            use_container_width=True,
        )

        validate_now = st.toggle(
            "Validasi JSON dari GitHub",
            value=True,
            help="Membaca file JSON memakai GitHub Contents API/raw URL, lalu cek struktur dasar sing-box.",
            key="singbox_qr_validate_now",
        )

        if validate_now:
            raw_text = ""
            config = None
            parse_error = None
            fetch_error = None

            try:
                if path_mode == "File output repo":
                    raw_text = fetch_github_file_text(selected_path)
                else:
                    response = requests.get(
                        raw_url,
                        timeout=15,
                        headers={"User-Agent": "yamlku-streamlit-singbox-qr"},
                    )
                    response.raise_for_status()
                    raw_text = response.text
                config, pretty_json, parse_error = parse_json_text_for_admin(raw_text)
            except Exception as exc:
                fetch_error = str(exc)
                pretty_json = raw_text

            if fetch_error:
                render_qr_status_card(f"JSON belum bisa dibaca: {fetch_error}", "error")
            elif parse_error:
                render_qr_status_card(f"File ditemukan, tetapi bukan JSON valid: {parse_error}", "error")
            else:
                in_count, out_count, rule_count = singbox_metric_counts(config)
                c1, c2, c3 = st.columns(3)
                c1.metric("Inbounds", in_count)
                c2.metric("Outbounds", out_count)
                c3.metric("Route rules", rule_count)

                warnings = validate_singbox_profile_config(config)
                if warnings:
                    st.warning("\n".join(f"- {item}" for item in warnings))
                else:
                    st.success("Struktur dasar JSON sing-box terlihat valid.")

                with st.expander("Preview JSON sing-box"):
                    st.code(pretty_json[:14000], language="json")
                    if len(pretty_json) > 14000:
                        st.caption("Preview dipotong sampai 14.000 karakter agar halaman tetap ringan.")

    with right:
        st.markdown(
            """
            <div class="pet-panel" style="text-align:center;">
                <div style="font-weight:900;color:#00ff88;margin-bottom:10px;">QR Import Profile</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        try:
            png_bytes = make_qr_png_bytes(import_uri, error_correction=error_correction)
            st.image(
                png_bytes,
                caption="Scan dari sing-box/SFA → Add profile / Scan QR",
                use_container_width=True,
            )
            st.download_button(
                "⬇️ Download QR PNG",
                data=png_bytes,
                file_name=f"{safe_file_label}-singbox-profile-qr.png",
                mime="image/png",
                use_container_width=True,
            )
            st.download_button(
                "⬇️ Download payload TXT",
                data=import_uri.encode("utf-8"),
                file_name=f"{safe_file_label}-singbox-profile-link.txt",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(str(exc))

        st.markdown(
            """
            <div class="pet-panel">
                <div style="font-weight:900;color:#ffcc66;">Catatan</div>
                <div class="pet-small-note" style="text-align:left;margin-top:8px;">
                    Jika masih muncul <i>not valid sing-box profile</i>, pastikan URL raw JSON bisa dibuka publik dan file JSON tidak kosong.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


if ensure_admin_authenticated():
    render_workflow_status_panel()
    render_admin_actions()
    render_admin_best_ping()
    render_admin_singbox_qr()
    if st.button("🚪 Keluar Admin", use_container_width=True):
        st.session_state.admin_authenticated = False
        st.rerun()

    st.markdown(
        '<div class="pet-small-note">Mode admin aktif. Telegram tetap aktif di background: /check, /update, /update_ping, /test, /test_ping, /best, /status, /id, /help.</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="pet-small-note">Mode publik. terminal hacker aktif; panel Aksi Bot dan Best Ping hanya tersedia di halaman admin.</div>',
        unsafe_allow_html=True,
    )

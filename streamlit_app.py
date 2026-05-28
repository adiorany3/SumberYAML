from __future__ import annotations

import glob
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import qrcode
import requests
import streamlit as st
from PIL import Image


REPO_OWNER = "adiorany3"
REPO_NAME = "SumberYAML"
DEFAULT_BRANCH = "main"
DEFAULT_PROFILE_NAME = "SumberYAML Lengkap"
DEFAULT_JSON_PATH = "output/SingBox/lengkap.json"
DEFAULT_RAW_URL = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/"
    f"{DEFAULT_BRANCH}/{DEFAULT_JSON_PATH}"
)


st.set_page_config(
    page_title="Sing-box Profile QR",
    page_icon="📱",
    layout="wide",
)


st.markdown(
    """
<style>
.block-container {
    padding-top: 1.4rem;
    padding-bottom: 2.5rem;
}
.good-card {
    border: 1px solid rgba(70, 160, 90, .35);
    border-radius: 18px;
    padding: 1rem 1.1rem;
    background: rgba(70, 160, 90, .06);
}
.warn-card {
    border: 1px solid rgba(230, 160, 40, .35);
    border-radius: 18px;
    padding: 1rem 1.1rem;
    background: rgba(230, 160, 40, .07);
}
.small-note {
    font-size: .9rem;
    opacity: .72;
}
</style>
""",
    unsafe_allow_html=True,
)


def normalize_github_url(url: str) -> str:
    """Convert common GitHub blob URL to raw.githubusercontent.com URL."""
    cleaned = url.strip()

    if "github.com" in cleaned and "/blob/" in cleaned:
        cleaned = cleaned.replace(
            "https://github.com/",
            "https://raw.githubusercontent.com/",
        )
        cleaned = cleaned.replace("/blob/", "/")

    return cleaned


def build_raw_github_url(
    owner: str,
    repo: str,
    branch: str,
    file_path: str,
) -> str:
    clean_path = file_path.replace("\\", "/").lstrip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{clean_path}"


def build_singbox_remote_profile_uri(
    raw_url: str,
    profile_name: str,
) -> str:
    """
    Build official sing-box graphical-client remote profile import URL scheme:
    sing-box://import-remote-profile?url=urlEncodedURL#urlEncodedName
    """
    encoded_url = quote(raw_url.strip(), safe="")
    encoded_name = quote(profile_name.strip() or "SingBox Profile", safe="")
    return f"sing-box://import-remote-profile?url={encoded_url}#{encoded_name}"


def find_json_files() -> list[str]:
    patterns = [
        "output/SingBox/*.json",
        "output/*.json",
        "*.json",
    ]

    files: list[str] = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))

    return sorted(set(files))


def make_qr_image(data: str, error_correction: str = "M") -> Image.Image:
    correction_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    qr = qrcode.QRCode(
        version=None,
        error_correction=correction_map.get(
            error_correction,
            qrcode.constants.ERROR_CORRECT_M,
        ),
        box_size=9,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)

    return qr.make_image(
        fill_color="black",
        back_color="white",
    ).convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def load_json_file(path: str) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        return "", None, f"Tidak bisa membaca file: {exc}"

    try:
        parsed = json.loads(text)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        return pretty, parsed, None
    except Exception as exc:
        return text, None, f"File bukan JSON valid: {exc}"


def fetch_remote_json(url: str) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        response = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "streamlit-singbox-profile-qr"},
        )
        response.raise_for_status()
    except Exception as exc:
        return "", None, f"Gagal mengambil URL: {exc}"

    text = response.text

    try:
        parsed = response.json()
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        return pretty, parsed, None
    except Exception as exc:
        return text, None, f"URL berhasil diambil, tetapi isinya bukan JSON valid: {exc}"


def validate_singbox_config(config: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = []

    if not isinstance(config, dict):
        return ["Config belum terbaca sebagai object JSON."]

    outbounds = config.get("outbounds")
    inbounds = config.get("inbounds")

    if not isinstance(outbounds, list) or not outbounds:
        warnings.append("Field `outbounds` kosong/tidak ada. Config sing-box biasanya wajib punya outbounds.")

    if inbounds is not None and not isinstance(inbounds, list):
        warnings.append("Field `inbounds` harus berupa array/list.")

    if isinstance(outbounds, list):
        tags = []
        for item in outbounds:
            if isinstance(item, dict):
                tag = item.get("tag")
                if tag:
                    tags.append(tag)

                if item.get("type") in {"block", "dns"}:
                    warnings.append(
                        "Masih ada special outbound lama `block`/`dns`. "
                        "Untuk sing-box 1.11+ sebaiknya migrasi ke rule action."
                    )

        if len(tags) != len(set(tags)):
            warnings.append("Ada tag outbound duplikat. Ini bisa membuat profile gagal jalan.")

    route = config.get("route")
    if route is not None and not isinstance(route, dict):
        warnings.append("Field `route` harus berupa object JSON.")

    dns = config.get("dns")
    if dns is not None and not isinstance(dns, dict):
        warnings.append("Field `dns` harus berupa object JSON.")

    return warnings


def metric_counts(config: dict[str, Any] | None) -> tuple[int, int, int]:
    if not isinstance(config, dict):
        return 0, 0, 0

    inbounds = config.get("inbounds", [])
    outbounds = config.get("outbounds", [])
    rules = config.get("route", {}).get("rules", []) if isinstance(config.get("route"), dict) else []

    return (
        len(inbounds) if isinstance(inbounds, list) else 0,
        len(outbounds) if isinstance(outbounds, list) else 0,
        len(rules) if isinstance(rules, list) else 0,
    )


st.title("📱 Sing-box Remote Profile QR")
st.caption(
    "QR valid untuk aplikasi sing-box/SFA harus berisi URL scheme remote profile, "
    "bukan raw JSON langsung."
)

with st.sidebar:
    st.header("Sumber profile")

    source_mode = st.radio(
        "Pilih sumber",
        [
            "Raw GitHub URL",
            "File lokal repo",
        ],
        index=0,
    )

    st.divider()
    st.header("Repository default")

    repo_owner = st.text_input("Owner", value=REPO_OWNER)
    repo_name = st.text_input("Repo", value=REPO_NAME)
    branch = st.text_input("Branch", value=DEFAULT_BRANCH)

    st.divider()
    st.header("QR")

    profile_name = st.text_input("Nama profile", value=DEFAULT_PROFILE_NAME)

    error_correction = st.selectbox(
        "Error correction",
        ["L", "M", "Q", "H"],
        index=1,
        help="M biasanya paling seimbang. Untuk QR sangat pendek, M/H aman.",
    )

    validate_remote = st.toggle(
        "Validasi remote JSON",
        value=True,
        help="Aplikasi akan mencoba mengambil raw URL dan cek struktur JSON sing-box dasar.",
    )


raw_url = DEFAULT_RAW_URL
source_label = "lengkap"
local_json_text = ""
local_json_obj: dict[str, Any] | None = None
local_error: str | None = None

if source_mode == "Raw GitHub URL":
    raw_url = st.text_input(
        "Raw URL file JSON sing-box",
        value=DEFAULT_RAW_URL,
        help=(
            "Bisa paste URL github.com/.../blob/...; aplikasi akan otomatis mengubahnya "
            "ke raw.githubusercontent.com."
        ),
    )
    raw_url = normalize_github_url(raw_url)
    source_label = raw_url.rstrip("/").split("/")[-1].replace(".json", "") or "singbox"

elif source_mode == "File lokal repo":
    local_files = find_json_files()

    if not local_files:
        st.warning(
            "Belum ada file JSON lokal. Pastikan ada `output/SingBox/*.json` "
            "atau pakai mode Raw GitHub URL."
        )
    else:
        selected_file = st.selectbox(
            "Pilih file JSON lokal",
            local_files,
            index=local_files.index(DEFAULT_JSON_PATH) if DEFAULT_JSON_PATH in local_files else 0,
        )
        source_label = Path(selected_file).stem
        raw_url = build_raw_github_url(repo_owner, repo_name, branch, selected_file)
        local_json_text, local_json_obj, local_error = load_json_file(selected_file)


import_uri = build_singbox_remote_profile_uri(raw_url, profile_name)

left, right = st.columns([1.08, 0.92], gap="large")

with left:
    st.subheader("Payload profile")

    st.markdown(
        """
<div class="good-card">
<b>Mode yang benar untuk scan sing-box:</b><br>
QR di kanan berisi <code>sing-box://import-remote-profile?url=...#NamaProfile</code>.
</div>
""",
        unsafe_allow_html=True,
    )

    st.write("Raw JSON URL:")
    st.code(raw_url, language="text")

    st.write("Payload QR / deep link sing-box:")
    st.code(import_uri, language="text")

    st.link_button(
        "Buka langsung di sing-box",
        import_uri,
        use_container_width=True,
    )

    if source_mode == "File lokal repo":
        if local_error:
            st.error(local_error)
        elif local_json_obj is not None:
            in_count, out_count, rule_count = metric_counts(local_json_obj)
            c1, c2, c3 = st.columns(3)
            c1.metric("Inbounds", in_count)
            c2.metric("Outbounds", out_count)
            c3.metric("Route rules", rule_count)

            warnings = validate_singbox_config(local_json_obj)
            if warnings:
                st.warning("\n".join(f"- {item}" for item in warnings))
            else:
                st.success("Struktur dasar JSON sing-box terlihat valid.")

            with st.expander("Preview JSON lokal"):
                st.code(local_json_text[:12000], language="json")
                if len(local_json_text) > 12000:
                    st.caption("Preview dipotong sampai 12.000 karakter.")

    if source_mode == "Raw GitHub URL" and validate_remote:
        with st.spinner("Mengecek raw URL..."):
            remote_text, remote_json_obj, remote_error = fetch_remote_json(raw_url)

        if remote_error:
            st.error(remote_error)
        else:
            st.success("Raw URL berhasil diambil dan JSON terbaca.")
            in_count, out_count, rule_count = metric_counts(remote_json_obj)
            c1, c2, c3 = st.columns(3)
            c1.metric("Inbounds", in_count)
            c2.metric("Outbounds", out_count)
            c3.metric("Route rules", rule_count)

            warnings = validate_singbox_config(remote_json_obj)
            if warnings:
                st.warning("\n".join(f"- {item}" for item in warnings))
            else:
                st.success("Struktur dasar JSON sing-box terlihat valid.")

            with st.expander("Preview remote JSON"):
                st.code(remote_text[:12000], language="json")
                if len(remote_text) > 12000:
                    st.caption("Preview dipotong sampai 12.000 karakter.")

with right:
    st.subheader("QR untuk import")

    try:
        qr_img = make_qr_image(import_uri, error_correction=error_correction)
        png_bytes = image_to_png_bytes(qr_img)

        st.image(
            qr_img,
            caption="Scan dari sing-box → Add profile / Scan QR",
            use_container_width=True,
        )

        st.download_button(
            "Download QR PNG",
            data=png_bytes,
            file_name=f"{source_label}-singbox-profile-qr.png",
            mime="image/png",
            use_container_width=True,
        )

        st.download_button(
            "Download payload .txt",
            data=import_uri.encode("utf-8"),
            file_name=f"{source_label}-singbox-profile-link.txt",
            mime="text/plain",
            use_container_width=True,
        )

    except Exception as exc:
        st.error(f"Gagal membuat QR: {exc}")

    st.markdown(
        """
<div class="warn-card">
<b>Jangan scan QR raw JSON penuh.</b><br>
Banyak client sing-box membaca QR sebagai profile link. Jika QR hanya berisi JSON atau link https biasa, biasanya muncul pesan <i>not valid sing-box profile</i>.
</div>
""",
        unsafe_allow_html=True,
    )

st.divider()
st.markdown(
    """
### Cara pasang di repo

1. Simpan file ini sebagai `streamlit_app.py` di root repo.
2. Buat `requirements.txt`:

```txt
streamlit
qrcode[pil]
pillow
requests
```

3. Jalankan lokal:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

4. Untuk Streamlit Cloud, pastikan file JSON sing-box sudah tersedia di repo, misalnya:

```text
output/SingBox/lengkap.json
```

Payload QR yang benar berbentuk:

```text
sing-box://import-remote-profile?url=<RAW_JSON_URL_ENCODED>#<PROFILE_NAME_ENCODED>
```
"""
)

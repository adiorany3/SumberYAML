import base64
import glob
import io
import json
from pathlib import Path
from typing import Optional, Tuple

import qrcode
import streamlit as st
from PIL import Image


REPO_OWNER = "adiorany3"
REPO_NAME = "SumberYAML"
DEFAULT_BRANCH = "main"
DEFAULT_RAW_URL = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/"
    f"{DEFAULT_BRANCH}/output/SingBox/lengkap.json"
)


st.set_page_config(
    page_title="Sing-box JSON QR Generator",
    page_icon="📱",
    layout="wide",
)


CUSTOM_CSS = """
<style>
.block-container {
    padding-top: 1.5rem;
}
.qr-card {
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 18px;
    padding: 1rem;
    background: rgba(255,255,255,.03);
}
.small-note {
    font-size: .9rem;
    opacity: .75;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def normalize_github_url(url: str) -> str:
    """Convert a GitHub blob URL to a raw.githubusercontent.com URL."""
    url = url.strip()

    if "github.com" in url and "/blob/" in url:
        url = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
        url = url.replace("/blob/", "/")

    return url


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


def read_json_from_file(path: str) -> Tuple[str, Optional[dict]]:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        return pretty, parsed
    except Exception:
        return raw, None


def read_uploaded_json(uploaded_file) -> Tuple[str, Optional[dict]]:
    raw = uploaded_file.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        return pretty, parsed
    except Exception:
        return raw, None


def make_qr_image(data: str, error_correction: str = "M") -> Image.Image:
    correction_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }

    qr = qrcode.QRCode(
        version=None,
        error_correction=correction_map.get(error_correction, qrcode.constants.ERROR_CORRECT_M),
        box_size=8,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)

    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def make_download_name(source_name: str, suffix: str = "qr") -> str:
    clean = Path(source_name).stem if source_name else "singbox"
    return f"{clean}-{suffix}.png"


def build_data_uri(text: str) -> str:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"data:application/json;base64,{encoded}"


st.title("📱 Sing-box JSON QR Generator")
st.caption("Tampilkan config sing-box JSON sebagai QR Code dari file lokal, upload JSON, atau raw GitHub URL.")

with st.sidebar:
    st.header("Sumber JSON")

    source_mode = st.radio(
        "Pilih sumber",
        [
            "File lokal repo",
            "Upload JSON",
            "Raw GitHub URL",
            "Tempel manual",
        ],
        index=0,
    )

    st.divider()

    st.header("Mode QR")
    qr_mode = st.radio(
        "Isi QR",
        [
            "Raw GitHub URL / link config",
            "Isi JSON langsung",
            "Data URI base64 JSON",
        ],
        index=0,
        help=(
            "Untuk config besar, mode URL paling aman. "
            "QR raw JSON bisa gagal karena kapasitas QR terbatas."
        ),
    )

    error_correction = st.selectbox(
        "Error correction QR",
        ["L", "M", "Q", "H"],
        index=1,
        help="M seimbang. L menampung teks lebih panjang. H lebih tahan rusak tapi kapasitas lebih kecil.",
    )

    show_preview = st.toggle("Tampilkan preview JSON", value=True)


json_text = ""
json_obj = None
source_label = "singbox"
raw_url = DEFAULT_RAW_URL

if source_mode == "File lokal repo":
    local_files = find_json_files()

    if not local_files:
        st.warning(
            "Belum ada file JSON lokal yang ditemukan. "
            "Pastikan file ada di output/SingBox/*.json atau upload JSON secara manual."
        )
    else:
        selected_file = st.selectbox("Pilih file JSON", local_files)
        json_text, json_obj = read_json_from_file(selected_file)
        source_label = selected_file

        possible_raw = selected_file.replace("\\", "/")
        raw_url = (
            f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/"
            f"{DEFAULT_BRANCH}/{possible_raw}"
        )

elif source_mode == "Upload JSON":
    uploaded = st.file_uploader("Upload file .json", type=["json"])

    if uploaded is not None:
        json_text, json_obj = read_uploaded_json(uploaded)
        source_label = uploaded.name

elif source_mode == "Raw GitHub URL":
    raw_url = st.text_input(
        "URL raw JSON",
        value=DEFAULT_RAW_URL,
        help="Bisa paste URL github.com/.../blob/... nanti otomatis diubah ke raw URL.",
    )
    raw_url = normalize_github_url(raw_url)
    source_label = raw_url.split("/")[-1] or "singbox"
    st.info("Mode ini tidak mengambil isi URL di Streamlit; QR berisi link raw JSON agar bisa dipindai/download oleh client.")

elif source_mode == "Tempel manual":
    json_text = st.text_area(
        "Tempel isi JSON sing-box",
        height=320,
        placeholder='{\n  "log": {"level": "info"},\n  "inbounds": [],\n  "outbounds": []\n}',
    )
    source_label = "manual-json"

    if json_text.strip():
        try:
            json_obj = json.loads(json_text)
            json_text = json.dumps(json_obj, indent=2, ensure_ascii=False)
        except Exception:
            json_obj = None


left, right = st.columns([1.1, 0.9], gap="large")

with left:
    st.subheader("Config")

    if source_mode != "Raw GitHub URL" and json_text:
        size_bytes = len(json_text.encode("utf-8"))
        st.write(f"Ukuran JSON: **{size_bytes:,} bytes**")

        if json_obj is not None:
            inbound_count = len(json_obj.get("inbounds", [])) if isinstance(json_obj, dict) else 0
            outbound_count = len(json_obj.get("outbounds", [])) if isinstance(json_obj, dict) else 0
            route_count = len(json_obj.get("route", {}).get("rules", [])) if isinstance(json_obj, dict) else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Inbounds", inbound_count)
            c2.metric("Outbounds", outbound_count)
            c3.metric("Route rules", route_count)
        else:
            st.warning("Isi belum valid JSON, tetapi tetap bisa dibuat QR sebagai teks mentah.")

        if show_preview:
            st.code(json_text[:12000], language="json")
            if len(json_text) > 12000:
                st.caption("Preview dipotong sampai 12.000 karakter agar aplikasi tetap ringan.")

    elif source_mode == "Raw GitHub URL":
        st.write("QR akan berisi link berikut:")
        st.code(raw_url, language="text")

    else:
        st.info("Pilih/upload/tempel JSON terlebih dahulu.")

with right:
    st.subheader("QR Code")

    qr_payload = ""
    suffix = "qr"

    if qr_mode == "Raw GitHub URL / link config":
        if source_mode == "Raw GitHub URL":
            qr_payload = raw_url
        elif source_mode == "File lokal repo" and source_label:
            qr_payload = raw_url
        else:
            qr_payload = ""
            st.warning("Mode URL hanya otomatis untuk file lokal repo atau raw GitHub URL.")
        suffix = "url-qr"

    elif qr_mode == "Isi JSON langsung":
        qr_payload = json_text.strip()
        suffix = "json-qr"

    elif qr_mode == "Data URI base64 JSON":
        if json_text.strip():
            qr_payload = build_data_uri(json_text.strip())
        suffix = "data-uri-qr"

    if qr_payload:
        payload_size = len(qr_payload.encode("utf-8"))
        st.write(f"Ukuran payload QR: **{payload_size:,} bytes**")

        if payload_size > 2500 and qr_mode != "Raw GitHub URL / link config":
            st.warning(
                "Payload QR cukup besar. Banyak scanner/client gagal membaca QR besar. "
                "Disarankan pakai mode Raw GitHub URL / link config."
            )

        try:
            qr_img = make_qr_image(qr_payload, error_correction=error_correction)
            png_bytes = image_to_png_bytes(qr_img)

            st.image(qr_img, caption="QR Code", use_container_width=True)
            st.download_button(
                "Download QR PNG",
                data=png_bytes,
                file_name=make_download_name(source_label, suffix=suffix),
                mime="image/png",
                use_container_width=True,
            )

            with st.expander("Lihat payload QR"):
                st.code(qr_payload[:8000], language="text")
                if len(qr_payload) > 8000:
                    st.caption("Payload dipotong sampai 8.000 karakter pada preview.")

        except Exception as exc:
            st.error(f"Gagal membuat QR: {exc}")
            st.info(
                "Coba ganti mode ke Raw GitHub URL / link config, "
                "atau turunkan error correction ke L."
            )
    else:
        st.info("Belum ada payload QR yang bisa dibuat.")


st.divider()
st.markdown(
    """
### Cara pakai di repo GitHub

1. Simpan file ini sebagai `streamlit_app.py` di root repo.
2. Buat file `requirements.txt` berisi:

```txt
streamlit
qrcode[pil]
pillow
```

3. Jalankan lokal:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

4. Kalau deploy ke Streamlit Cloud, pastikan repo berisi:

```text
streamlit_app.py
requirements.txt
output/SingBox/*.json
```

Mode paling aman untuk config sing-box besar adalah **Raw GitHub URL / link config**, karena QR langsung berisi link ke file JSON, bukan seluruh isi JSON.
"""
)

# SumberYAML OpenClash Generator

Struktur repository ini dibuat mengikuti pola `adiorany3/SumberYAML`.

## Struktur utama

```text
.github/workflows/
  keep-streamlit-awake.yml
  update-openclash.yml
output/
  Alive/
  AllValid/
  BestPing/
  Country/
  Duplicate/
  Invalid/
  Raw/
  Renamed/
  Txt/
  Yaml/
scripts/
  generate_configs.py
  generate_configs_basic.py
tools/
  telegram_notify.py
README.md
requirements.txt
streamlit_app.py
telegram_github_dispatch_bot.py
telegram_openclash_alive.py
telegram_openclash_bot.py
```

## Catatan fix OpenClash

Nama proxy sudah dibuat lebih aman untuk OpenClash:

- Emoji bendera dikonversi menjadi kode negara, contoh `🇸🇬` menjadi `SG`.
- Karakter kontrol, zero-width character, quote, koma, bracket YAML, pipe, backtick, dan simbol bermasalah dibersihkan.
- Nama kosong otomatis diganti menjadi `Proxy`.
- Nama duplikat otomatis diberi nomor.
- Output YAML dibuat lebih aman dengan quote pada nilai string.

## Cara pakai di GitHub

1. Upload semua isi folder ini ke root repository GitHub.
2. Pastikan file `.github/workflows/update-openclash.yml` ikut terupload.
3. Masuk ke tab **Actions**.
4. Jalankan workflow **Update OpenClash** secara manual, atau tunggu jadwal otomatis setiap 6 jam.
5. Hasil utama akan dibuat di:

```text
output/lengkap.yaml
```

## Secrets GitHub yang disarankan

Untuk notifikasi Telegram, tambahkan repository secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Untuk Streamlit bot/dispatch, gunakan secrets/environment sesuai kebutuhan:

```text
GITHUB_TOKEN
GITHUB_REPOSITORY
GITHUB_REF
GITHUB_WORKFLOW_FILE
TELEGRAM_BOT_TOKEN
TELEGRAM_ALLOWED_CHAT_ID
```

## Menjalankan lokal

```bash
pip install -r requirements.txt
python telegram_openclash_alive.py --mode update --enable-proxy-test true --filter-alive-only true
```

Untuk Streamlit:

```bash
streamlit run streamlit_app.py
```
## Catatan Validasi OpenClash

- Nama proxy otomatis dibersihkan dari karakter yang berpotensi membuat OpenClash gagal import.
- Akun VMess/VLESS dengan UUID kosong atau tidak valid otomatis dihapus/dilewati satu akun tersebut.
- Akun yang dilewati dicatat di `output/Invalid/*.csv` dengan alasan `uuid kosong` atau `uuid tidak valid`.



## Update tambahan

- Sumber VMess tambahan sudah ditambahkan jika belum ada:
  `https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vmess_configs.txt`
- `BEST_PING_TOP_N` default diubah menjadi `5`.
- `BEST_PING_COUNTRY_FILTER` default `ID`, jadi Top 5 diambil dari proxy Indonesia yang alive.
- Hasil 5 akun alive dengan ping terbaik otomatis dimasukkan ke grup OpenClash:
  `URL-TEST TOP 5 INDONESIA`
- Grup tersebut memakai `type: url-test`, bukan `load-balance`, agar OpenClash otomatis memilih node tercepat dari 5 akun terbaik.
- Nama proxy tetap dibersihkan agar aman untuk OpenClash, dan UUID VMess/VLESS tidak valid tetap dihapus satu akun.


### URL-Test Top 5 Indonesia di `lengkap.yaml`

Generator sekarang memasukkan grup berikut langsung ke `output/lengkap.yaml`:

```yaml
- name: URL-TEST TOP 5 INDONESIA
  type: url-test
```

Grup ini diambil dari 5 proxy alive tercepat dengan `country == ID`. Jika tidak ada proxy Indonesia yang alive dan `BEST_PING_FALLBACK_GLOBAL=true`, script akan fallback ke Top 5 global agar grup tidak kosong.

### Update Best Ping Group

- Grup Best Ping / `URL-TEST TOP 5 INDONESIA` sekarang hanya berisi nama proxy hasil ping terbaik.
- `DIRECT` dan `REJECT` tidak dimasukkan ke group `type: url-test`.
- `DIRECT` dan `REJECT` hanya otomatis ditambahkan ke group `type: select`, yaitu group utama `PROXY`.

## Update stabilitas terbaru

Fitur tambahan yang sudah dimasukkan:

- `output/lengkap.yaml` tetap menjadi output utama untuk OpenClash.
- `output/lengkap_alive.yaml` dibuat otomatis dan berisi akun alive/layak pakai.
- Batas delay default `MAX_DELAY_MS=3000`, sehingga akun alive yang terlalu lambat tidak diprioritaskan ke output final dan Best Ping.
- `output/Source/source_status.csv` mencatat status setiap URL sumber: berhasil/gagal, HTTP status, jumlah link VMess/VLESS/Trojan yang ditemukan, dan pesan error.
- `blacklist.txt` tersedia untuk membuang akun berdasarkan kata/frasa tertentu.
- Grup `FALLBACK` ditambahkan agar pilihan utama tetap punya cadangan selain grup URL-Test.
- Grup kosong otomatis tidak ditulis, kecuali grup `PROXY` yang tetap memuat `DIRECT` dan `REJECT`.
- `DIRECT` dan `REJECT` hanya ada pada grup `type: select`, bukan pada `url-test`, `fallback`, atau Best Ping.
- Validasi YAML dijalankan sebelum commit melalui `scripts/validate_openclash_outputs.py`.

### File output penting

```text
output/lengkap.yaml
output/lengkap_alive.yaml
output/Alive/check_result.csv
output/Alive/summary_alive.json
output/BestPing/top5_indonesia_ping.csv
output/BestPing/top5_indonesia_ping.yaml
output/Source/source_status.csv
output/Validation/validation_report.json
```

### Pengaturan environment penting

```text
BEST_PING_TOP_N=5
BEST_PING_COUNTRY_FILTER=ID
BEST_PING_URL_TEST_NAME=URL-TEST TOP 5 INDONESIA
MAX_DELAY_MS=3000
FILTER_MAX_DELAY_FOR_OUTPUT=true
BLACKLIST_FILE=blacklist.txt
```

### Cara memakai blacklist

Isi `blacklist.txt` dengan satu kata/frasa per baris. Baris yang diawali `#` akan diabaikan.

Contoh:

```text
expired
test
ads
```

Jika nama, raw link, host, SNI, atau server mengandung kata tersebut, satu akun/proxy akan dilewati dan dicatat di `output/Invalid/*.csv`.

### Validasi manual

```bash
python scripts/validate_openclash_outputs.py output/lengkap.yaml output/lengkap_alive.yaml
```

Jika validasi gagal, workflow GitHub Actions akan berhenti sebelum commit agar file rusak tidak masuk repository.

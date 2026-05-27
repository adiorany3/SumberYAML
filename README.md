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
- Batas delay default dilonggarkan menjadi `MAX_DELAY_MS=8000`. Filter delay final default nonaktif agar akun VMess/VLESS/Trojan tidak habis tersaring.
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
MAX_DELAY_MS=8000
FILTER_MAX_DELAY_FOR_OUTPUT=false
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

## Optimasi tambahan terbaru

Fitur berikut sudah ditambahkan untuk memperingan OpenClash dan membuat update lebih stabil:

1. **`output/lite.yaml`**
   - File ringan untuk router kecil.
   - Isi default: Top 5 Indonesia, Top 10 global alive, `FALLBACK`, dan rule dasar.
   - Cocok dipakai jika `lengkap.yaml` terlalu berat.

2. **Dedup fingerprint lebih kuat**
   - Duplikat tidak hanya dilihat dari nama/link mentah.
   - Fingerprint dibuat dari identitas akun seperti protocol, UUID/password, port, network, SNI, host, path, TLS/security, dan flow.
   - Hasil fingerprint dicatat di laporan CSV.

3. **Ranking stabilitas sederhana**
   - Ranking Best Ping sekarang memakai `rank_score`, bukan delay mentah saja.
   - Hasil TCP fallback diberi penalti agar tidak mengalahkan node yang benar-benar lolos URL delay test.
   - Fallback global dari filter negara juga diberi penalti.

4. **Cache source**
   - Sumber yang berhasil diambil akan disimpan di:
     `output/Cache/sources/`
   - Jika suatu URL sumber sedang down, generator mencoba memakai cache terakhir agar output tidak langsung kosong.
   - Status cache terlihat di:
     `output/Source/source_status.csv`

5. **Notifikasi Telegram ringkas**
   - Setelah workflow selesai, Telegram mengirim ringkasan: total valid, alive, dead, Lite YAML, invalid UUID, blacklist, source cache, validasi YAML, dan Top 5.
   - File yang dikirim juga mencakup `lengkap.yaml`, `lengkap_alive.yaml`, `lite.yaml`, laporan ping, BestPing, dan source status.

6. **Rules custom terpisah**
   - Rule tambahan bisa ditulis di:
     `rules/custom_rules.yaml`
   - Generator akan memasukkannya sebelum rule akhir `MATCH,PROXY`.

### Environment tambahan

```text
SOURCE_CACHE_ENABLE=true
SOURCE_CACHE_DIR=output/Cache/sources
LITE_OUTPUT_FILE=lite.yaml
LITE_GLOBAL_TOP_N=10
LITE_MAX_TOTAL=25
CUSTOM_RULES_FILE=rules/custom_rules.yaml
RANK_TCP_FALLBACK_PENALTY=300
RANK_GLOBAL_FALLBACK_PENALTY=1000
```

### Validasi manual terbaru

```bash
python scripts/validate_openclash_outputs.py output/lengkap.yaml output/lengkap_alive.yaml output/lite.yaml
```


Sumber tambahan aktif: `Epodonios/v2ray-configs/All_Configs_Sub.txt`.


## STRICT ALIVE ONLY

Mode ini memastikan file yang dipakai OpenClash hanya berisi akun yang lolos URL delay test Mihomo beberapa ronde.

Default workflow sekarang memakai mode balanced agar akun tidak habis tersaring:

```env
STRICT_ALIVE_ONLY=true
TEST_ROUNDS=2
REQUIRE_SUCCESS_ROUNDS=1
STRICT_MAX_DELAY_MS=8000
TCP_FALLBACK=true
DISABLE_TCP_ONLY_OUTPUT=false
STRICT_FALLBACK_TO_ALIVE=true
STRICT_FALLBACK_TO_VALID=true
```

Jika hasil strict kosong, generator otomatis turun ke fallback alive/TCP, lalu terakhir semua akun valid format agar output tidak kosong.

Output tambahan:

```text
output/strict_alive.yaml
output/Strict/strict_alive.csv
output/Strict/strict_alive_proxies.yaml
output/Strict/summary_strict_alive.json
```

Gunakan `output/strict_alive.yaml` di OpenClash jika ingin hasil yang sudah diprioritaskan dari akun yang lolos test. Pada mode balanced, file ini tetap diisi dari fallback jika strict 0 agar OpenClash tidak kosong.

## Info GitHub Actions di Streamlit Online

Streamlit sekarang menampilkan panel **Status GitHub Actions**.

Fungsinya:

- Menampilkan status workflow terbaru: queued, in_progress, completed, success, atau failure.
- Jika workflow sedang berjalan, halaman akan auto-refresh setiap 60 detik.
- Jika workflow selesai sukses, panel menampilkan ringkasan:
  - total valid,
  - alive/dead/untested,
  - strict alive,
  - jumlah node lite.yaml,
  - Best Ping Indonesia,
  - status source/cache,
  - status validasi YAML.
- Jika workflow gagal, panel memberi info gagal dan link ke halaman log GitHub Actions.

Setting opsional di Streamlit Secrets:

```toml
SHOW_WORKFLOW_STATUS_PANEL = "true"
WORKFLOW_STATUS_REFRESH_SECONDS = "60"
```

Agar panel ini bisa membaca status workflow, pastikan Streamlit Secrets sudah berisi akses GitHub:

```toml
GITHUB_TOKEN = "ghp_xxx"
GITHUB_REPOSITORY = "owner/repo"
GITHUB_REF = "main"
GITHUB_WORKFLOW_FILE = "update-openclash.yml"
```


### Status GitHub Actions hanya di Admin

Panel **Status GitHub Actions** tidak tampil di halaman publik. Panel ini hanya muncul setelah membuka halaman admin dan login:

```text
https://nama-app.streamlit.app/?admin=1
```

Secrets yang berhubungan:

```toml
SHOW_WORKFLOW_STATUS_PANEL = "true"
WORKFLOW_STATUS_REFRESH_SECONDS = "60"
ADMIN_PASSWORD = "password_admin_anda"
```

## Fallback agar akun tidak kosong

Versi ini menambahkan mekanisme reuse output sebelumnya.

Jika semua sumber gagal, tidak ada akun raw baru, atau hasil parsing valid kosong, workflow akan memakai kembali folder `output` dari commit sebelumnya. Dengan begitu file berikut tidak menjadi kosong:

- `output/lengkap.yaml`
- `output/lengkap_alive.yaml`
- `output/strict_alive.yaml`
- `output/lite.yaml`

Jika raw source saat ini sama persis dengan update sebelumnya, workflow juga mempersingkat proses dengan reuse output lama. Laporan fallback tersedia di:

```text
output/Reuse/reuse_previous_output.json
```

Environment terkait:

```env
USE_PREVIOUS_OUTPUT_IF_EMPTY=true
FAST_REUSE_WHEN_NO_SOURCE_CHANGE=true
PREVIOUS_OUTPUT_DIR=.previous_output
```

Jika ingin selalu test ulang walaupun source belum berubah, ubah:

```env
FAST_REUSE_WHEN_NO_SOURCE_CHANGE=false
```


## Group URL-Test Per Negara

Default terbaru: group `URL-TEST <NEGARA>` tidak dimasukkan ke `lengkap.yaml`, `lengkap_alive.yaml`, `strict_alive.yaml`, dan `lite.yaml` agar jumlah proxy-group tidak terlalu banyak di OpenClash.

Jika ingin mengaktifkan kembali group per negara, isi env/Secrets berikut:

```env
ENABLE_COUNTRY_URL_TEST_GROUPS=true
```

Folder `output/Country/` dan `summary_country.csv` tetap dibuat sebagai laporan/arsip, tetapi tidak otomatis menjadi group di file utama saat opsi ini `false`.

## Optimasi responsivitas terbaru

Versi ini menambahkan mode pemilihan akun yang lebih responsif, bukan hanya sekadar hidup.

Output baru:

```text
output/fast.yaml
output/Fast/fast.csv
output/Fast/fast_proxies.yaml
output/Fast/summary_fast.json
```

Perubahan penting:

- `fast.yaml` berisi akun paling responsif untuk penggunaan harian.
- Best Ping sekarang memakai `responsive_score`, yaitu gabungan dari delay rata-rata, jitter, success-rate, penalti TCP fallback, dan penalti fallback global.
- Grup baru `FALLBACK CEPAT` ditambahkan untuk akun stabil/cepat.
- `URL-TEST GABUNGAN` dibatasi maksimal 30 akun agar OpenClash tidak berat.
- `url-test` memakai default lebih responsif:
  `interval=120`, `tolerance=30`, `lazy=false`.
- Konfigurasi performa Mihomo/OpenClash ditambahkan:
  `unified-delay`, `tcp-concurrent`, `keep-alive-idle`, dan `keep-alive-interval`.

Environment baru:

```env
URL_TEST_INTERVAL=120
URL_TEST_TOLERANCE=30
URL_TEST_LAZY=false
RESPONSIVE_MAX_AVG_DELAY_MS=8000
RESPONSIVE_MAX_JITTER_MS=5000
RESPONSIVE_MIN_SUCCESS_RATE=0.50
RESPONSIVE_TOP_N=15
RESPONSIVE_COMBINED_MAX=30
RESPONSIVE_JITTER_WEIGHT=0.35
RESPONSIVE_FAILURE_PENALTY=1500
FAST_OUTPUT_FILE=fast.yaml
FAST_MAX_TOTAL=20
FAST_FALLBACK_NAME=FALLBACK CEPAT
ENABLE_FAST_FALLBACK_GROUP=true
ENABLE_PERFORMANCE_OPTIONS=true
```

Rekomendasi pemakaian OpenClash:

```text
output/fast.yaml          = paling ringan dan responsif
output/lite.yaml          = ringan dengan tambahan Top Global
output/lengkap_alive.yaml = akun alive lebih banyak
output/lengkap.yaml       = output utama paling lengkap
```

Validasi manual lengkap:

```bash
python scripts/validate_openclash_outputs.py output/lengkap.yaml output/lengkap_alive.yaml output/strict_alive.yaml output/lite.yaml output/fast.yaml
```

## Profil Akun Stabil Berdasarkan Kebutuhan

Versi ini juga membuat pilihan akun paling stabil untuk beberapa kebutuhan pemakaian:

```text
output/gaming.yaml
output/social_media.yaml
output/streaming.yaml
output/working.yaml
output/general.yaml
output/Categories/gaming.csv
output/Categories/social_media.csv
output/Categories/streaming.csv
output/Categories/working.csv
output/Categories/general.csv
output/Categories/summary_usage_profiles.json
```

Group yang ditambahkan ke file utama:

```text
GAMING STABIL
SOCIAL MEDIA STABIL
STREAMING STABIL
WORKING STABIL
GENERAL STABIL
```

Skor setiap kategori berbeda:

- `GAMING STABIL`: memprioritaskan jitter rendah dan respons stabil.
- `SOCIAL MEDIA STABIL`: memprioritaskan respons awal cepat.
- `STREAMING STABIL`: memprioritaskan koneksi yang tidak sering timeout dan jitter rendah.
- `WORKING STABIL`: memprioritaskan success-rate tinggi untuk meeting, remote work, dan akses kerja.
- `GENERAL STABIL`: skor seimbang untuk penggunaan harian.

Environment tambahan:

```env
ENABLE_USAGE_PROFILE_GROUPS=true
USAGE_PROFILE_TOP_N=10
USAGE_PROFILE_MAX_TOTAL=15
USAGE_PROFILE_GROUP_TYPE=fallback
USAGE_PROFILE_INTERVAL=120
USAGE_PROFILE_LAZY=false
USAGE_PROFILE_OUTPUT_ROOT=true
```

Catatan: sumber akun publik tidak menyediakan data bandwidth dan packet loss asli. Karena itu kategori ini dihitung dari data yang tersedia, yaitu delay rata-rata, jitter, success-rate, max delay, dan penalti TCP-only.

Validasi manual lengkap:

```bash
python scripts/validate_openclash_outputs.py \
  output/lengkap.yaml \
  output/lengkap_alive.yaml \
  output/strict_alive.yaml \
  output/lite.yaml \
  output/fast.yaml \
  output/gaming.yaml \
  output/social_media.yaml \
  output/streaming.yaml \
  output/working.yaml \
  output/general.yaml
```

## Rules otomatis dan custom

Generator sekarang mendukung rule otomatis untuk profil pemakaian:

- `GAMING STABIL`
- `SOCIAL MEDIA STABIL`
- `STREAMING STABIL`
- `WORKING STABIL`
- `GENERAL STABIL`

Rule bawaan akan otomatis diarahkan ke group profil yang tersedia. Jika suatu output tidak memiliki group profil tertentu, rule ke group tersebut tidak akan ditulis agar OpenClash tidak error.

File rule yang bisa diedit:

```text
rules/default_rules.yaml
rules/custom_rules.yaml
```

Gunakan `rules/custom_rules.yaml` untuk rule pribadi. Contoh:

```yaml
- DOMAIN-SUFFIX,example.com,PROXY
- DOMAIN-SUFFIX,example.co.id,DIRECT
- DOMAIN-KEYWORD,ads,REJECT
```

Pengaturan lewat environment variable:

```env
ENABLE_USAGE_RULES=true
ENABLE_DEFAULT_RULES=true
CUSTOM_RULES_FILE=rules/custom_rules.yaml
DEFAULT_RULES_FILE=rules/default_rules.yaml
```

Jika ingin mematikan rule profil otomatis:

```env
ENABLE_USAGE_RULES=false
```

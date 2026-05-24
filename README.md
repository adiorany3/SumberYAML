# Auto Update Protocol Configs

Project ini dibuat untuk dijalankan otomatis di GitHub menggunakan GitHub Actions cron.

## Output otomatis

```text
output/Yaml/vmess.yaml
output/Yaml/vless.yaml
output/Yaml/trojan.yaml

output/Txt/vmess.txt
output/Txt/vless.txt
output/Txt/trojan.txt

output/Raw/vmess.txt
output/Raw/vless.txt
output/Raw/trojan.txt

output/Invalid/vmess_invalid.csv
output/Invalid/vless_invalid.csv
output/Invalid/trojan_invalid.csv
output/summary_protocol.csv
```

## Perbedaan output

### `output/Yaml`

Berisi format YAML/OpenClash.

### `output/Txt`

Berisi format protocol asli, bukan YAML:

```text
vmess://...
vless://...
trojan://...
```

Yang diubah hanya bagian `server` sesuai pengaturan override di script.

Default server override:

```python
VMESS_SERVER_OVERRIDE = "104.17.3.81"
VLESS_SERVER_OVERRIDE = "104.17.3.81"
TROJAN_SERVER_OVERRIDE = "104.17.3.81"
```

## Cara upload ke GitHub

1. Buat repository baru di GitHub.
2. Upload semua isi ZIP ini ke repository.
3. Pastikan struktur file seperti ini:

```text
.github/workflows/auto-update.yml
scripts/generate_configs.py
requirements.txt
README.md
.gitignore
```

4. Buka tab **Actions**.
5. Aktifkan GitHub Actions jika diminta.
6. Workflow akan jalan otomatis setiap 6 jam.

## Menjalankan manual

Di GitHub:

1. Buka tab **Actions**.
2. Pilih workflow **Auto Update Config Files**.
3. Klik **Run workflow**.

Di lokal:

```bash
pip install -r requirements.txt
python scripts/generate_configs.py
```

## Mengubah jadwal cron

Edit file:

```text
.github/workflows/auto-update.yml
```

Default:

```yaml
- cron: "0 */6 * * *"
```

Contoh setiap 1 jam:

```yaml
- cron: "0 * * * *"
```

Contoh setiap hari jam 00:00 UTC:

```yaml
- cron: "0 0 * * *"
```

## Link raw setelah masuk GitHub

Ganti `USERNAME` dan `NAMA_REPO` sesuai repo Anda:

```text
https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Yaml/vmess.yaml
https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Yaml/vless.yaml
https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Yaml/trojan.yaml

https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Txt/vmess.txt
https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Txt/vless.txt
https://raw.githubusercontent.com/USERNAME/NAMA_REPO/main/output/Txt/trojan.txt
```

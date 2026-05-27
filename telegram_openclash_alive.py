import base64, binascii, csv, json, random, re, os, sys, time, shutil, socket, gzip, tarfile, zipfile, subprocess, tempfile, argparse, hashlib
import unicodedata
import uuid as uuidlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, urlunparse, quote
import requests

TIMEOUT = 10
OUTPUT_DIR = Path('output')
ONLY_PORT_443 = True
INCLUDE_PROXIES_HEADER = True
VMESS_SERVER_OVERRIDE = '104.17.3.81'
VLESS_SERVER_OVERRIDE = '104.17.3.81'
TROJAN_SERVER_OVERRIDE = '104.17.3.81'
PROTOCOLS = ['vmess', 'vless', 'trojan']
OPENCLASH_OUTPUT_FILE = 'lengkap.yaml'
URL_TEST_URL = 'http://www.gstatic.com/generate_204'
URL_TEST_INTERVAL = 300
URL_TEST_TOLERANCE = 50
FETCH_WORKERS = 10
RUN_MODE = os.getenv('RUN_MODE', 'update').strip().lower() or 'update'

# Top 5 tercepat dari hasil test delay.
# Catatan: lokasi test mengikuti tempat workflow/script dijalankan.
# Jika ingin benar-benar dari Indonesia, jalankan workflow di runner/VPS Indonesia.
BEST_PING_TOP_N = int(os.getenv('BEST_PING_TOP_N', '5'))
BEST_PING_COUNTRY_FILTER = os.getenv('BEST_PING_COUNTRY_FILTER', 'ID').strip().upper()
BEST_PING_URL_TEST_NAME = os.getenv('BEST_PING_URL_TEST_NAME', 'URL-TEST TOP 5 INDONESIA')
BEST_PING_BALANCE_ENABLE_RAW = os.getenv('BEST_PING_BALANCE_ENABLE', 'true')
BEST_PING_BALANCE_NAME = os.getenv('BEST_PING_BALANCE_NAME', BEST_PING_URL_TEST_NAME)
BEST_PING_BALANCE_STRATEGY = os.getenv('BEST_PING_BALANCE_STRATEGY', 'round-robin')

def env_bool(name, default=False):
    value = str(os.getenv(name, str(default))).strip().lower()
    return value in ['1', 'true', 'yes', 'y', 'on']

BEST_PING_BALANCE_ENABLE = str(BEST_PING_BALANCE_ENABLE_RAW).strip().lower() in ['1', 'true', 'yes', 'y', 'on']
BEST_PING_FALLBACK_GLOBAL = env_bool('BEST_PING_FALLBACK_GLOBAL', True)
MAX_DELAY_MS = int(os.getenv('MAX_DELAY_MS', '8000'))
FILTER_MAX_DELAY_FOR_OUTPUT = env_bool('FILTER_MAX_DELAY_FOR_OUTPUT', False)
# Default false agar lengkap.yaml/lengkap_alive.yaml tidak kebanyakan group per negara.
ENABLE_COUNTRY_URL_TEST_GROUPS = env_bool('ENABLE_COUNTRY_URL_TEST_GROUPS', False)

# STRICT ALIVE ONLY: hanya proxy yang lolos URL delay test Mihomo beberapa ronde
# yang boleh masuk output strict/lite/best ping saat mode ini aktif.
STRICT_ALIVE_ONLY = env_bool('STRICT_ALIVE_ONLY', True)
# Default dibuat tidak terlalu ketat agar VMess/VLESS/Trojan tidak habis tersaring.
# Jika ingin benar-benar ketat, atur TEST_ROUNDS=3 dan REQUIRE_SUCCESS_ROUNDS=3 di GitHub Secrets/Workflow.
TEST_ROUNDS = max(1, int(os.getenv('TEST_ROUNDS', '2')))
REQUIRE_SUCCESS_ROUNDS = max(1, int(os.getenv('REQUIRE_SUCCESS_ROUNDS', str(TEST_ROUNDS))))
if REQUIRE_SUCCESS_ROUNDS > TEST_ROUNDS:
    REQUIRE_SUCCESS_ROUNDS = TEST_ROUNDS
STRICT_MAX_DELAY_MS = int(os.getenv('STRICT_MAX_DELAY_MS', str(MAX_DELAY_MS)))
STRICT_OUTPUT_FILE = os.getenv('STRICT_OUTPUT_FILE', 'strict_alive.yaml').strip() or 'strict_alive.yaml'
DISABLE_TCP_ONLY_OUTPUT = env_bool('DISABLE_TCP_ONLY_OUTPUT', False)
STRICT_FALLBACK_TO_ALIVE = env_bool('STRICT_FALLBACK_TO_ALIVE', True)
STRICT_FALLBACK_TO_VALID = env_bool('STRICT_FALLBACK_TO_VALID', True)

BLACKLIST_FILE = os.getenv('BLACKLIST_FILE', 'blacklist.txt').strip()
SOURCE_CACHE_ENABLE = env_bool('SOURCE_CACHE_ENABLE', True)
SOURCE_CACHE_DIR = Path(os.getenv('SOURCE_CACHE_DIR', 'output/Cache/sources'))
LITE_OUTPUT_FILE = os.getenv('LITE_OUTPUT_FILE', 'lite.yaml').strip() or 'lite.yaml'
LITE_GLOBAL_TOP_N = int(os.getenv('LITE_GLOBAL_TOP_N', '10'))
LITE_MAX_TOTAL = int(os.getenv('LITE_MAX_TOTAL', '25'))
CUSTOM_RULES_FILE = os.getenv('CUSTOM_RULES_FILE', 'rules/custom_rules.yaml').strip()
RANK_TCP_FALLBACK_PENALTY = int(os.getenv('RANK_TCP_FALLBACK_PENALTY', '300'))
RANK_GLOBAL_FALLBACK_PENALTY = int(os.getenv('RANK_GLOBAL_FALLBACK_PENALTY', '1000'))
SOURCE_STATUS_ROWS = []

# Reuse output sebelumnya agar hasil tidak kosong dan update lebih cepat
# jika semua sumber kosong/tidak ada akun baru. PREVIOUS_OUTPUT_DIR diisi workflow
# dari folder output sebelum proses generate berjalan.
USE_PREVIOUS_OUTPUT_IF_EMPTY = env_bool('USE_PREVIOUS_OUTPUT_IF_EMPTY', True)
FAST_REUSE_WHEN_NO_SOURCE_CHANGE = env_bool('FAST_REUSE_WHEN_NO_SOURCE_CHANGE', True)
PREVIOUS_OUTPUT_DIR = os.getenv('PREVIOUS_OUTPUT_DIR', '').strip()

ENABLE_PROXY_TEST = env_bool('ENABLE_PROXY_TEST', True)
FILTER_ALIVE_ONLY = env_bool('FILTER_ALIVE_ONLY', True)
CHECK_TEST_URL = os.getenv('CHECK_TEST_URL', URL_TEST_URL)
CHECK_TIMEOUT_MS = int(os.getenv('CHECK_TIMEOUT_MS', '5000'))
CHECK_WORKERS = int(os.getenv('CHECK_WORKERS', '20'))
MIHOMO_API_HOST = os.getenv('MIHOMO_API_HOST', '127.0.0.1')
MIHOMO_API_PORT = int(os.getenv('MIHOMO_API_PORT', '9092'))
MIHOMO_DOWNLOAD = env_bool('MIHOMO_DOWNLOAD', True)
MIHOMO_BIN = os.getenv('MIHOMO_BIN', '').strip()
TCP_FALLBACK = env_bool('TCP_FALLBACK', True)
WRITE_ALL_VALID_BACKUP = env_bool('WRITE_ALL_VALID_BACKUP', True)
COUNTRY_OUTPUT_DIR = 'Country'
UNKNOWN_COUNTRY_CODE = 'UNKNOWN'
COUNTRY_NAMES = {
    'AD': 'Andorra', 'AE': 'United Arab Emirates', 'AF': 'Afghanistan', 'AG': 'Antigua and Barbuda',
    'AI': 'Anguilla', 'AL': 'Albania', 'AM': 'Armenia', 'AO': 'Angola', 'AQ': 'Antarctica',
    'AR': 'Argentina', 'AS': 'American Samoa', 'AT': 'Austria', 'AU': 'Australia', 'AW': 'Aruba',
    'AX': 'Aland Islands', 'AZ': 'Azerbaijan', 'BA': 'Bosnia and Herzegovina', 'BB': 'Barbados',
    'BD': 'Bangladesh', 'BE': 'Belgium', 'BF': 'Burkina Faso', 'BG': 'Bulgaria', 'BH': 'Bahrain',
    'BI': 'Burundi', 'BJ': 'Benin', 'BL': 'Saint Barthelemy', 'BM': 'Bermuda', 'BN': 'Brunei',
    'BO': 'Bolivia', 'BQ': 'Caribbean Netherlands', 'BR': 'Brazil', 'BS': 'Bahamas', 'BT': 'Bhutan',
    'BV': 'Bouvet Island', 'BW': 'Botswana', 'BY': 'Belarus', 'BZ': 'Belize', 'CA': 'Canada',
    'CC': 'Cocos Islands', 'CD': 'Congo Kinshasa', 'CF': 'Central African Republic', 'CG': 'Congo Brazzaville',
    'CH': 'Switzerland', 'CI': 'Cote d Ivoire', 'CK': 'Cook Islands', 'CL': 'Chile', 'CM': 'Cameroon',
    'CN': 'China', 'CO': 'Colombia', 'CR': 'Costa Rica', 'CU': 'Cuba', 'CV': 'Cape Verde',
    'CW': 'Curacao', 'CX': 'Christmas Island', 'CY': 'Cyprus', 'CZ': 'Czech Republic', 'DE': 'Germany',
    'DJ': 'Djibouti', 'DK': 'Denmark', 'DM': 'Dominica', 'DO': 'Dominican Republic', 'DZ': 'Algeria',
    'EC': 'Ecuador', 'EE': 'Estonia', 'EG': 'Egypt', 'EH': 'Western Sahara', 'ER': 'Eritrea',
    'ES': 'Spain', 'ET': 'Ethiopia', 'FI': 'Finland', 'FJ': 'Fiji', 'FK': 'Falkland Islands',
    'FM': 'Micronesia', 'FO': 'Faroe Islands', 'FR': 'France', 'GA': 'Gabon', 'GB': 'United Kingdom',
    'GD': 'Grenada', 'GE': 'Georgia', 'GF': 'French Guiana', 'GG': 'Guernsey', 'GH': 'Ghana',
    'GI': 'Gibraltar', 'GL': 'Greenland', 'GM': 'Gambia', 'GN': 'Guinea', 'GP': 'Guadeloupe',
    'GQ': 'Equatorial Guinea', 'GR': 'Greece', 'GS': 'South Georgia and South Sandwich Islands',
    'GT': 'Guatemala', 'GU': 'Guam', 'GW': 'Guinea Bissau', 'GY': 'Guyana', 'HK': 'Hong Kong',
    'HM': 'Heard Island and McDonald Islands', 'HN': 'Honduras', 'HR': 'Croatia', 'HT': 'Haiti',
    'HU': 'Hungary', 'ID': 'Indonesia', 'IE': 'Ireland', 'IL': 'Israel', 'IM': 'Isle of Man',
    'IN': 'India', 'IO': 'British Indian Ocean Territory', 'IQ': 'Iraq', 'IR': 'Iran', 'IS': 'Iceland',
    'IT': 'Italy', 'JE': 'Jersey', 'JM': 'Jamaica', 'JO': 'Jordan', 'JP': 'Japan', 'KE': 'Kenya',
    'KG': 'Kyrgyzstan', 'KH': 'Cambodia', 'KI': 'Kiribati', 'KM': 'Comoros', 'KN': 'Saint Kitts and Nevis',
    'KP': 'North Korea', 'KR': 'South Korea', 'KW': 'Kuwait', 'KY': 'Cayman Islands', 'KZ': 'Kazakhstan',
    'LA': 'Laos', 'LB': 'Lebanon', 'LC': 'Saint Lucia', 'LI': 'Liechtenstein', 'LK': 'Sri Lanka',
    'LR': 'Liberia', 'LS': 'Lesotho', 'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia',
    'LY': 'Libya', 'MA': 'Morocco', 'MC': 'Monaco', 'MD': 'Moldova', 'ME': 'Montenegro',
    'MF': 'Saint Martin', 'MG': 'Madagascar', 'MH': 'Marshall Islands', 'MK': 'North Macedonia',
    'ML': 'Mali', 'MM': 'Myanmar', 'MN': 'Mongolia', 'MO': 'Macao', 'MP': 'Northern Mariana Islands',
    'MQ': 'Martinique', 'MR': 'Mauritania', 'MS': 'Montserrat', 'MT': 'Malta', 'MU': 'Mauritius',
    'MV': 'Maldives', 'MW': 'Malawi', 'MX': 'Mexico', 'MY': 'Malaysia', 'MZ': 'Mozambique',
    'NA': 'Namibia', 'NC': 'New Caledonia', 'NE': 'Niger', 'NF': 'Norfolk Island', 'NG': 'Nigeria',
    'NI': 'Nicaragua', 'NL': 'Netherlands', 'NO': 'Norway', 'NP': 'Nepal', 'NR': 'Nauru',
    'NU': 'Niue', 'NZ': 'New Zealand', 'OM': 'Oman', 'PA': 'Panama', 'PE': 'Peru',
    'PF': 'French Polynesia', 'PG': 'Papua New Guinea', 'PH': 'Philippines', 'PK': 'Pakistan',
    'PL': 'Poland', 'PM': 'Saint Pierre and Miquelon', 'PN': 'Pitcairn Islands', 'PR': 'Puerto Rico',
    'PS': 'Palestine', 'PT': 'Portugal', 'PW': 'Palau', 'PY': 'Paraguay', 'QA': 'Qatar',
    'RE': 'Reunion', 'RO': 'Romania', 'RS': 'Serbia', 'RU': 'Russia', 'RW': 'Rwanda',
    'SA': 'Saudi Arabia', 'SB': 'Solomon Islands', 'SC': 'Seychelles', 'SD': 'Sudan', 'SE': 'Sweden',
    'SG': 'Singapore', 'SH': 'Saint Helena', 'SI': 'Slovenia', 'SJ': 'Svalbard and Jan Mayen',
    'SK': 'Slovakia', 'SL': 'Sierra Leone', 'SM': 'San Marino', 'SN': 'Senegal', 'SO': 'Somalia',
    'SR': 'Suriname', 'SS': 'South Sudan', 'ST': 'Sao Tome and Principe', 'SV': 'El Salvador',
    'SX': 'Sint Maarten', 'SY': 'Syria', 'SZ': 'Eswatini', 'TC': 'Turks and Caicos Islands',
    'TD': 'Chad', 'TF': 'French Southern Territories', 'TG': 'Togo', 'TH': 'Thailand', 'TJ': 'Tajikistan',
    'TK': 'Tokelau', 'TL': 'Timor Leste', 'TM': 'Turkmenistan', 'TN': 'Tunisia', 'TO': 'Tonga',
    'TR': 'Turkey', 'TT': 'Trinidad and Tobago', 'TV': 'Tuvalu', 'TW': 'Taiwan', 'TZ': 'Tanzania',
    'UA': 'Ukraine', 'UG': 'Uganda', 'UM': 'United States Minor Outlying Islands', 'US': 'United States',
    'UY': 'Uruguay', 'UZ': 'Uzbekistan', 'VA': 'Vatican City', 'VC': 'Saint Vincent and the Grenadines',
    'VE': 'Venezuela', 'VG': 'British Virgin Islands', 'VI': 'United States Virgin Islands', 'VN': 'Vietnam',
    'VU': 'Vanuatu', 'WF': 'Wallis and Futuna', 'WS': 'Samoa', 'YE': 'Yemen', 'YT': 'Mayotte',
    'ZA': 'South Africa', 'ZM': 'Zambia', 'ZW': 'Zimbabwe',
}
COUNTRY_ALIASES = {
    'usa': 'US', 'united states': 'US', 'america': 'US', 'uk': 'GB', 'united kingdom': 'GB',
    'england': 'GB', 'britain': 'GB', 'germany': 'DE', 'deutschland': 'DE', 'singapore': 'SG',
    'sgp': 'SG', 'japan': 'JP', 'korea': 'KR', 'south korea': 'KR', 'hong kong': 'HK',
    'taiwan': 'TW', 'china': 'CN', 'netherlands': 'NL', 'holland': 'NL', 'france': 'FR',
    'canada': 'CA', 'australia': 'AU', 'indonesia': 'ID', 'india': 'IN', 'iran': 'IR',
    'turkey': 'TR', 'türkiye': 'TR', 'russia': 'RU', 'vietnam': 'VN', 'thailand': 'TH',
    'malaysia': 'MY', 'philippines': 'PH', 'brazil': 'BR', 'poland': 'PL', 'sweden': 'SE',
    'finland': 'FI', 'norway': 'NO', 'denmark': 'DK', 'spain': 'ES', 'italy': 'IT',
}
BASE64_LINKS = [
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/app/sub.txt',
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/mtn/sub_1.txt',
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/mtn/sub_2.txt',
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/mtn/sub_3.txt',
    'https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/mtn/sub_4.txt',
    'https://raw.githubusercontent.com/Surfboardv2ray/TGParse/main/splitted/mixed',
]
DIRECT_LINKS = [
    'https://raw.githubusercontent.com/itsyebekhe/PSG/main/lite/subscriptions/xray/normal/mix',
    'https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/mix/sub.html',
    'https://raw.githubusercontent.com/Rayan-Config/C-Sub/refs/heads/main/configs/proxy.txt',
    'https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt',
    'https://raw.githubusercontent.com/Everyday-VPN/Everyday-VPN/main/subscription/main.txt',
    'https://raw.githubusercontent.com/MahsaNetConfigTopic/config/refs/heads/main/xray_final.txt',
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/All_Configs_Sub.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/trojan.txt',
    'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vmess_configs.txt',
]
PREFIX = {'vmess': 'vmess://', 'vless': 'vless://', 'trojan': 'trojan://'}

def clean(v, default=''):
    if v is None:
        return default
    v = str(v).strip()
    return v if v else default

def yq(v):
    v = clean(v)
    if not v:
        return '""'
    # Quote semua scalar string agar YAML OpenClash lebih aman.
    # Sekaligus buang karakter kontrol/newline yang bisa merusak import.
    v = ''.join(ch if not unicodedata.category(ch).startswith('C') else ' ' for ch in v)
    v = re.sub(r'\s+', ' ', v).strip()
    return '"' + v.replace('\\', '\\\\').replace('\"', '\\"') + '"'


def flag_pair_to_country_code_for_name(text):
    """Ubah emoji bendera menjadi kode negara ASCII, contoh 🇸🇬 -> SG."""
    chars = list(clean(text))
    out = []
    i = 0
    while i < len(chars):
        if i + 1 < len(chars):
            a = ord(chars[i])
            b = ord(chars[i + 1])
            if 0x1F1E6 <= a <= 0x1F1FF and 0x1F1E6 <= b <= 0x1F1FF:
                out.append(' ' + chr(a - 0x1F1E6 + ord('A')) + chr(b - 0x1F1E6 + ord('A')) + ' ')
                i += 2
                continue
        out.append(chars[i])
        i += 1
    return ''.join(out)


def sanitize_proxy_name(name, fallback='Proxy', max_len=80):
    """Bersihkan nama proxy agar aman untuk OpenClash/Mihomo YAML.

    Karakter yang sering membuat import gagal seperti emoji, karakter kontrol,
    zero-width character, newline, kutip, kurung YAML, koma, pipe, backtick,
    dan simbol aneh akan dihapus/diganti spasi. Nama dibuat ASCII agar stabil
    saat dipakai di proxies, proxy-groups, file TXT, dan API delay test.
    """
    value = clean(name, fallback)
    value = flag_pair_to_country_code_for_name(value)
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(ch if not unicodedata.category(ch).startswith('C') else ' ' for ch in value)
    value = value.encode('ascii', 'ignore').decode('ascii', errors='ignore')
    value = re.sub(r'[^A-Za-z0-9._() -]+', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip(' ._-()')

    if not value:
        value = clean(fallback, 'Proxy')
        value = re.sub(r'[^A-Za-z0-9._() -]+', ' ', value)
        value = re.sub(r'\s+', ' ', value).strip(' ._-()') or 'Proxy'

    if len(value) > max_len:
        value = value[:max_len].rstrip(' ._-()') or 'Proxy'

    return value


def normalize_uuid_value(value):
    """Kembalikan UUID canonical jika valid; jika tidak valid, return string kosong.

    Tujuannya: akun VMess/VLESS dengan UUID rusak tidak ikut masuk YAML/TXT,
    karena UUID yang tidak sesuai format sering membuat OpenClash gagal import.
    Format yang diterima: UUID standar 36 karakter atau 32 hex tanpa strip.
    Output selalu dibuat canonical, contoh: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.
    """
    value = clean(value)
    if not value:
        return ''
    value = value.strip().strip('{}')
    try:
        parsed = uuidlib.UUID(value)
        return str(parsed)
    except Exception:
        return ''

def b64_bytes(data):
    for enc in ['utf-8', 'iso-8859-1']:
        try:
            return base64.b64decode(data + b'=' * (-len(data) % 4)).decode(enc)
        except (UnicodeDecodeError, binascii.Error, ValueError):
            pass
    return ''

def b64_text(txt):
    txt = clean(txt).replace('-', '+').replace('_', '/')
    try:
        return base64.b64decode((txt + '=' * (-len(txt) % 4)).encode()).decode('utf-8', errors='ignore')
    except Exception:
        return ''

def count_protocol_links(text):
    counts = {p: 0 for p in PROTOCOLS}
    for line in clean(text).splitlines():
        line = line.strip()
        for p, pref in PREFIX.items():
            if line.startswith(pref):
                counts[p] += 1
                break
    return counts


def source_cache_key(url, is_b64=False):
    raw = f'{"base64" if is_b64 else "direct"}|{url}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def source_cache_paths(url, is_b64=False):
    key = source_cache_key(url, is_b64)
    return SOURCE_CACHE_DIR / f'{key}.txt', SOURCE_CACHE_DIR / f'{key}.json'


def fill_source_counts(row, text):
    counts = count_protocol_links(text)
    row['chars'] = len(text or '')
    row['total_found'] = sum(counts.values())
    row['vmess_found'] = counts.get('vmess', 0)
    row['vless_found'] = counts.get('vless', 0)
    row['trojan_found'] = counts.get('trojan', 0)


def write_source_cache(url, is_b64, text, row):
    if not SOURCE_CACHE_ENABLE or not text:
        return
    try:
        data_path, meta_path = source_cache_paths(url, is_b64)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(text, encoding='utf-8')
        meta = {
            'url': url,
            'source_type': 'base64' if is_b64 else 'direct',
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'http_status': row.get('http_status', ''),
            'total_found': row.get('total_found', 0),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        pass


def read_source_cache(url, is_b64, row, error_text=''):
    if not SOURCE_CACHE_ENABLE:
        return ''
    try:
        data_path, meta_path = source_cache_paths(url, is_b64)
        if not data_path.exists():
            return ''
        text = data_path.read_text(encoding='utf-8', errors='replace')
        if not text:
            return ''
        fill_source_counts(row, text)
        row['status'] = 'cached'
        row['cache_used'] = 'true'
        row['cache_file'] = str(data_path).replace('\\', '/')
        row['error'] = error_text
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding='utf-8'))
                row['cache_updated_at'] = meta.get('updated_at', '')
            except Exception:
                pass
        return text
    except Exception as exc:
        row['cache_used'] = 'false'
        row['error'] = f'{error_text} | cache error: {exc}'.strip(' |')
        return ''


def fetch_source_payload(url, is_b64=False):
    row = {
        'url': url,
        'source_type': 'base64' if is_b64 else 'direct',
        'status': 'failed',
        'http_status': '',
        'total_found': 0,
        'vmess_found': 0,
        'vless_found': 0,
        'trojan_found': 0,
        'chars': 0,
        'cache_used': 'false',
        'cache_file': '',
        'cache_updated_at': '',
        'error': '',
    }
    try:
        r = requests.get(url, timeout=TIMEOUT)
        row['http_status'] = r.status_code
        r.raise_for_status()
        text = b64_bytes(r.content) if is_b64 else r.text
        fill_source_counts(row, text)
        row['status'] = 'ok' if text else 'empty'
        write_source_cache(url, is_b64, text, row)
        return text, row
    except Exception as exc:
        error_text = str(exc)
        cached_text = read_source_cache(url, is_b64, row, error_text)
        if cached_text:
            return cached_text, row
        row['error'] = error_text
        return '', row


def fetch_all_sources():
    tasks = []
    for url in BASE64_LINKS:
        tasks.append((url, True))
    for url in DIRECT_LINKS:
        tasks.append((url, False))

    contents = []
    SOURCE_STATUS_ROWS.clear()
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_source_payload, url, is_b64): (url, is_b64)
            for url, is_b64 in tasks
        }
        for future in as_completed(future_map):
            data, row = future.result()
            SOURCE_STATUS_ROWS.append(row)
            if data:
                contents.append(data)
    return contents

def protocol(line):
    for p, pref in PREFIX.items():
        if line.startswith(pref):
            return p
    return ''

def map_protocols(contents):
    out = {p: [] for p in PROTOCOLS}
    seen = {p: set() for p in PROTOCOLS}
    for content in contents:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            p = protocol(line)
            if p in out and line not in seen[p]:
                out[p].append(line)
                seen[p].add(line)
    return out

def qv(query, *keys, default=''):
    for k in keys:
        vals = query.get(k)
        if vals:
            return clean(unquote(vals[0]), default)
    return default

def parse_vmess(link):
    try:
        decoded = b64_text(link.replace('vmess://', '', 1))
        if not decoded:
            return None
        d = json.loads(decoded)
        path = clean(d.get('path'), '/')
        if not path.startswith('/'):
            path = '/' + path
        host = clean(d.get('host'))
        server = clean(d.get('add'))
        sni = clean(d.get('sni'))
        port = clean(d.get('port'), '443')
        tls_raw = clean(d.get('tls')).lower()
        raw_uuid = clean(d.get('id'))
        uuid_value = normalize_uuid_value(raw_uuid)
        return {
            'name': clean(d.get('ps'), 'VMess'),
            'server': server,
            'port': port,
            'uuid': uuid_value,
            'raw_uuid': raw_uuid,
            'alterId': clean(d.get('aid', d.get('alterId', 0)), '0'),
            'network': clean(d.get('net'), 'ws'),
            'path': path,
            'host': host or sni or server,
            'servername': sni or host or server,
            'tls': tls_raw in ['tls', 'true', '1'] or port == '443',
            'raw': link,
        }
    except Exception:
        return None

def parse_vless(link):
    try:
        u = urlparse(link); q = parse_qs(u.query)
        path = qv(q, 'path', default='/')
        if not path.startswith('/'):
            path = '/' + path
        server = clean(u.hostname)
        host = qv(q, 'host', 'Host')
        sni = qv(q, 'sni', 'servername')
        sec = qv(q, 'security', default='tls').lower()
        raw_uuid = clean(u.username)
        uuid_value = normalize_uuid_value(raw_uuid)
        return {
            'name': clean(unquote(u.fragment), 'VLESS'),
            'server': server,
            'port': str(u.port or 443),
            'uuid': uuid_value,
            'raw_uuid': raw_uuid,
            'network': qv(q, 'type', 'network', default='ws').lower(),
            'path': path,
            'host': host or sni or server,
            'servername': sni or host or server,
            'tls': sec in ['tls', 'reality', ''],
            'raw': link,
        }
    except Exception:
        return None

def parse_trojan(link):
    try:
        u = urlparse(link); q = parse_qs(u.query)
        path = qv(q, 'path', default='/')
        if not path.startswith('/'):
            path = '/' + path
        server = clean(u.hostname)
        host = qv(q, 'host', 'Host')
        sni = qv(q, 'sni', 'peer', 'servername')
        sec = qv(q, 'security', default='tls').lower()
        return {
            'name': clean(unquote(u.fragment), 'Trojan'),
            'server': server,
            'port': str(u.port or 443),
            'password': clean(unquote(u.username or '')),
            'network': qv(q, 'type', 'network', default='ws').lower(),
            'path': path,
            'host': host or sni or server,
            'sni': sni or host or server,
            'tls': sec in ['tls', ''],
            'raw': link,
        }
    except Exception:
        return None

def vmess_yaml(c):
    txt = f'''- name: {yq(c['name'])}
  type: vmess
  server: {yq(c['server'])}
  port: {c['port']}
  uuid: {c['uuid']}
  alterId: {c['alterId']}
  cipher: auto
  tls: true
  skip-cert-verify: true
  servername: {yq(c['servername'])}
  network: {c['network']}'''
    if c['network'].lower() == 'ws':
        txt += f'''
  ws-opts:
    path: {yq(c['path'])}
    headers:
      Host: {yq(c['host'])}'''
    return txt + '\n  udp: true'

def vless_yaml(c):
    txt = f'''- name: {yq(c['name'])}
  server: {yq(c['server'])}
  port: {c['port']}
  type: vless
  uuid: {c['uuid']}
  cipher: none
  tls: true
  skip-cert-verify: true
  network: {c['network']}
  servername: {yq(c['servername'])}'''
    if c['network'].lower() == 'ws':
        txt += f'''
  ws-opts:
    path: {yq(c['path'])}
    headers:
      Host: {yq(c['host'])}'''
    return txt + '\n  udp: true'

def trojan_yaml(c):
    txt = f'''- name: {yq(c['name'])}
  server: {yq(c['server'])}
  port: {c['port']}
  type: trojan
  password: {yq(c['password'])}
  tls: true
  skip-cert-verify: true
  network: {c['network']}
  sni: {yq(c['sni'])}'''
    if c['network'].lower() == 'ws':
        txt += f'''
  ws-opts:
    path: {yq(c['path'])}
    headers:
      Host: {yq(c['host'])}'''
    return txt + '\n  udp: true'

def encode_vmess(c):
    obj = {
        'v': '2', 'ps': c['name'], 'add': c['server'], 'port': c['port'], 'id': c['uuid'],
        'aid': c['alterId'], 'scy': 'auto', 'net': c['network'], 'type': 'none',
        'host': c['host'], 'path': c['path'], 'tls': 'tls' if c.get('tls') else '',
        'sni': c['servername'], 'alpn': ''
    }
    raw = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return 'vmess://' + base64.b64encode(raw).decode('utf-8')

def replace_server(link, new_server):
    if not new_server:
        return link
    try:
        u = urlparse(link)
        username = u.username or ''
        password = u.password or ''
        userinfo = f'{username}:{password}@' if username and password else (f'{username}@' if username else '')
        netloc = f'{userinfo}{new_server}:{u.port}' if u.port else f'{userinfo}{new_server}'
        return urlunparse(u._replace(netloc=netloc))
    except Exception:
        return link

def valid(p, c):
    reasons = []
    if c is None:
        return False, ['gagal parse']
    if ONLY_PORT_443 and clean(c.get('port')) != '443':
        reasons.append('port bukan 443')

    if p in ['vmess', 'vless']:
        if not clean(c.get('raw_uuid') or c.get('uuid')):
            reasons.append('uuid kosong')
        elif not clean(c.get('uuid')):
            reasons.append('uuid tidak valid')

    req = {
        'vmess': ['server', 'network', 'servername'],
        'vless': ['server', 'network', 'servername', 'path', 'host'],
        'trojan': ['server', 'password', 'network', 'sni', 'path', 'host'],
    }[p]
    for k in req:
        if not clean(c.get(k)):
            reasons.append(f'{k} kosong')
    if p in ['vless', 'trojan'] and c.get('network') != 'ws':
        reasons.append('network bukan ws')
    return len(reasons) == 0, reasons


def norm_key(v):
    return clean(v).strip().lower()

def normalized_path_for_key(value):
    value = norm_key(value)
    if not value:
        return '/'
    return value if value.startswith('/') else '/' + value


def account_key(p, c):
    """Fingerprint kuat untuk dedup akun.

    Nama config tidak dipakai. Server output yang dioverride juga tidak dipakai, tetapi
    identitas tunnel seperti UUID/password, port, network, SNI, host, path, TLS/security,
    dan flow tetap dipakai agar akun yang sama dari source berbeda tidak dobel.
    """
    if p == 'vmess':
        parts = [
            p,
            norm_key(c.get('uuid')),
            norm_key(c.get('alterId')),
            norm_key(c.get('cipher') or 'auto'),
            norm_key(c.get('network')),
            normalized_path_for_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('servername') or c.get('sni')),
            norm_key(c.get('port')),
        ]
    elif p == 'vless':
        parts = [
            p,
            norm_key(c.get('uuid')),
            norm_key(c.get('encryption') or 'none'),
            norm_key(c.get('flow')),
            norm_key(c.get('security') or 'tls'),
            norm_key(c.get('network')),
            normalized_path_for_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('servername') or c.get('sni')),
            norm_key(c.get('port')),
        ]
    elif p == 'trojan':
        parts = [
            p,
            norm_key(c.get('password')),
            norm_key(c.get('security') or 'tls'),
            norm_key(c.get('network')),
            normalized_path_for_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('sni') or c.get('servername')),
            norm_key(c.get('port')),
        ]
    else:
        parts = [p, norm_key(c.get('raw'))]
    raw_key = '|'.join(parts)
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:24]


def flag_to_country_code(text):
    """Ambil kode negara dari emoji bendera, contoh 🇸🇬 -> SG."""
    chars = list(clean(text))
    for i in range(len(chars) - 1):
        a = ord(chars[i])
        b = ord(chars[i + 1])
        if 0x1F1E6 <= a <= 0x1F1FF and 0x1F1E6 <= b <= 0x1F1FF:
            code = chr(a - 0x1F1E6 + ord('A')) + chr(b - 0x1F1E6 + ord('A'))
            if code in COUNTRY_NAMES:
                return code
    return ''


def detect_country_from_text(text):
    text = clean(text)
    if not text:
        return UNKNOWN_COUNTRY_CODE

    flag_code = flag_to_country_code(text)
    if flag_code:
        return flag_code

    # Format umum pada nama proxy: (SG), [US], {DE}, - JP -, | NL |, dll.
    for match in re.finditer(r'(?<![A-Z0-9])([A-Z]{2})(?![A-Z0-9])', text.upper()):
        code = match.group(1)
        if code in COUNTRY_NAMES:
            return code

    lower_text = text.lower()
    for alias, code in COUNTRY_ALIASES.items():
        if re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', lower_text):
            return code

    return UNKNOWN_COUNTRY_CODE


def detect_country(c):
    """Deteksi negara dari name, raw fragment, host, servername, dan server asli.
    Prioritas utama tetap name karena biasanya berisi kode/emoji negara dari sumber config.
    """
    parts = [
        clean(c.get('name')),
        clean(c.get('raw')),
        clean(c.get('host')),
        clean(c.get('servername')),
        clean(c.get('sni')),
        clean(c.get('server')),
    ]
    text = ' '.join(parts)
    return detect_country_from_text(text)


def country_label(code):
    if code == UNKNOWN_COUNTRY_CODE:
        return 'UNKNOWN'
    return f'{code} - {COUNTRY_NAMES.get(code, code)}'


def make_unique_name(name, used_names):
    """Jika name sudah dipakai, tambahkan angka acak di belakangnya sampai unik."""
    base_name = sanitize_proxy_name(name, 'Proxy')
    if base_name not in used_names:
        used_names.add(base_name)
        return base_name, ''

    for _ in range(1000):
        random_number = random.randint(1000, 9999)
        new_name = f'{base_name} {random_number}'
        if new_name not in used_names:
            used_names.add(new_name)
            return new_name, str(random_number)

    # Fallback sangat jarang, untuk mencegah loop berhenti tanpa hasil.
    suffix = len(used_names) + 1
    new_name = f'{base_name} {suffix}'
    while new_name in used_names:
        suffix += 1
        new_name = f'{base_name} {suffix}'
    used_names.add(new_name)
    return new_name, str(suffix)

def update_link_name(link, protocol_name, new_name):
    """Update nama/fragment pada link TXT vless/trojan agar sama dengan YAML.
    VMess tidak memakai fungsi ini karena nama disimpan dalam payload base64 dan dibuat ulang oleh encode_vmess().
    """
    if protocol_name == 'vmess':
        return link
    try:
        u = urlparse(link)
        return urlunparse(u._replace(fragment=quote(new_name, safe='._-()')))
    except Exception:
        return link

def load_blacklist_terms():
    if not BLACKLIST_FILE:
        return []
    path = Path(BLACKLIST_FILE)
    if not path.exists():
        return []
    terms = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        item = line.strip()
        if not item or item.startswith('#'):
            continue
        terms.append(item.lower())
    return terms


def blacklist_hit(c, terms):
    if not terms:
        return ''
    haystack = ' '.join([
        clean(c.get('name')),
        clean(c.get('raw')),
        clean(c.get('host')),
        clean(c.get('servername')),
        clean(c.get('sni')),
        clean(c.get('original_server')),
        clean(c.get('server')),
    ]).lower()
    for term in terms:
        if term and term in haystack:
            return term
    return ''


def write_source_status(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        'url', 'source_type', 'status', 'http_status', 'total_found',
        'vmess_found', 'vless_found', 'trojan_found', 'chars',
        'cache_used', 'cache_file', 'cache_updated_at', 'error'
    ]
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')

def write_invalid(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['protocol', 'reason', 'raw'])
        w.writeheader(); w.writerows(rows)


def write_duplicates(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        fields = ['protocol', 'duplicate_key', 'kept_name', 'duplicate_name', 'raw']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def write_renamed(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        fields = ['protocol', 'old_name', 'new_name', 'random_number', 'raw']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

def add_proxies_header(items):
    out = '\n'.join(items)
    if INCLUDE_PROXIES_HEADER and out:
        out = 'proxies:\n' + '\n'.join('  ' + line if line.strip() else line for line in out.splitlines())
    return out

def convert_protocol(p, links, used_names, blacklist_terms=None):
    parser = {'vmess': parse_vmess, 'vless': parse_vless, 'trojan': parse_trojan}[p]
    yaml_func = {'vmess': vmess_yaml, 'vless': vless_yaml, 'trojan': trojan_yaml}[p]
    override = {'vmess': VMESS_SERVER_OVERRIDE, 'vless': VLESS_SERVER_OVERRIDE, 'trojan': TROJAN_SERVER_OVERRIDE}[p]
    yaml_items, txt_items, invalid, duplicates, renamed, configs = [], [], [], [], [], []
    seen_accounts = {}
    blacklist_terms = blacklist_terms or []
    for link in links:
        c = parser(link)
        ok, reasons = valid(p, c)
        if not ok:
            invalid.append({'protocol': p, 'reason': '; '.join(reasons), 'raw': link})
            continue

        hit = blacklist_hit(c, blacklist_terms)
        if hit:
            invalid.append({'protocol': p, 'reason': f'blacklist: {hit}', 'raw': link})
            continue

        key = account_key(p, c)
        c['fingerprint'] = key
        if key in seen_accounts:
            duplicates.append({
                'protocol': p,
                'duplicate_key': key,
                'kept_name': seen_accounts[key],
                'duplicate_name': clean(c.get('name')),
                'raw': link,
            })
            continue
        seen_accounts[key] = clean(c.get('name'))

        old_name = clean(c.get('name'), {'vmess': 'VMess', 'vless': 'VLESS', 'trojan': 'Trojan'}[p])
        new_name, random_number = make_unique_name(old_name, used_names)
        if new_name != old_name:
            renamed.append({
                'protocol': p,
                'old_name': old_name,
                'new_name': new_name,
                'random_number': random_number,
                'raw': link,
            })
        c['name'] = new_name
        c['protocol'] = p
        c['country'] = detect_country(c)
        c['original_server'] = clean(c.get('server'))

        c['rank_penalty'] = 0
        if p == 'vmess':
            c['server'] = clean(override, c['server'])
            txt_link = encode_vmess(c)
            txt_items.append(txt_link)
            yaml_text = yaml_func(c)
            yaml_items.append(yaml_text)
        else:
            renamed_link = update_link_name(link, p, c['name'])
            txt_link = replace_server(renamed_link, override)
            txt_items.append(txt_link)
            c['server'] = clean(override, c['server'])
            yaml_text = yaml_func(c)
            yaml_items.append(yaml_text)
        c['txt_link'] = txt_link
        c['yaml_text'] = yaml_text
        configs.append(c)
    return yaml_items, txt_items, invalid, duplicates, renamed, configs


def indent_block(text, spaces=2):
    prefix = ' ' * spaces
    return '\n'.join(prefix + line if line.strip() else line for line in text.splitlines())


RESERVED_GROUP_ITEMS = {'DIRECT', 'REJECT'}


def clean_group_proxy_names(names, allow_direct_reject=False):
    """Bersihkan daftar isi proxy-group.

    DIRECT dan REJECT hanya boleh muncul di group type: select.
    Group type: url-test/best-ping harus hanya berisi nama akun/proxy asli.
    """
    cleaned = []
    seen = set()

    for name in names or []:
        item = clean(name)
        if not item:
            continue
        if not allow_direct_reject and item.upper() in RESERVED_GROUP_ITEMS:
            continue
        if item in seen:
            continue
        cleaned.append(item)
        seen.add(item)

    return cleaned


def yaml_name_list(names, spaces=4, fallback=None):
    prefix = ' ' * spaces
    names = list(names or [])
    if not names:
        names = list(fallback or [])
    if not names:
        return ''
    return '\n'.join(prefix + '- ' + yq(name) for name in names)


def make_url_test_group(group_name, proxy_names):
    proxy_names = clean_group_proxy_names(proxy_names, allow_direct_reject=False)
    if not proxy_names:
        return ''
    return f'''- name: {yq(group_name)}
  type: url-test
  proxies:
{yaml_name_list(proxy_names, 4)}
  url: {URL_TEST_URL}
  interval: {URL_TEST_INTERVAL}
  tolerance: {URL_TEST_TOLERANCE}'''


def make_load_balance_group(group_name, proxy_names):
    # Backward-compatible function name. Untuk OpenClash sekarang dibuat sebagai URL-Test Top 5, bukan load-balance.
    return make_url_test_group(group_name, proxy_names)


def make_fallback_group(group_name, proxy_names):
    proxy_names = clean_group_proxy_names(proxy_names, allow_direct_reject=False)
    if not proxy_names:
        return ''
    return f'''- name: {yq(group_name)}
  type: fallback
  proxies:
{yaml_name_list(proxy_names, 4)}
  url: {URL_TEST_URL}
  interval: {URL_TEST_INTERVAL}'''


def make_select_group(group_name, entries):
    entries = clean_group_proxy_names(entries, allow_direct_reject=True)
    if 'DIRECT' not in entries:
        entries.append('DIRECT')
    if 'REJECT' not in entries:
        entries.append('REJECT')
    return f'''- name: {yq(group_name)}
  type: select
  proxies:
{yaml_name_list(entries, 4, fallback=['DIRECT', 'REJECT'])}'''


def load_custom_rules():
    if not CUSTOM_RULES_FILE:
        return []
    path = Path(CUSTOM_RULES_FILE)
    if not path.exists():
        return []
    rules = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            item = line.strip()
            if not item or item.startswith('#'):
                continue
            if item.startswith('- '):
                item = item[2:].strip()
            if item:
                rules.append(item)
    except Exception:
        return []
    return rules


def render_rules_section():
    rules = load_custom_rules()
    if 'MATCH,PROXY' not in [rule.upper() for rule in rules]:
        rules.append('MATCH,PROXY')
    return 'rules:\n' + '\n'.join('  - ' + rule for rule in rules)


def build_openclash_yaml(
    all_yaml_items,
    protocol_proxy_names,
    country_proxy_names=None,
    external_controller='0.0.0.0:9090',
    best_balance_names=None,
):
    all_proxy_names = []
    for p in PROTOCOLS:
        all_proxy_names.extend(protocol_proxy_names.get(p, []))

    country_proxy_names = country_proxy_names or {}
    best_balance_names = best_balance_names or []
    groups = []
    protocol_group_names = []
    country_group_names = []

    if BEST_PING_BALANCE_ENABLE and best_balance_names:
        groups.append(make_load_balance_group(sanitize_proxy_name(BEST_PING_BALANCE_NAME, 'URL-TEST TOP 5 INDONESIA'), best_balance_names))
    for p in PROTOCOLS:
        names = protocol_proxy_names.get(p, [])
        if not names:
            continue
        group_name = f'URL-TEST {p.upper()}'
        protocol_group_names.append(group_name)
        groups.append(make_url_test_group(group_name, names))

    if all_proxy_names:
        groups.append(make_url_test_group('URL-TEST GABUNGAN', all_proxy_names))
        groups.append(make_fallback_group('FALLBACK', all_proxy_names))

    if ENABLE_COUNTRY_URL_TEST_GROUPS:
        for country_code in sorted(country_proxy_names):
            names = country_proxy_names.get(country_code, [])
            if not names:
                continue
            group_name = f'URL-TEST {country_label(country_code)}'
            country_group_names.append(group_name)
            groups.append(make_url_test_group(group_name, names))

    select_entries = []
    if BEST_PING_BALANCE_ENABLE and best_balance_names:
        select_entries.append(sanitize_proxy_name(BEST_PING_BALANCE_NAME, 'URL-TEST TOP 5 INDONESIA'))
    if all_proxy_names:
        select_entries.append('URL-TEST GABUNGAN')
        select_entries.append('FALLBACK')
    select_entries.extend(protocol_group_names)
    select_entries.extend(country_group_names)
    select_entries.append('DIRECT')
    groups.append(make_select_group('PROXY', select_entries))

    proxies_part = 'proxies:\n'
    if all_yaml_items:
        proxies_part += indent_block('\n'.join(all_yaml_items), 2)
    else:
        proxies_part += '  []'

    groups_part = 'proxy-groups:\n'
    if groups:
        groups_part += indent_block('\n\n'.join(g for g in groups if g), 2)
    else:
        groups_part += '  []'

    rules_part = render_rules_section()

    return f'''# Auto generated OpenClash config
# Output: output/{OPENCLASH_OUTPUT_FILE}

port: 7890
socks-port: 7891
redir-port: 7892
mixed-port: 7893
tproxy-port: 7895
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
ipv6: false
external-controller: {external_controller}

profile:
  store-selected: true
  store-fake-ip: true

dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  listen: 0.0.0.0:7874
  nameserver:
    - 1.1.1.1
    - 8.8.8.8
  fallback:
    - 1.0.0.1
    - 8.8.4.4

{proxies_part}

{groups_part}

{rules_part}
'''

def build_country_openclash_yaml(country_code, country_yaml_items, country_proxy_names):
    return build_openclash_yaml(
        country_yaml_items,
        {p: [] for p in PROTOCOLS},
        {country_code: country_proxy_names},
    )


def write_country_summary(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        fields = ['country_code', 'country_name', 'proxy_count', 'openclash_file', 'proxy_only_file']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)



def safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def config_row(c, status='', delay_ms='', reason=''):
    return {
        'protocol': clean(c.get('protocol')),
        'name': clean(c.get('name')),
        'country': clean(c.get('country')),
        'server': clean(c.get('server')),
        'original_server': clean(c.get('original_server')),
        'port': clean(c.get('port')),
        'network': clean(c.get('network')),
        'status': clean(status or c.get('status')),
        'delay_ms': clean(delay_ms if delay_ms != '' else c.get('delay_ms')),
        'rank_score': clean(c.get('rank_score')),
        'strict_success_rounds': clean(c.get('strict_success_rounds')),
        'strict_test_rounds': clean(c.get('strict_test_rounds')),
        'strict_required_rounds': clean(c.get('strict_required_rounds')),
        'fingerprint': clean(c.get('fingerprint')),
        'reason': clean(reason or c.get('reason')),
        'raw': clean(c.get('raw')),
    }


def write_check_results(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        'protocol', 'name', 'country', 'server', 'original_server', 'port',
        'network', 'status', 'delay_ms', 'rank_score', 'strict_success_rounds',
        'strict_test_rounds', 'strict_required_rounds', 'fingerprint', 'reason', 'raw'
    ]
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_test_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def delay_sort_value(c):
    try:
        return int(c.get('delay_ms'))
    except Exception:
        return 999999999


def rank_score(c, preferred_country=None):
    """Skor ranking: makin kecil makin baik.

    Dasar skor adalah delay. Ditambah penalti bila hasil hanya TCP fallback
    atau bila sistem harus fallback global dari filter negara.
    """
    delay = delay_sort_value(c)
    if delay >= 999999999:
        return delay
    score = delay + int(c.get('rank_penalty') or 0)
    reason = clean(c.get('reason')).lower()
    tester = clean(c.get('tester')).lower()
    if 'tcp' in reason or 'tcp' in tester:
        score += RANK_TCP_FALLBACK_PENALTY
    country = clean(preferred_country).upper()
    if country and clean(c.get('country')).upper() != country:
        score += RANK_GLOBAL_FALLBACK_PENALTY
    return score


def get_best_ping_configs(configs, limit=None, country_filter=None):
    """Ambil Top N dengan skor stabilitas sederhana.

    Default: proxy country == ID lebih diprioritaskan. Jika kosong dan
    BEST_PING_FALLBACK_GLOBAL=true, fallback ke global agar grup tidak kosong.
    """
    limit = int(limit or BEST_PING_TOP_N or 10)
    alive = [
        c for c in configs
        if c.get('status') == 'alive'
        and clean(c.get('name'))
        and delay_sort_value(c) < 999999999
        and delay_sort_value(c) <= MAX_DELAY_MS
    ]

    country = clean(country_filter if country_filter is not None else BEST_PING_COUNTRY_FILTER).upper()
    preferred_country_for_score = ''
    if country:
        country_alive = [
            c for c in alive
            if clean(c.get('country')).upper() == country
        ]
        if country_alive:
            alive = country_alive
            preferred_country_for_score = country
        elif not BEST_PING_FALLBACK_GLOBAL:
            alive = []
        else:
            preferred_country_for_score = country

    for c in alive:
        c['rank_score'] = rank_score(c, preferred_country_for_score)

    alive.sort(key=lambda item: (safe_int(item.get('rank_score'), 999999999), delay_sort_value(item), clean(item.get('name'))))
    return alive[:limit]


def write_best_ping_outputs(best_configs):
    best_dir = OUTPUT_DIR / 'BestPing'
    best_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for idx, c in enumerate(best_configs, start=1):
        row = config_row(c)
        row['rank'] = idx
        row['url_test_group'] = BEST_PING_BALANCE_NAME
        row['country_filter'] = BEST_PING_COUNTRY_FILTER or 'GLOBAL'
        rows.append(row)

    fields = [
        'rank', 'protocol', 'name', 'country', 'country_filter', 'server', 'original_server', 'port',
        'network', 'status', 'delay_ms', 'rank_score', 'strict_success_rounds',
        'strict_test_rounds', 'strict_required_rounds', 'fingerprint', 'reason', 'url_test_group', 'raw'
    ]
    with (best_dir / 'top5_best_ping.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    yaml_payload = add_proxies_header([c.get('yaml_text', '') for c in best_configs if c.get('yaml_text')])
    write(best_dir / 'top5_best_ping.yaml', yaml_payload)

    # Alias file khusus Indonesia agar mudah dibaca di repository.
    if BEST_PING_COUNTRY_FILTER == 'ID':
        with (best_dir / 'top5_indonesia_ping.csv').open('w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        write(best_dir / 'top5_indonesia_ping.yaml', yaml_payload)

    fallback_global_used = bool(
        BEST_PING_COUNTRY_FILTER
        and best_configs
        and not any(clean(c.get('country')).upper() == BEST_PING_COUNTRY_FILTER for c in best_configs)
    )

    summary_payload = {
        'label': 'Best Ping Top 5 Indonesia' if BEST_PING_COUNTRY_FILTER == 'ID' else 'Best Ping Top 5',
        'note': (
            'Default mengambil proxy country == ID. Delay tetap mengikuti lokasi runner/tempat test dijalankan. '
            'Jika tidak ada proxy ID alive dan BEST_PING_FALLBACK_GLOBAL=true, sistem memakai Top 5 global agar grup tidak kosong. '
            'Hasil Top 5 dimasukkan ke grup URL-Test di lengkap.yaml.'
        ),
        'country_filter': BEST_PING_COUNTRY_FILTER or 'GLOBAL',
        'fallback_global_if_empty': BEST_PING_FALLBACK_GLOBAL,
        'fallback_global_used': fallback_global_used,
        'url_test_group': BEST_PING_BALANCE_NAME,
        'group_type': 'url-test',
        'top_n': BEST_PING_TOP_N,
        'max_delay_ms': MAX_DELAY_MS,
        'count': len(best_configs),
        'names': [c.get('name') for c in best_configs],
    }

    write_test_summary(best_dir / 'summary_top5_best_ping.json', summary_payload)
    if BEST_PING_COUNTRY_FILTER == 'ID':
        write_test_summary(best_dir / 'summary_top5_indonesia_ping.json', summary_payload)


def unique_configs_by_name(configs):
    seen = set()
    result = []
    for c in configs or []:
        name = clean(c.get('name'))
        if not name or name in seen:
            continue
        result.append(c)
        seen.add(name)
    return result


def build_lite_openclash_yaml(lite_configs, top_country_names=None, top_global_names=None):
    lite_configs = unique_configs_by_name(lite_configs)
    yaml_items = [c.get('yaml_text', '') for c in lite_configs if c.get('yaml_text')]
    all_names = [c.get('name') for c in lite_configs if c.get('name')]
    top_country_names = clean_group_proxy_names(top_country_names or [], allow_direct_reject=False)
    top_global_names = clean_group_proxy_names(top_global_names or [], allow_direct_reject=False)
    all_names = clean_group_proxy_names(all_names, allow_direct_reject=False)

    groups = []
    select_entries = []
    if top_country_names:
        groups.append(make_url_test_group(sanitize_proxy_name(BEST_PING_BALANCE_NAME, 'URL-TEST TOP 5 INDONESIA'), top_country_names))
        select_entries.append(sanitize_proxy_name(BEST_PING_BALANCE_NAME, 'URL-TEST TOP 5 INDONESIA'))
    if top_global_names:
        groups.append(make_url_test_group('URL-TEST TOP GLOBAL', top_global_names))
        select_entries.append('URL-TEST TOP GLOBAL')
    if all_names:
        groups.append(make_fallback_group('FALLBACK', all_names))
        select_entries.append('FALLBACK')
    select_entries.append('DIRECT')
    groups.append(make_select_group('PROXY', select_entries))

    proxies_part = 'proxies:\n'
    proxies_part += indent_block('\n'.join(yaml_items), 2) if yaml_items else '  []'
    groups_part = 'proxy-groups:\n'
    groups_part += indent_block('\n\n'.join(g for g in groups if g), 2) if groups else '  []'
    rules_part = render_rules_section()

    return f'''# Auto generated Lite OpenClash config
# Output: output/{LITE_OUTPUT_FILE}

port: 7890
socks-port: 7891
redir-port: 7892
mixed-port: 7893
tproxy-port: 7895
allow-lan: true
bind-address: '*'
mode: rule
log-level: info
ipv6: false
external-controller: 0.0.0.0:9090

profile:
  store-selected: true
  store-fake-ip: true

dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  listen: 0.0.0.0:7874
  nameserver:
    - 1.1.1.1
    - 8.8.8.8
  fallback:
    - 1.0.0.1
    - 8.8.4.4

{proxies_part}

{groups_part}

{rules_part}
'''


def write_lite_output(alive_usable_configs, best_country_configs):
    best_country_configs = list(best_country_configs or [])
    alive_usable_configs = list(alive_usable_configs or [])
    global_best = get_best_ping_configs(alive_usable_configs, LITE_GLOBAL_TOP_N, country_filter='')
    picked = unique_configs_by_name(list(best_country_configs or []) + list(global_best or []))
    if LITE_MAX_TOTAL > 0:
        picked = picked[:LITE_MAX_TOTAL]
    lite_yaml = build_lite_openclash_yaml(
        picked,
        top_country_names=[c.get('name') for c in best_country_configs if c.get('name')],
        top_global_names=[c.get('name') for c in global_best if c.get('name')],
    )
    write(OUTPUT_DIR / LITE_OUTPUT_FILE, lite_yaml)
    write_test_summary(OUTPUT_DIR / 'Lite' / 'summary_lite.json', {
        'file': f'output/{LITE_OUTPUT_FILE}',
        'proxy_count': len(picked),
        'top_country_count': len(best_country_configs or []),
        'top_global_count': len(global_best or []),
        'lite_global_top_n': LITE_GLOBAL_TOP_N,
        'lite_max_total': LITE_MAX_TOTAL,
        'names': [c.get('name') for c in picked],
    })


def tcp_check(c):
    host = clean(c.get('server'))
    port = safe_int(c.get('port'), 443)
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=CHECK_TIMEOUT_MS / 1000):
            delay = int((time.perf_counter() - started) * 1000)
            return 'alive', delay, 'tcp connect ok'
    except Exception as exc:
        return 'dead', '', f'tcp error: {exc}'


def find_local_mihomo_binary():
    candidates = []
    if MIHOMO_BIN:
        candidates.append(MIHOMO_BIN)
    candidates.extend(['mihomo', 'clash-meta', 'clash'])
    for item in candidates:
        path = shutil.which(item) if not os.path.isabs(item) else item
        if path and Path(path).exists():
            return path
    return ''


def extract_mihomo_binary(download_path, target_path):
    name = download_path.name.lower()
    if name.endswith('.gz') and not name.endswith('.tar.gz'):
        with gzip.open(download_path, 'rb') as src, open(target_path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        target_path.chmod(0o755)
        return str(target_path)

    if name.endswith('.zip'):
        with zipfile.ZipFile(download_path) as zf:
            for member in zf.namelist():
                if member.endswith('/'):
                    continue
                lower = member.lower()
                if 'mihomo' in lower or 'clash' in lower:
                    with zf.open(member) as src, open(target_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    target_path.chmod(0o755)
                    return str(target_path)

    if name.endswith('.tar.gz') or name.endswith('.tgz'):
        with tarfile.open(download_path, 'r:gz') as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                lower = member.name.lower()
                if 'mihomo' in lower or 'clash' in lower:
                    src = tf.extractfile(member)
                    if src:
                        with src, open(target_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        target_path.chmod(0o755)
                        return str(target_path)
    return ''


def download_mihomo_binary(work_dir):
    if not MIHOMO_DOWNLOAD:
        return ''
    if not sys.platform.startswith('linux'):
        return ''

    api = 'https://api.github.com/repos/MetaCubeX/mihomo/releases/latest'
    try:
        release = requests.get(api, timeout=30).json()
    except Exception:
        return ''

    assets = release.get('assets', []) if isinstance(release, dict) else []
    preferred = []
    fallback = []
    for asset in assets:
        name = asset.get('name', '')
        url = asset.get('browser_download_url', '')
        lower = name.lower()
        if not url or 'sha256' in lower or 'checksum' in lower:
            continue
        if 'linux' in lower and 'amd64' in lower:
            fallback.append((name, url))
            if 'compatible' in lower:
                preferred.append((name, url))

    selected = (preferred or fallback)
    if not selected:
        return ''

    name, url = selected[0]
    download_path = Path(work_dir) / name
    target_path = Path(work_dir) / 'mihomo'
    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return extract_mihomo_binary(download_path, target_path)
    except Exception:
        return ''


def wait_mihomo_api(base_url, timeout_seconds=20):
    deadline = time.time() + timeout_seconds
    last_error = ''
    while time.time() < deadline:
        try:
            r = requests.get(f'{base_url}/proxies', timeout=3)
            if r.ok:
                return True, ''
            last_error = f'http {r.status_code}: {r.text[:120]}'
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    return False, last_error


def run_mihomo_delay_tests(configs):
    if not configs:
        return False, 'Tidak ada config untuk dites.'

    work_dir = tempfile.mkdtemp(prefix='mihomo-check-')
    process = None
    try:
        mihomo_bin = find_local_mihomo_binary() or download_mihomo_binary(work_dir)
        if not mihomo_bin:
            return False, 'Mihomo/Clash binary tidak ditemukan dan gagal download otomatis.'

        yaml_items = [c.get('yaml_text', '') for c in configs if c.get('yaml_text')]
        protocol_names = {p: [] for p in PROTOCOLS}
        country_names = {}
        for c in configs:
            protocol_names.setdefault(c.get('protocol'), []).append(c.get('name'))
            country_names.setdefault(c.get('country', UNKNOWN_COUNTRY_CODE), []).append(c.get('name'))

        controller = f'{MIHOMO_API_HOST}:{MIHOMO_API_PORT}'
        temp_config = Path(work_dir) / 'check.yaml'
        temp_config.write_text(
            build_openclash_yaml(
                yaml_items,
                protocol_names,
                country_names,
                external_controller=controller,
            ),
            encoding='utf-8',
        )

        process = subprocess.Popen(
            [mihomo_bin, '-f', str(temp_config), '-d', work_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        base_url = f'http://{controller}'
        ok, err = wait_mihomo_api(base_url)
        if not ok:
            output = ''
            try:
                if process.stdout:
                    output = process.stdout.read(1000)
            except Exception:
                pass
            return False, f'Mihomo API tidak aktif: {err}. {output[:500]}'

        def one(c):
            name = clean(c.get('name'))
            url = (
                f'{base_url}/proxies/{quote(name, safe="")}/delay'
                f'?timeout={CHECK_TIMEOUT_MS}&url={quote(CHECK_TEST_URL, safe="")}'
            )
            try:
                response = requests.get(url, timeout=(CHECK_TIMEOUT_MS / 1000) + 5)
                if response.ok:
                    data = response.json()
                    delay = data.get('delay')
                    if isinstance(delay, int) and delay > 0:
                        return c, 'alive', delay, 'proxy delay ok'
                    return c, 'dead', '', json.dumps(data, ensure_ascii=False)[:200]
                return c, 'dead', '', f'api http {response.status_code}: {response.text[:200]}'
            except Exception as exc:
                return c, 'dead', '', f'proxy test error: {exc}'

        with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as executor:
            futures = [executor.submit(one, c) for c in configs]
            for future in as_completed(futures):
                c, status, delay, reason = future.result()
                c['status'] = status
                c['delay_ms'] = delay
                c['reason'] = reason
        return True, 'Mihomo proxy delay test selesai.'
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
        shutil.rmtree(work_dir, ignore_errors=True)


def run_tcp_fallback_tests(configs, reason_prefix=''):
    def one(c):
        status, delay, reason = tcp_check(c)
        c['status'] = status
        c['delay_ms'] = delay
        c['reason'] = f'{reason_prefix} | {reason}'.strip(' |')
        return c

    with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as executor:
        futures = [executor.submit(one, c) for c in configs]
        for future in as_completed(futures):
            future.result()



def average_int(values):
    values = [safe_int(v, 0) for v in values if safe_int(v, 0) > 0]
    if not values:
        return ''
    return int(sum(values) / len(values))


def run_strict_mihomo_round_tests(configs):
    """Jalankan URL delay test beberapa ronde dan hanya luluskan node yang stabil.

    Strict mode tidak menerima TCP-only fallback sebagai akun hidup. Satu akun hanya
    dianggap usable jika lolos REQUIRE_SUCCESS_ROUNDS dari TEST_ROUNDS melalui
    endpoint /delay Mihomo/Clash.
    """
    required = max(1, min(REQUIRE_SUCCESS_ROUNDS, TEST_ROUNDS))
    round_reports = []

    for c in configs:
        c['_strict_success_rounds'] = 0
        c['_strict_delays'] = []
        c['strict_test_rounds'] = TEST_ROUNDS
        c['strict_required_rounds'] = required
        c['strict_success_rounds'] = 0
        c['tester'] = 'strict-mihomo-delay'

    for round_index in range(1, TEST_ROUNDS + 1):
        ok, message = run_mihomo_delay_tests(configs)
        alive_this_round = 0

        if ok:
            for c in configs:
                delay = delay_sort_value(c)
                if c.get('status') == 'alive' and 0 < delay <= STRICT_MAX_DELAY_MS:
                    c['_strict_success_rounds'] = int(c.get('_strict_success_rounds') or 0) + 1
                    c['_strict_delays'].append(delay)
                    alive_this_round += 1
        else:
            # Dalam strict mode, kegagalan Mihomo tidak diganti TCP fallback.
            # Ini sengaja agar output strict hanya berisi node yang lolos URL delay test asli.
            pass

        round_reports.append({
            'round': round_index,
            'tester': 'mihomo-delay',
            'tester_ok': bool(ok),
            'alive': alive_this_round,
            'message': message,
        })

    strict_alive = []
    for c in configs:
        success = int(c.get('_strict_success_rounds') or 0)
        delays = list(c.get('_strict_delays') or [])
        c['strict_success_rounds'] = success
        c['strict_test_rounds'] = TEST_ROUNDS
        c['strict_required_rounds'] = required
        c['tester'] = 'strict-mihomo-delay'

        if success >= required:
            c['status'] = 'alive'
            c['delay_ms'] = min(delays) if delays else ''
            c['rank_score'] = rank_score(c, BEST_PING_COUNTRY_FILTER)
            c['reason'] = (
                f'strict URL delay ok {success}/{TEST_ROUNDS}; '
                f'required={required}; min={min(delays) if delays else "-"}ms; '
                f'avg={average_int(delays) or "-"}ms'
            )
            strict_alive.append(c)
        else:
            c['status'] = 'dead'
            c['delay_ms'] = min(delays) if delays else ''
            c['rank_score'] = ''
            c['reason'] = (
                f'strict URL delay failed {success}/{TEST_ROUNDS}; '
                f'required={required}; max_delay={STRICT_MAX_DELAY_MS}ms; tcp fallback not accepted'
            )

    return strict_alive, round_reports

def apply_alive_tests(configs):
    summary = {
        'run_mode': RUN_MODE,
        'enable_proxy_test': ENABLE_PROXY_TEST,
        'filter_alive_only': FILTER_ALIVE_ONLY,
        'strict_alive_only': STRICT_ALIVE_ONLY,
        'test_rounds': TEST_ROUNDS,
        'require_success_rounds': REQUIRE_SUCCESS_ROUNDS,
        'strict_max_delay_ms': STRICT_MAX_DELAY_MS,
        'tcp_fallback_enabled': TCP_FALLBACK,
        'tcp_only_output_disabled': DISABLE_TCP_ONLY_OUTPUT,
        'strict_fallback_to_alive': STRICT_FALLBACK_TO_ALIVE,
        'strict_fallback_to_valid': STRICT_FALLBACK_TO_VALID,
        'test_url': CHECK_TEST_URL,
        'timeout_ms': CHECK_TIMEOUT_MS,
        'workers': CHECK_WORKERS,
        'tester': 'none',
        'tester_ok': False,
        'tester_message': '',
        'rounds': [],
        'max_delay_ms': MAX_DELAY_MS,
        'filter_max_delay_for_output': FILTER_MAX_DELAY_FOR_OUTPUT,
        'total': len(configs),
        'alive': 0,
        'strict_alive': 0,
        'dead': 0,
        'untested': 0,
    }

    if not ENABLE_PROXY_TEST:
        for c in configs:
            c['status'] = 'untested'
            c['delay_ms'] = ''
            c['strict_success_rounds'] = 0
            c['strict_test_rounds'] = TEST_ROUNDS
            c['strict_required_rounds'] = REQUIRE_SUCCESS_ROUNDS
            c['reason'] = 'ENABLE_PROXY_TEST=false; strict output tidak bisa diverifikasi'
        summary['untested'] = len(configs)
        summary['tester_message'] = 'Proxy test nonaktif. Tidak ada akun yang bisa dianggap strict alive.'
        summary['final_output_filter'] = 'untested; no strict alive verification'
        return [] if STRICT_ALIVE_ONLY else configs, summary

    if STRICT_ALIVE_ONLY:
        strict_configs, round_reports = run_strict_mihomo_round_tests(configs)
        summary['tester'] = 'strict-mihomo-delay'
        summary['tester_ok'] = bool(strict_configs)
        summary['rounds'] = round_reports
        summary['alive'] = len(strict_configs)
        summary['strict_alive'] = len(strict_configs)
        summary['dead'] = len(configs) - len(strict_configs)
        summary['untested'] = 0
        summary['strict_fallback_to_alive'] = STRICT_FALLBACK_TO_ALIVE
        summary['strict_fallback_to_valid'] = STRICT_FALLBACK_TO_VALID
        summary['tester_message'] = (
            f'STRICT_ALIVE_ONLY aktif tapi dibuat balanced: node cukup lolos {REQUIRE_SUCCESS_ROUNDS}/{TEST_ROUNDS} '
            f'ronde URL delay Mihomo dengan delay <= {STRICT_MAX_DELAY_MS}ms.'
        )
        summary['final_output_filter'] = f'strict/balanced alive {REQUIRE_SUCCESS_ROUNDS}/{TEST_ROUNDS} <= {STRICT_MAX_DELAY_MS}ms'

        if strict_configs:
            return strict_configs, summary

        # Jangan biarkan output kosong. Jika strict 0, turunkan ke test alive 1 ronde,
        # lalu ke TCP fallback, lalu terakhir semua config valid format.
        summary['tester_message'] += ' | Strict result kosong, fallback longgar diaktifkan agar output tidak kosong.'

        fallback_alive = []
        if STRICT_FALLBACK_TO_ALIVE:
            ok, message = run_mihomo_delay_tests(configs)
            summary['fallback_tester'] = 'mihomo-delay'
            summary['fallback_message'] = message

            if not ok and TCP_FALLBACK and not DISABLE_TCP_ONLY_OUTPUT:
                summary['fallback_tester'] = 'tcp-fallback'
                run_tcp_fallback_tests(configs, f'strict empty; mihomo unavailable: {message}')

            fallback_alive = [c for c in configs if c.get('status') == 'alive']

            if FILTER_MAX_DELAY_FOR_OUTPUT:
                fallback_under_delay = [c for c in fallback_alive if delay_sort_value(c) <= MAX_DELAY_MS]
                if fallback_under_delay:
                    fallback_alive = fallback_under_delay

            if fallback_alive:
                summary['alive'] = len(fallback_alive)
                summary['dead'] = sum(1 for c in configs if c.get('status') == 'dead')
                summary['untested'] = sum(1 for c in configs if c.get('status') == 'untested')
                summary['final_output_filter'] = 'fallback alive because strict empty'
                return fallback_alive, summary

        if STRICT_FALLBACK_TO_VALID:
            for c in configs:
                if not c.get('status'):
                    c['status'] = 'untested'
                if not c.get('reason'):
                    c['reason'] = 'strict empty; valid-format fallback used'
            summary['alive'] = sum(1 for c in configs if c.get('status') == 'alive')
            summary['dead'] = sum(1 for c in configs if c.get('status') == 'dead')
            summary['untested'] = sum(1 for c in configs if c.get('status') == 'untested')
            summary['final_output_filter'] = 'fallback all valid configs because strict/alive empty'
            return configs, summary

        return strict_configs, summary

    ok, message = run_mihomo_delay_tests(configs)
    summary['tester'] = 'mihomo-delay'
    summary['tester_ok'] = ok
    summary['tester_message'] = message

    if not ok:
        if TCP_FALLBACK and not DISABLE_TCP_ONLY_OUTPUT:
            summary['tester'] = 'tcp-fallback'
            run_tcp_fallback_tests(configs, f'mihomo unavailable: {message}')
        elif TCP_FALLBACK and DISABLE_TCP_ONLY_OUTPUT:
            for c in configs:
                c['status'] = 'untested'
                c['delay_ms'] = ''
                c['reason'] = f'mihomo unavailable: {message}; TCP fallback tidak dipakai untuk output final'
        else:
            for c in configs:
                c['status'] = 'untested'
                c['delay_ms'] = ''
                c['reason'] = message

    summary['alive'] = sum(1 for c in configs if c.get('status') == 'alive')
    summary['strict_alive'] = 0
    summary['dead'] = sum(1 for c in configs if c.get('status') == 'dead')
    summary['untested'] = sum(1 for c in configs if c.get('status') == 'untested')

    if FILTER_ALIVE_ONLY and summary['alive'] > 0:
        usable_alive = [
            c for c in configs
            if c.get('status') == 'alive'
            and (not FILTER_MAX_DELAY_FOR_OUTPUT or delay_sort_value(c) <= MAX_DELAY_MS)
        ]
        if usable_alive:
            summary['final_output_filter'] = f'alive <= {MAX_DELAY_MS}ms' if FILTER_MAX_DELAY_FOR_OUTPUT else 'alive only'
            return usable_alive, summary
        summary['tester_message'] += f' | Ada proxy alive, tetapi tidak ada yang delay <= {MAX_DELAY_MS}ms. Output utama memakai semua proxy alive agar tidak kosong.'
        summary['final_output_filter'] = 'alive only fallback because max delay filter empty'
        return [c for c in configs if c.get('status') == 'alive'], summary

    if FILTER_ALIVE_ONLY and summary['alive'] == 0:
        summary['tester_message'] += ' | Tidak ada proxy alive, output utama tetap memakai semua config valid agar file tidak kosong.'

    return configs, summary



def count_proxy_names_in_yaml_file(path):
    """Hitung jumlah proxy pada file OpenClash/YAML proxy-only secara ringan."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size <= 0:
            return 0
        text = p.read_text(encoding='utf-8', errors='ignore')
        # Proxy definitions in this generator always use "- name:".
        return len(re.findall(r'(?m)^\s*-\s+name\s*:', text))
    except Exception:
        return 0


def previous_output_path():
    if not PREVIOUS_OUTPUT_DIR:
        return None
    p = Path(PREVIOUS_OUTPUT_DIR)
    if not p.exists() or not p.is_dir():
        return None
    return p


def previous_output_has_accounts(prev_dir=None):
    prev = Path(prev_dir) if prev_dir else previous_output_path()
    if not prev:
        return False
    candidates = [
        prev / OPENCLASH_OUTPUT_FILE,
        prev / 'lengkap_alive.yaml',
        prev / STRICT_OUTPUT_FILE,
        prev / LITE_OUTPUT_FILE,
        prev / 'Yaml' / 'vmess.yaml',
        prev / 'Yaml' / 'vless.yaml',
        prev / 'Yaml' / 'trojan.yaml',
    ]
    return any(count_proxy_names_in_yaml_file(item) > 0 for item in candidates)


def raw_signature_from_mapping(mapped):
    """Signature akun raw dari source saat ini, dipakai untuk mendeteksi tidak ada akun baru."""
    h = hashlib.sha256()
    total = 0
    for p in PROTOCOLS:
        links = sorted(clean(x) for x in mapped.get(p, []) if clean(x))
        total += len(links)
        h.update((p + '\n').encode())
        for link in links:
            h.update(link.encode('utf-8', errors='ignore'))
            h.update(b'\n')
    return h.hexdigest(), total


def raw_signature_from_previous(prev_dir=None):
    prev = Path(prev_dir) if prev_dir else previous_output_path()
    if not prev:
        return '', 0
    mapped = {}
    total = 0
    for p in PROTOCOLS:
        raw_path = prev / 'Raw' / f'{p}.txt'
        links = []
        if raw_path.exists():
            try:
                links = [line.strip() for line in raw_path.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]
            except Exception:
                links = []
        mapped[p] = links
        total += len(links)
    sig, _ = raw_signature_from_mapping(mapped)
    return sig, total


def write_reuse_previous_report(reason, prev_dir, extra=None):
    report_dir = OUTPUT_DIR / 'Reuse'
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        'reuse_previous_output': True,
        'reason': reason,
        'previous_output_dir': str(prev_dir),
        'openclash_file': str(OUTPUT_DIR / OPENCLASH_OUTPUT_FILE),
        'openclash_proxy_count': count_proxy_names_in_yaml_file(OUTPUT_DIR / OPENCLASH_OUTPUT_FILE),
        'strict_file': str(OUTPUT_DIR / STRICT_OUTPUT_FILE),
        'strict_proxy_count': count_proxy_names_in_yaml_file(OUTPUT_DIR / STRICT_OUTPUT_FILE),
        'lite_file': str(OUTPUT_DIR / LITE_OUTPUT_FILE),
        'lite_proxy_count': count_proxy_names_in_yaml_file(OUTPUT_DIR / LITE_OUTPUT_FILE),
        'updated_at_epoch': int(time.time()),
    }
    if extra:
        payload.update(extra)
    (report_dir / 'reuse_previous_output.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def reuse_previous_output_if_available(reason, extra=None):
    """Restore output lama jika generate saat ini kosong/tidak berubah.

    Ini mencegah OpenClash menerima YAML kosong saat semua sumber gagal,
    GitHub rate limit, atau filter/test sedang terlalu ketat. Source status
    terbaru tetap ditulis agar alasan fallback terlihat.
    """
    prev = previous_output_path()
    if not prev or not previous_output_has_accounts(prev):
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Bersihkan output hasil generate parsial, lalu kembalikan output lama.
    for item in list(OUTPUT_DIR.iterdir()):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except Exception:
                pass

    for item in prev.iterdir():
        target = OUTPUT_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    # Jangan hilangkan laporan sumber terbaru. Ini akan menimpa source_status lama.
    write_source_status(
        OUTPUT_DIR / 'Source' / 'source_status.csv',
        sorted(SOURCE_STATUS_ROWS, key=lambda item: item.get('url', '')),
    )
    write_reuse_previous_report(reason, prev, extra or {})
    print(f'Reuse previous output aktif: {reason}')
    return True

def rebuild_collections(configs):
    yaml_items = [c.get('yaml_text', '') for c in configs if c.get('yaml_text')]
    txt_items_by_protocol = {p: [] for p in PROTOCOLS}
    yaml_items_by_protocol = {p: [] for p in PROTOCOLS}
    protocol_proxy_names = {p: [] for p in PROTOCOLS}
    country_yaml_items = {}
    country_proxy_names = {}

    for c in configs:
        p = c.get('protocol')
        if p in PROTOCOLS:
            txt_items_by_protocol[p].append(c.get('txt_link', ''))
            yaml_items_by_protocol[p].append(c.get('yaml_text', ''))
            protocol_proxy_names[p].append(c.get('name', ''))
        country_code = c.get('country', UNKNOWN_COUNTRY_CODE)
        country_yaml_items.setdefault(country_code, []).append(c.get('yaml_text', ''))
        country_proxy_names.setdefault(country_code, []).append(c.get('name', ''))

    return {
        'yaml_items': yaml_items,
        'txt_items_by_protocol': txt_items_by_protocol,
        'yaml_items_by_protocol': yaml_items_by_protocol,
        'protocol_proxy_names': protocol_proxy_names,
        'country_yaml_items': country_yaml_items,
        'country_proxy_names': country_proxy_names,
    }


def generate():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    contents = fetch_all_sources()
    write_source_status(OUTPUT_DIR / 'Source' / 'source_status.csv', sorted(SOURCE_STATUS_ROWS, key=lambda item: item.get('url', '')))
    mapped = map_protocols(contents)

    current_raw_signature, current_raw_count = raw_signature_from_mapping(mapped)
    previous_raw_signature, previous_raw_count = raw_signature_from_previous()

    if USE_PREVIOUS_OUTPUT_IF_EMPTY and current_raw_count == 0:
        if reuse_previous_output_if_available(
            'Tidak ada akun raw dari sumber mana pun. Output sebelumnya dipakai agar hasil tidak kosong.',
            {
                'current_raw_count': current_raw_count,
                'previous_raw_count': previous_raw_count,
                'source_signature_current': current_raw_signature,
                'source_signature_previous': previous_raw_signature,
            },
        ):
            return

    if (
        FAST_REUSE_WHEN_NO_SOURCE_CHANGE
        and current_raw_count > 0
        and previous_raw_count > 0
        and current_raw_signature == previous_raw_signature
    ):
        if reuse_previous_output_if_available(
            'Tidak ada akun baru dari sumber. Raw source sama dengan update sebelumnya, proses test dipersingkat dengan reuse output lama.',
            {
                'current_raw_count': current_raw_count,
                'previous_raw_count': previous_raw_count,
                'source_signature_current': current_raw_signature,
                'source_signature_previous': previous_raw_signature,
                'fast_reuse_when_no_source_change': True,
            },
        ):
            return

    blacklist_terms = load_blacklist_terms()
    summary, all_invalid, all_duplicates, all_renamed = [], [], [], []
    all_configs = []
    used_names = set()

    for p in PROTOCOLS:
        raw_links = mapped.get(p, [])
        yaml_items, txt_items, invalid, duplicates, renamed, configs = convert_protocol(p, raw_links, used_names, blacklist_terms)

        write(OUTPUT_DIR / 'Raw' / f'{p}.txt', '\n'.join(raw_links))
        write_invalid(OUTPUT_DIR / 'Invalid' / f'{p}_invalid.csv', invalid)
        write_duplicates(OUTPUT_DIR / 'Duplicate' / f'{p}_duplicates.csv', duplicates)
        write_renamed(OUTPUT_DIR / 'Renamed' / f'{p}_renamed.csv', renamed)

        if WRITE_ALL_VALID_BACKUP:
            write(OUTPUT_DIR / 'AllValid' / 'Yaml' / f'{p}.yaml', add_proxies_header(yaml_items))
            write(OUTPUT_DIR / 'AllValid' / 'Txt' / f'{p}.txt', '\n'.join(txt_items))

        all_configs.extend(configs)
        summary.append({
            'protocol': p,
            'raw_count': len(raw_links),
            'valid_before_test_count': len(configs),
            'invalid_count': len(invalid),
            'duplicate_count': len(duplicates),
            'renamed_count': len(renamed),
            'country_count': len(set(c.get('country', UNKNOWN_COUNTRY_CODE) for c in configs)),
            'yaml_file': f'output/Yaml/{p}.yaml',
            'txt_file': f'output/Txt/{p}.txt',
            'raw_file': f'output/Raw/{p}.txt'
        })
        all_invalid.extend(invalid)
        all_duplicates.extend(duplicates)
        all_renamed.extend(renamed)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if USE_PREVIOUS_OUTPUT_IF_EMPTY and not all_configs:
        if reuse_previous_output_if_available(
            'Tidak ada akun valid setelah parsing/validasi. Output sebelumnya dipakai agar hasil tidak kosong.',
            {
                'current_raw_count': current_raw_count,
                'previous_raw_count': previous_raw_count,
                'source_signature_current': current_raw_signature,
                'source_signature_previous': previous_raw_signature,
                'valid_config_count': 0,
            },
        ):
            return

    final_configs, test_summary = apply_alive_tests(all_configs)
    final_names = set(c.get('name') for c in final_configs)

    # Tulis laporan alive/dead lengkap.
    all_rows = [config_row(c) for c in all_configs]
    alive_rows = [config_row(c) for c in all_configs if c.get('status') == 'alive']
    dead_rows = [config_row(c) for c in all_configs if c.get('status') == 'dead']
    untested_rows = [config_row(c) for c in all_configs if c.get('status') == 'untested']
    write_check_results(OUTPUT_DIR / 'Alive' / 'check_result.csv', all_rows)
    write_check_results(OUTPUT_DIR / 'Alive' / 'alive.csv', alive_rows)
    write_check_results(OUTPUT_DIR / 'Alive' / 'dead.csv', dead_rows)
    write_check_results(OUTPUT_DIR / 'Alive' / 'untested.csv', untested_rows)
    write_test_summary(OUTPUT_DIR / 'Alive' / 'summary_alive.json', test_summary)

    alive_usable_configs = [
        c for c in all_configs
        if c.get('status') == 'alive'
        and (not FILTER_MAX_DELAY_FOR_OUTPUT or delay_sort_value(c) <= MAX_DELAY_MS)
    ]
    if not alive_usable_configs:
        alive_usable_configs = [c for c in all_configs if c.get('status') == 'alive']
    if not alive_usable_configs and final_configs:
        # Fallback agar lengkap_alive.yaml/lite/best ping tidak kosong saat filter terlalu ketat.
        alive_usable_configs = final_configs

    alive_yaml = [c.get('yaml_text', '') for c in all_configs if c.get('status') == 'alive']
    dead_yaml = [c.get('yaml_text', '') for c in all_configs if c.get('status') == 'dead']
    write(OUTPUT_DIR / 'Alive' / 'alive.yaml', add_proxies_header(alive_yaml))
    write(OUTPUT_DIR / 'Alive' / 'dead.yaml', add_proxies_header(dead_yaml))

    strict_usable_configs = [
        c for c in all_configs
        if c.get('status') == 'alive'
        and int(c.get('strict_success_rounds') or 0) >= int(c.get('strict_required_rounds') or REQUIRE_SUCCESS_ROUNDS)
        and (not FILTER_MAX_DELAY_FOR_OUTPUT or delay_sort_value(c) <= STRICT_MAX_DELAY_MS)
    ]
    if not STRICT_ALIVE_ONLY:
        strict_usable_configs = alive_usable_configs
    elif not strict_usable_configs:
        # Jika strict 0, isi strict_alive.yaml dari alive fallback/final valid agar tidak kosong.
        strict_usable_configs = alive_usable_configs or final_configs

    strict_rows = [config_row(c) for c in strict_usable_configs]
    write_check_results(OUTPUT_DIR / 'Strict' / 'strict_alive.csv', strict_rows)
    write(OUTPUT_DIR / 'Strict' / 'strict_alive_proxies.yaml', add_proxies_header([c.get('yaml_text', '') for c in strict_usable_configs if c.get('yaml_text')]))
    strict_collections = rebuild_collections(strict_usable_configs)
    strict_best_configs = get_best_ping_configs(strict_usable_configs, BEST_PING_TOP_N, BEST_PING_COUNTRY_FILTER)
    strict_best_names = [c.get('name') for c in strict_best_configs if c.get('name')]
    strict_yaml = build_openclash_yaml(
        strict_collections['yaml_items'],
        strict_collections['protocol_proxy_names'],
        strict_collections['country_proxy_names'],
        best_balance_names=strict_best_names,
    )
    write(OUTPUT_DIR / STRICT_OUTPUT_FILE, strict_yaml)
    write_test_summary(OUTPUT_DIR / 'Strict' / 'summary_strict_alive.json', {
        'file': f'output/{STRICT_OUTPUT_FILE}',
        'strict_alive_only': STRICT_ALIVE_ONLY,
        'test_rounds': TEST_ROUNDS,
        'require_success_rounds': REQUIRE_SUCCESS_ROUNDS,
        'strict_max_delay_ms': STRICT_MAX_DELAY_MS,
        'proxy_count': len(strict_usable_configs),
        'best_ping_count': len(strict_best_configs),
        'tcp_only_output_disabled': DISABLE_TCP_ONLY_OUTPUT,
        'names': [c.get('name') for c in strict_usable_configs],
    })

    alive_collections = rebuild_collections(alive_usable_configs)
    alive_best_configs = get_best_ping_configs(alive_usable_configs, BEST_PING_TOP_N, BEST_PING_COUNTRY_FILTER)
    alive_best_names = [c.get('name') for c in alive_best_configs if c.get('name')]
    lengkap_alive_yaml = build_openclash_yaml(
        alive_collections['yaml_items'],
        alive_collections['protocol_proxy_names'],
        alive_collections['country_proxy_names'],
        best_balance_names=alive_best_names,
    )
    write(OUTPUT_DIR / 'lengkap_alive.yaml', lengkap_alive_yaml)

    source_for_best = strict_usable_configs if STRICT_ALIVE_ONLY else alive_usable_configs
    best_configs = get_best_ping_configs(source_for_best, BEST_PING_TOP_N, BEST_PING_COUNTRY_FILTER)
    best_balance_names = [c.get('name') for c in best_configs if c.get('name')]
    write_lite_output(source_for_best, best_configs)
    test_summary['best_ping_top_n'] = BEST_PING_TOP_N
    test_summary['best_ping_country_filter'] = BEST_PING_COUNTRY_FILTER or 'GLOBAL'
    test_summary['best_ping_fallback_global_if_empty'] = BEST_PING_FALLBACK_GLOBAL
    test_summary['best_ping_url_test_group'] = BEST_PING_BALANCE_NAME
    test_summary['best_ping_group_type'] = 'url-test'
    test_summary['best_ping_count'] = len(best_configs)
    test_summary['best_ping_names'] = best_balance_names
    test_summary['strict_output_file'] = f'output/{STRICT_OUTPUT_FILE}'
    test_summary['strict_output_count'] = len(strict_usable_configs)
    write_test_summary(OUTPUT_DIR / 'Alive' / 'summary_alive.json', test_summary)
    write_best_ping_outputs(best_configs)

    collections = rebuild_collections(final_configs)

    # Output utama mengikuti hasil filter alive jika test berhasil dan ada proxy alive.
    for p in PROTOCOLS:
        write(OUTPUT_DIR / 'Yaml' / f'{p}.yaml', add_proxies_header(collections['yaml_items_by_protocol'].get(p, [])))
        write(OUTPUT_DIR / 'Txt' / f'{p}.txt', '\n'.join(collections['txt_items_by_protocol'].get(p, [])))

    openclash_yaml = build_openclash_yaml(
        collections['yaml_items'],
        collections['protocol_proxy_names'],
        collections['country_proxy_names'],
        best_balance_names=best_balance_names,
    )
    write(OUTPUT_DIR / OPENCLASH_OUTPUT_FILE, openclash_yaml)

    country_summary = []
    for country_code in sorted(collections['country_yaml_items']):
        items = collections['country_yaml_items'].get(country_code, [])
        names = collections['country_proxy_names'].get(country_code, [])
        if not items:
            continue
        proxy_only_path = OUTPUT_DIR / COUNTRY_OUTPUT_DIR / 'ProxyOnly' / f'{country_code}.yaml'
        openclash_path = OUTPUT_DIR / COUNTRY_OUTPUT_DIR / 'OpenClash' / f'{country_code}.yaml'
        write(proxy_only_path, add_proxies_header(items))
        write(openclash_path, build_country_openclash_yaml(country_code, items, names))
        country_summary.append({
            'country_code': country_code,
            'country_name': COUNTRY_NAMES.get(country_code, 'Unknown'),
            'proxy_count': len(names),
            'openclash_file': str(openclash_path).replace('\\', '/'),
            'proxy_only_file': str(proxy_only_path).replace('\\', '/'),
        })

    # Tambahkan jumlah akhir setelah test ke summary protocol.
    final_by_protocol = {p: 0 for p in PROTOCOLS}
    alive_by_protocol = {p: 0 for p in PROTOCOLS}
    strict_by_protocol = {p: 0 for p in PROTOCOLS}
    dead_by_protocol = {p: 0 for p in PROTOCOLS}
    for c in all_configs:
        p = c.get('protocol')
        if p in PROTOCOLS:
            if c.get('status') == 'alive':
                alive_by_protocol[p] += 1
                if int(c.get('strict_success_rounds') or 0) >= int(c.get('strict_required_rounds') or REQUIRE_SUCCESS_ROUNDS):
                    strict_by_protocol[p] += 1
            elif c.get('status') == 'dead':
                dead_by_protocol[p] += 1
            if c.get('name') in final_names:
                final_by_protocol[p] += 1

    for row in summary:
        p = row['protocol']
        row['alive_count'] = alive_by_protocol.get(p, 0)
        row['strict_alive_count'] = strict_by_protocol.get(p, 0)
        row['dead_count'] = dead_by_protocol.get(p, 0)
        row['final_output_count'] = final_by_protocol.get(p, 0)
        row['max_delay_ms'] = MAX_DELAY_MS
        row['blacklist_terms_count'] = len(blacklist_terms)

    with (OUTPUT_DIR / 'summary_protocol.csv').open('w', encoding='utf-8', newline='') as f:
        fields = [
            'protocol',
            'raw_count',
            'valid_before_test_count',
            'invalid_count',
            'duplicate_count',
            'renamed_count',
            'country_count',
            'alive_count',
            'strict_alive_count',
            'dead_count',
            'final_output_count',
            'max_delay_ms',
            'blacklist_terms_count',
            'yaml_file',
            'txt_file',
            'raw_file'
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary)

    write_invalid(OUTPUT_DIR / 'Invalid' / 'all_invalid.csv', all_invalid)
    write_duplicates(OUTPUT_DIR / 'Duplicate' / 'all_duplicates.csv', all_duplicates)
    write_renamed(OUTPUT_DIR / 'Renamed' / 'all_renamed.csv', all_renamed)
    write_country_summary(OUTPUT_DIR / COUNTRY_OUTPUT_DIR / 'summary_country.csv', country_summary)

    print('Done. Output folder:', OUTPUT_DIR)
    print('OpenClash file:', OUTPUT_DIR / OPENCLASH_OUTPUT_FILE)
    print('Proxy test summary:', json.dumps(test_summary, ensure_ascii=False))

def parse_bool_text(value):
    return str(value).strip().lower() in ['1', 'true', 'yes', 'y', 'on']


def main():
    global RUN_MODE, ENABLE_PROXY_TEST, FILTER_ALIVE_ONLY, STRICT_ALIVE_ONLY, TEST_ROUNDS, REQUIRE_SUCCESS_ROUNDS

    parser = argparse.ArgumentParser(description='Generate OpenClash YAML output.')
    parser.add_argument('--mode', default=RUN_MODE)
    parser.add_argument('--enable-proxy-test', default=str(ENABLE_PROXY_TEST).lower())
    parser.add_argument('--filter-alive-only', default=str(FILTER_ALIVE_ONLY).lower())
    parser.add_argument('--strict-alive-only', default=str(STRICT_ALIVE_ONLY).lower())
    parser.add_argument('--test-rounds', default=str(TEST_ROUNDS))
    parser.add_argument('--require-success-rounds', default=str(REQUIRE_SUCCESS_ROUNDS))
    args = parser.parse_args()

    RUN_MODE = clean(args.mode, RUN_MODE).lower()
    ENABLE_PROXY_TEST = parse_bool_text(args.enable_proxy_test)
    FILTER_ALIVE_ONLY = parse_bool_text(args.filter_alive_only)
    STRICT_ALIVE_ONLY = parse_bool_text(args.strict_alive_only)
    TEST_ROUNDS = max(1, safe_int(args.test_rounds, TEST_ROUNDS))
    REQUIRE_SUCCESS_ROUNDS = max(1, min(safe_int(args.require_success_rounds, REQUIRE_SUCCESS_ROUNDS), TEST_ROUNDS))
    generate()


if __name__ == '__main__':
    main()
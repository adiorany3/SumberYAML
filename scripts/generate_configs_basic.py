import base64, binascii, csv, json, random, re
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
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/vless.txt',
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/trojan.txt',
]
DIRECT_LINKS = [
    'https://raw.githubusercontent.com/itsyebekhe/PSG/main/lite/subscriptions/xray/normal/mix',
    'https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/mix/sub.html',
    'https://raw.githubusercontent.com/Rayan-Config/C-Sub/refs/heads/main/configs/proxy.txt',
    'https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt',
    'https://raw.githubusercontent.com/Everyday-VPN/Everyday-VPN/main/subscription/main.txt',
    'https://raw.githubusercontent.com/MahsaNetConfigTopic/config/refs/heads/main/xray_final.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/trojan.txt',
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/Splitted-By-Protocol/trojan.txt',
    'https://raw.githubusercontent.com/sevcator/5ubscrpt10n/main/protocols/vl.txt',
    'https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/main/detailed/vless/443.txt',
    'https://raw.githubusercontent.com/Delta-Kronecker/V2ray-Config/main/config/protocols/vless.txt',
    'https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/all_sub.txt',
    'https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt',
    'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/vless_configs.txt',
    'https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/main/V2Ray-Config-By-EbraSha-All-Type.txt',
    'https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/refs/heads/main/splitted-by-protocol/vless.txt',
    'https://raw.githubusercontent.com/shabane/kamaji/master/hub/SG.txt',
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

def fetch(url, is_b64=False):
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return b64_bytes(r.content) if is_b64 else r.text
    except requests.RequestException:
        return ''


def fetch_all_sources():
    tasks = []
    for url in BASE64_LINKS:
        tasks.append((url, True))
    for url in DIRECT_LINKS:
        tasks.append((url, False))

    contents = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        future_map = {
            executor.submit(fetch, url, is_b64): (url, is_b64)
            for url, is_b64 in tasks
        }
        for future in as_completed(future_map):
            data = future.result()
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

def account_key(p, c):
    """Kunci untuk mendeteksi duplikat akun setelah config berhasil diparse.
    Nama config dan raw link tidak dipakai supaya config yang sama dari source berbeda tetap dianggap duplikat.
    Server asli juga tidak dipakai karena output server akan dioverride menjadi satu server yang sama.
    """
    if p == 'vmess':
        parts = [
            p,
            norm_key(c.get('uuid')),
            norm_key(c.get('alterId')),
            norm_key(c.get('network')),
            norm_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('servername')),
            norm_key(c.get('port')),
        ]
    elif p == 'vless':
        parts = [
            p,
            norm_key(c.get('uuid')),
            norm_key(c.get('network')),
            norm_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('servername')),
            norm_key(c.get('port')),
        ]
    elif p == 'trojan':
        parts = [
            p,
            norm_key(c.get('password')),
            norm_key(c.get('network')),
            norm_key(c.get('path')),
            norm_key(c.get('host')),
            norm_key(c.get('sni')),
            norm_key(c.get('port')),
        ]
    else:
        parts = [p, norm_key(c.get('raw'))]
    return '|'.join(parts)


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

def convert_protocol(p, links, used_names):
    parser = {'vmess': parse_vmess, 'vless': parse_vless, 'trojan': parse_trojan}[p]
    yaml_func = {'vmess': vmess_yaml, 'vless': vless_yaml, 'trojan': trojan_yaml}[p]
    override = {'vmess': VMESS_SERVER_OVERRIDE, 'vless': VLESS_SERVER_OVERRIDE, 'trojan': TROJAN_SERVER_OVERRIDE}[p]
    yaml_items, txt_items, invalid, duplicates, renamed, configs = [], [], [], [], [], []
    seen_accounts = {}
    for link in links:
        c = parser(link)
        ok, reasons = valid(p, c)
        if not ok:
            invalid.append({'protocol': p, 'reason': '; '.join(reasons), 'raw': link})
            continue

        key = account_key(p, c)
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

        if p == 'vmess':
            c['server'] = clean(override, c['server'])
            txt_items.append(encode_vmess(c))
            yaml_text = yaml_func(c)
            yaml_items.append(yaml_text)
        else:
            renamed_link = update_link_name(link, p, c['name'])
            txt_items.append(replace_server(renamed_link, override))
            c['server'] = clean(override, c['server'])
            yaml_text = yaml_func(c)
            yaml_items.append(yaml_text)
        c['yaml_text'] = yaml_text
        configs.append(c)
    return yaml_items, txt_items, invalid, duplicates, renamed, configs


def indent_block(text, spaces=2):
    prefix = ' ' * spaces
    return '\n'.join(prefix + line if line.strip() else line for line in text.splitlines())


def yaml_name_list(names, spaces=4):
    prefix = ' ' * spaces
    if not names:
        return prefix + '- DIRECT'
    return '\n'.join(prefix + '- ' + yq(name) for name in names)


def make_url_test_group(group_name, proxy_names):
    if not proxy_names:
        return ''
    return f'''- name: {yq(group_name)}
  type: url-test
  proxies:
{yaml_name_list(proxy_names, 4)}
  url: {URL_TEST_URL}
  interval: {URL_TEST_INTERVAL}
  tolerance: {URL_TEST_TOLERANCE}'''


def make_select_group(group_name, entries):
    if not entries:
        entries = ['DIRECT']
    return f'''- name: {yq(group_name)}
  type: select
  proxies:
{yaml_name_list(entries, 4)}'''


def build_openclash_yaml(all_yaml_items, protocol_proxy_names, country_proxy_names=None):
    all_proxy_names = []
    for p in PROTOCOLS:
        all_proxy_names.extend(protocol_proxy_names.get(p, []))

    country_proxy_names = country_proxy_names or {}
    groups = []
    protocol_group_names = []
    country_group_names = []
    for p in PROTOCOLS:
        names = protocol_proxy_names.get(p, [])
        if not names:
            continue
        group_name = f'URL-TEST {p.upper()}'
        protocol_group_names.append(group_name)
        groups.append(make_url_test_group(group_name, names))

    if all_proxy_names:
        groups.append(make_url_test_group('URL-TEST GABUNGAN', all_proxy_names))

    for country_code in sorted(country_proxy_names):
        names = country_proxy_names.get(country_code, [])
        if not names:
            continue
        group_name = f'URL-TEST {country_label(country_code)}'
        country_group_names.append(group_name)
        groups.append(make_url_test_group(group_name, names))

    select_entries = []
    if all_proxy_names:
        select_entries.append('URL-TEST GABUNGAN')
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

rules:
  - MATCH,PROXY
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


def generate():
    contents = fetch_all_sources()
    mapped = map_protocols(contents)
    summary, all_invalid, all_duplicates, all_renamed = [], [], [], []
    all_yaml_items = []
    protocol_proxy_names = {p: [] for p in PROTOCOLS}
    country_yaml_items = {}
    country_proxy_names = {}
    used_names = set()

    for p in PROTOCOLS:
        raw_links = mapped.get(p, [])
        yaml_items, txt_items, invalid, duplicates, renamed, configs = convert_protocol(p, raw_links, used_names)

        write(OUTPUT_DIR / 'Yaml' / f'{p}.yaml', add_proxies_header(yaml_items))
        write(OUTPUT_DIR / 'Txt' / f'{p}.txt', '\n'.join(txt_items))
        write(OUTPUT_DIR / 'Raw' / f'{p}.txt', '\n'.join(raw_links))
        write_invalid(OUTPUT_DIR / 'Invalid' / f'{p}_invalid.csv', invalid)
        write_duplicates(OUTPUT_DIR / 'Duplicate' / f'{p}_duplicates.csv', duplicates)
        write_renamed(OUTPUT_DIR / 'Renamed' / f'{p}_renamed.csv', renamed)

        all_yaml_items.extend(yaml_items)
        protocol_proxy_names[p] = [c['name'] for c in configs]

        for c in configs:
            country_code = c.get('country', UNKNOWN_COUNTRY_CODE)
            country_yaml_items.setdefault(country_code, []).append(c.get('yaml_text', ''))
            country_proxy_names.setdefault(country_code, []).append(c.get('name', ''))

        summary.append({
            'protocol': p,
            'raw_count': len(raw_links),
            'yaml_valid_count': len(yaml_items),
            'txt_valid_count': len(txt_items),
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
    openclash_yaml = build_openclash_yaml(all_yaml_items, protocol_proxy_names, country_proxy_names)
    write(OUTPUT_DIR / OPENCLASH_OUTPUT_FILE, openclash_yaml)

    country_summary = []
    for country_code in sorted(country_yaml_items):
        items = country_yaml_items.get(country_code, [])
        names = country_proxy_names.get(country_code, [])
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

    with (OUTPUT_DIR / 'summary_protocol.csv').open('w', encoding='utf-8', newline='') as f:
        fields = [
            'protocol',
            'raw_count',
            'yaml_valid_count',
            'txt_valid_count',
            'invalid_count',
            'duplicate_count',
            'renamed_count',
            'country_count',
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

if __name__ == '__main__':
    generate()
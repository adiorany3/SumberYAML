import base64, binascii, csv, json, random
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, urlunparse
import requests

TIMEOUT = 10
OUTPUT_DIR = Path('output')
ONLY_PORT_443 = True
INCLUDE_PROXIES_HEADER = True
VMESS_SERVER_OVERRIDE = '104.17.3.81'
VLESS_SERVER_OVERRIDE = '104.17.3.81'
TROJAN_SERVER_OVERRIDE = '104.17.3.81'
PROTOCOLS = ['vmess', 'vless', 'trojan']
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
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/vless.txt',
    'https://raw.githubusercontent.com/barry-far/V2ray-config/main/Splitted-By-Protocol/trojan.txt',
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
    if any(c in v for c in [': ', '#', '{', '}', '[', ']', ',', '&', '*', '!', '|', '>', "'", '"', '%', '@', '`']):
        return '"' + v.replace('"', '\\"') + '"'
    return v

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
        return {
            'name': clean(d.get('ps'), 'VMess'),
            'server': server,
            'port': port,
            'uuid': clean(d.get('id')),
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
        return {
            'name': clean(unquote(u.fragment), 'VLESS'),
            'server': server,
            'port': str(u.port or 443),
            'uuid': clean(u.username),
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
  cipher: zero
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
  password: {c['password']}
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
    req = {
        'vmess': ['server', 'uuid', 'network', 'servername'],
        'vless': ['server', 'uuid', 'network', 'servername', 'path', 'host'],
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


def make_unique_name(name, used_names):
    """Jika name sudah dipakai, tambahkan angka acak di belakangnya sampai unik."""
    base_name = clean(name, 'Proxy')
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
        return urlunparse(u._replace(fragment=new_name))
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

def convert_protocol(p, links):
    parser = {'vmess': parse_vmess, 'vless': parse_vless, 'trojan': parse_trojan}[p]
    yaml_func = {'vmess': vmess_yaml, 'vless': vless_yaml, 'trojan': trojan_yaml}[p]
    override = {'vmess': VMESS_SERVER_OVERRIDE, 'vless': VLESS_SERVER_OVERRIDE, 'trojan': TROJAN_SERVER_OVERRIDE}[p]
    yaml_items, txt_items, invalid, duplicates, renamed = [], [], [], [], []
    seen_accounts = {}
    used_names = set()
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

        if p == 'vmess':
            c['server'] = clean(override, c['server'])
            txt_items.append(encode_vmess(c))
            yaml_items.append(yaml_func(c))
        else:
            renamed_link = update_link_name(link, p, c['name'])
            txt_items.append(replace_server(renamed_link, override))
            c['server'] = clean(override, c['server'])
            yaml_items.append(yaml_func(c))
    return yaml_items, txt_items, invalid, duplicates, renamed

def generate():
    contents = []
    for url in BASE64_LINKS:
        data = fetch(url, True)
        if data:
            contents.append(data)
    for url in DIRECT_LINKS:
        data = fetch(url, False)
        if data:
            contents.append(data)
    mapped = map_protocols(contents)
    summary, all_invalid, all_duplicates, all_renamed = [], [], [], []
    for p in PROTOCOLS:
        raw_links = mapped.get(p, [])
        yaml_items, txt_items, invalid, duplicates, renamed = convert_protocol(p, raw_links)
        write(OUTPUT_DIR / 'Yaml' / f'{p}.yaml', add_proxies_header(yaml_items))
        write(OUTPUT_DIR / 'Txt' / f'{p}.txt', '\n'.join(txt_items))
        write(OUTPUT_DIR / 'Raw' / f'{p}.txt', '\n'.join(raw_links))
        write_invalid(OUTPUT_DIR / 'Invalid' / f'{p}_invalid.csv', invalid)
        write_duplicates(OUTPUT_DIR / 'Duplicate' / f'{p}_duplicates.csv', duplicates)
        write_renamed(OUTPUT_DIR / 'Renamed' / f'{p}_renamed.csv', renamed)
        summary.append({
            'protocol': p, 'raw_count': len(raw_links), 'yaml_valid_count': len(yaml_items),
            'txt_valid_count': len(txt_items), 'invalid_count': len(invalid),
            'duplicate_count': len(duplicates), 'renamed_count': len(renamed),
            'yaml_file': f'output/Yaml/{p}.yaml', 'txt_file': f'output/Txt/{p}.txt',
            'raw_file': f'output/Raw/{p}.txt'
        })
        all_invalid.extend(invalid)
        all_duplicates.extend(duplicates)
        all_renamed.extend(renamed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / 'summary_protocol.csv').open('w', encoding='utf-8', newline='') as f:
        fields = ['protocol','raw_count','yaml_valid_count','txt_valid_count','invalid_count','duplicate_count','renamed_count','yaml_file','txt_file','raw_file']
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(summary)
    write_invalid(OUTPUT_DIR / 'Invalid' / 'all_invalid.csv', all_invalid)
    write_duplicates(OUTPUT_DIR / 'Duplicate' / 'all_duplicates.csv', all_duplicates)
    write_renamed(OUTPUT_DIR / 'Renamed' / 'all_renamed.csv', all_renamed)
    print('Done. Output folder:', OUTPUT_DIR)

if __name__ == '__main__':
    generate()
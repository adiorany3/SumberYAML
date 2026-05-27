import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    print('ERROR: PyYAML belum terpasang. Jalankan: pip install pyyaml', file=sys.stderr)
    raise

RESERVED = {'DIRECT', 'REJECT'}
DEFAULT_FILES = [
    'output/lengkap.yaml',
    'output/lengkap_alive.yaml',
    'output/strict_alive.yaml',
    'output/lite.yaml',
]


def load_yaml(path: Path):
    try:
        with path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        return None, [f'YAML parse error: {exc}']
    if data is None:
        return {}, []
    if not isinstance(data, dict):
        return data, ['Root YAML harus berupa mapping/object.']
    return data, []


def as_list(value):
    return value if isinstance(value, list) else []


def validate_file(path: Path):
    result = {
        'file': str(path).replace('\\', '/'),
        'exists': path.exists(),
        'ok': False,
        'proxy_count': 0,
        'group_count': 0,
        'errors': [],
        'warnings': [],
    }
    if not path.exists():
        result['errors'].append('File tidak ditemukan.')
        return result

    data, errors = load_yaml(path)
    result['errors'].extend(errors)
    if errors:
        return result

    proxies = as_list(data.get('proxies'))
    groups = as_list(data.get('proxy-groups'))
    result['proxy_count'] = len(proxies)
    result['group_count'] = len(groups)

    proxy_names = []
    duplicate_proxy_names = []
    seen_proxy_names = set()

    for index, proxy in enumerate(proxies, start=1):
        if not isinstance(proxy, dict):
            result['errors'].append(f'Proxy #{index} bukan object.')
            continue
        name = str(proxy.get('name', '')).strip()
        if not name:
            result['errors'].append(f'Proxy #{index} tidak punya name.')
            continue
        if name in RESERVED:
            result['errors'].append(f'Proxy name tidak boleh memakai reserved item: {name}.')
        if name in seen_proxy_names:
            duplicate_proxy_names.append(name)
        seen_proxy_names.add(name)
        proxy_names.append(name)

    if duplicate_proxy_names:
        result['errors'].append('Nama proxy duplikat: ' + ', '.join(sorted(set(duplicate_proxy_names))[:20]))

    valid_targets = set(proxy_names) | RESERVED
    group_names = set()

    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            result['errors'].append(f'Proxy group #{index} bukan object.')
            continue

        group_name = str(group.get('name', '')).strip()
        group_type = str(group.get('type', '')).strip()
        entries = as_list(group.get('proxies'))

        if not group_name:
            result['errors'].append(f'Proxy group #{index} tidak punya name.')
            continue
        if group_name in group_names:
            result['errors'].append(f'Nama proxy group duplikat: {group_name}.')
        group_names.add(group_name)

        if not group_type:
            result['errors'].append(f'Proxy group {group_name} tidak punya type.')

        if not entries:
            result['errors'].append(f'Proxy group {group_name} kosong.')
            continue

        normalized_entries = [str(item).strip() for item in entries if str(item).strip()]
        if len(normalized_entries) != len(entries):
            result['errors'].append(f'Proxy group {group_name} memiliki entry kosong.')

        if group_type in {'url-test', 'fallback', 'load-balance'}:
            reserved_hits = [item for item in normalized_entries if item in RESERVED]
            if reserved_hits:
                result['errors'].append(
                    f'Group {group_name} bertipe {group_type} tidak boleh berisi DIRECT/REJECT.'
                )

        for item in normalized_entries:
            if item in RESERVED:
                continue
            if item in group_names:
                # Group reference boleh dipakai di select; group mungkin didefinisikan sebelum/selama iterasi.
                continue
            if item not in valid_targets:
                # Bisa jadi referensi ke group yang belum sampai iterasinya; cek ulang setelah semua group terkumpul.
                pass

    valid_targets_final = set(proxy_names) | group_names | RESERVED
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get('name', '')).strip() or '<unknown>'
        for item in as_list(group.get('proxies')):
            item = str(item).strip()
            if item and item not in valid_targets_final:
                result['errors'].append(f'Group {group_name} mengarah ke proxy/group yang tidak ada: {item}.')

    result['ok'] = not result['errors']
    return result


def main():
    parser = argparse.ArgumentParser(description='Validasi output OpenClash YAML.')
    parser.add_argument('files', nargs='*', default=DEFAULT_FILES)
    parser.add_argument('--report', default='output/Validation/validation_report.json')
    args = parser.parse_args()

    reports = [validate_file(Path(item)) for item in args.files]
    ok = all(item['ok'] for item in reports)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({'ok': ok, 'files': reports}, ensure_ascii=False, indent=2), encoding='utf-8')

    for item in reports:
        status = 'OK' if item['ok'] else 'ERROR'
        print(f"[{status}] {item['file']} proxies={item['proxy_count']} groups={item['group_count']}")
        for error in item['errors']:
            print(f"  - {error}")

    if not ok:
        print(f'Validation report: {report_path}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

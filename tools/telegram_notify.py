import argparse
import csv
import json
import os
from pathlib import Path
import requests

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
SEND_FILE = os.getenv('TELEGRAM_SEND_OUTPUT_FILE', 'true').strip().lower() in ['1','true','yes','y','on']
RUN_MODE = os.getenv('RUN_MODE', '').strip().lower()


def mode_title():
    if RUN_MODE in ['test', 'test_ping']:
        return '🧪 <b>Test ping selesai</b>'
    if RUN_MODE in ['update_ping', 'ping_update']:
        return '🏆 <b>Update ping selesai</b>'
    return '✅ <b>Update OpenClash selesai</b>'


def tg(method):
    return f'https://api.telegram.org/bot{TOKEN}/{method}'


def send_message(text):
    if not TOKEN or not CHAT_ID:
        print('Telegram token/chat id kosong, skip notify')
        return
    for part in [text[i:i+3900] for i in range(0, len(text), 3900)] or ['']:
        r = requests.post(tg('sendMessage'), data={
            'chat_id': CHAT_ID,
            'text': part,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=30)
        print(r.status_code, r.text[:200])


def send_document(path, caption=''):
    if not TOKEN or not CHAT_ID or not Path(path).exists():
        return
    with open(path, 'rb') as f:
        r = requests.post(tg('sendDocument'), data={
            'chat_id': CHAT_ID,
            'caption': caption,
            'parse_mode': 'HTML',
        }, files={'document': f}, timeout=120)
        print(r.status_code, r.text[:200])


def read_summary():
    p = Path('output/Alive/summary_alive.json')
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_protocol_rows():
    p = Path('output/summary_protocol.csv')
    if not p.exists():
        return []
    with p.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def read_top10_rows():
    p = Path('output/BestPing/top10_indonesia.csv')
    if not p.exists():
        return []
    try:
        with p.open(encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))[:10]
    except Exception:
        return []


def success_message():
    s = read_summary()
    rows = read_protocol_rows()
    lines = [
        mode_title(),
        '',
        f'Total valid: <code>{s.get("total", "-")}</code>',
        f'Hidup: <code>{s.get("alive", "-")}</code>',
        f'Mati: <code>{s.get("dead", "-")}</code>',
        f'Untested: <code>{s.get("untested", "-")}</code>',
        f'Tester: <code>{s.get("tester", "-")}</code>',
        f'Filter alive only: <code>{s.get("filter_alive_only", "-")}</code>',
        f'Run mode: <code>{s.get("run_mode", RUN_MODE or "-")}</code>',
        '',
    ]
    if rows:
        lines.append('<b>Per protokol:</b>')
        for r in rows:
            lines.append(
                f'- {r.get("protocol", "-").upper()}: '
                f'alive <code>{r.get("alive_count", "0")}</code>, '
                f'dead <code>{r.get("dead_count", "0")}</code>, '
                f'output <code>{r.get("final_output_count", "0")}</code>'
            )
    top10 = read_top10_rows()
    if top10:
        lines.extend(['', '<b>Top 10 Balance:</b>'])
        for idx, row in enumerate(top10, start=1):
            lines.append(
                f'- #{idx} {row.get("name", "-")} '
                f'(<code>{row.get("delay_ms", "-")} ms</code>, {row.get("protocol", "-").upper()}, {row.get("country", "-")})'
            )

    msg = s.get('tester_message')
    if msg:
        lines.extend(['', f'<b>Info:</b> <code>{msg[:500]}</code>'])
    lines.extend([
        '',
        'File utama: <code>output/lengkap.yaml</code>',
        'Laporan: <code>output/Alive/check_result.csv</code>',
    ])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['success', 'failure'], required=True)
    args = parser.parse_args()

    if args.stage == 'failure':
        send_message('❌ <b>Update OpenClash gagal</b>\nCek log di GitHub Actions.')
        return

    send_message(success_message())
    if SEND_FILE:
        send_document('output/lengkap.yaml', '✅ <b>lengkap.yaml</b> terbaru')
        send_document('output/Alive/check_result.csv', '📊 <b>check_result.csv</b>')
        send_document('output/Alive/alive.csv', '✅ <b>alive.csv</b>')
        send_document('output/Alive/dead.csv', '❌ <b>dead.csv</b>')
        send_document('output/BestPing/top10_indonesia.csv', '🏆 <b>top10_indonesia.csv</b>')
        send_document('output/BestPing/top10_indonesia.yaml', '🏆 <b>top10_indonesia.yaml</b>')


if __name__ == '__main__':
    main()

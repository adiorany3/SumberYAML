#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-.}"
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

mkdir -p "$TARGET_DIR/scripts"
cp "$PATCH_DIR/scripts/apply_openclash_google_special_nodes.py" "$TARGET_DIR/scripts/apply_openclash_google_special_nodes.py"
chmod +x "$TARGET_DIR/scripts/apply_openclash_google_special_nodes.py"
cp "$PATCH_DIR/README_GOOGLE_SPECIAL_NODES_PATCH.md" "$TARGET_DIR/README_GOOGLE_SPECIAL_NODES_PATCH.md"

WORKFLOW="$TARGET_DIR/.github/workflows/update-openclash.yml"
if [ -f "$WORKFLOW" ]; then
  python - "$WORKFLOW" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8', errors='replace')
if 'Apply Google and YouTube special node routing' in text:
    print('Workflow sudah memiliki step Google special nodes; skip patch workflow.')
    raise SystemExit(0)

step = '''
      - name: Apply Google and YouTube special node routing
        run: |
          set -e
          if [ -f scripts/apply_openclash_google_special_nodes.py ]; then
            python scripts/apply_openclash_google_special_nodes.py --root .
            echo "Google special nodes report:"
            cat output/Validation/google_special_nodes_report.json || true
          else
            echo "ERROR: scripts/apply_openclash_google_special_nodes.py tidak ditemukan."
            exit 1
          fi
'''

anchors = [
    '      - name: Validate output exists',
    '      - name: Validate OpenClash YAML',
    '      - name: Assert latest output features',
]
insert_at = -1
anchor_used = ''
for anchor in anchors:
    idx = text.find(anchor)
    if idx != -1:
        insert_at = idx
        anchor_used = anchor
        break

if insert_at == -1:
    print('WARNING: Tidak menemukan anchor workflow untuk menyisipkan step Google.')
    print('Tambahkan manual step berikut sebelum Validate output exists:')
    print(step)
    raise SystemExit(0)

text = text[:insert_at] + step + text[insert_at:]
path.write_text(text, encoding='utf-8')
print(f'Workflow patched before: {anchor_used.strip()}')
PY
else
  echo "WARNING: workflow update-openclash.yml tidak ditemukan. Copy script saja."
fi

echo "Patch Google special nodes selesai dipasang ke: $TARGET_DIR"

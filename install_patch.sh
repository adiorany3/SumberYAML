#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-.}"
if [ ! -d "$TARGET" ]; then
  echo "Target directory tidak ditemukan: $TARGET" >&2
  exit 1
fi
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows" "$TARGET/input"
cp -a scripts/. "$TARGET/scripts/"
cp -a .github/. "$TARGET/.github/"
for f in README_*.md; do
  [ -f "$f" ] && cp -f "$f" "$TARGET/"
done
chmod +x "$TARGET/scripts/update_singbox_from_links.py" "$TARGET/scripts/validate_singbox_output.py" || true
echo "Patch sing-box latest format terpasang ke: $TARGET"

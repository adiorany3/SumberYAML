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
cp -f README_SINGBOX_LINKTXT_PATCH.md "$TARGET/"
chmod +x "$TARGET/scripts/update_singbox_from_links.py" "$TARGET/scripts/validate_singbox_output.py" || true
echo "Patch sing-box + link.txt terpasang ke: $TARGET"

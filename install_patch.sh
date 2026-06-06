#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$TARGET" ]; then
  echo "ERROR: target repo tidak ditemukan: $TARGET" >&2
  exit 1
fi

mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"
cp -a "$SCRIPT_DIR/scripts/." "$TARGET/scripts/"
cp -a "$SCRIPT_DIR/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp -a "$SCRIPT_DIR/README_GAME_WEB_BLOCK_EXPANDED_PATCH.md" "$TARGET/README_GAME_WEB_BLOCK_EXPANDED_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_game_block_inline_safe.py" || true
chmod +x "$TARGET/scripts/validate_game_block_inline_safe.py" || true

echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml README_GAME_WEB_BLOCK_EXPANDED_PATCH.md"

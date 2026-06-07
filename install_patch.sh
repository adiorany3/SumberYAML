#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-.}"
if [ ! -d "$TARGET" ]; then
  echo "ERROR: target repo tidak ditemukan: $TARGET" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows" "$TARGET/input"
cp -a "$SCRIPT_DIR/scripts/." "$TARGET/scripts/"
cp -a "$SCRIPT_DIR/.github/workflows/." "$TARGET/.github/workflows/"
if [ -d "$SCRIPT_DIR/input" ]; then
  cp -a "$SCRIPT_DIR/input/." "$TARGET/input/"
fi
for f in "$SCRIPT_DIR"/README*.md; do
  [ -f "$f" ] && cp -a "$f" "$TARGET/"
done
echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows input/extra_sources_urls.txt README*.md && git commit"

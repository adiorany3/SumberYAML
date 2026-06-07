#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Usage: bash install_patch.sh /path/to/SumberYAML"
  exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "ERROR: target directory not found: $TARGET"
  exit 1
fi
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"
cp -a "$ROOT/scripts/." "$TARGET/scripts/"
cp -a "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp -a "$ROOT"/README_*.md "$TARGET"/ 2>/dev/null || true
cp -a "$ROOT/manifest.json" "$TARGET/manifest_provider_bucket_input.json"
echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml README_PROVIDER_BUCKET_INPUT_PATCH.md README_EXTRA_SOURCES_ALIVE_PATCH.md README_GAME_WEB_BLOCK_EXPANDED_PATCH.md && git commit -m 'Bucket extra alive nodes into provider input files' && git push"

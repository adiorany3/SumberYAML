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
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"
cp -a "$ROOT/scripts/." "$TARGET/scripts/"
cp -a "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp -a "$ROOT"/README_* "$TARGET"/ 2>/dev/null || true
find "$TARGET" -type d -name __pycache__ -prune -exec rm -rf {} +
echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml README_* && git commit && git push"

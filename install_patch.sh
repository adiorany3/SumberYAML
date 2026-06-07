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
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows" "$TARGET/input"
cp -a "$ROOT/scripts/." "$TARGET/scripts/"
cp -a "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
if [ -d "$ROOT/input" ]; then
  cp -a "$ROOT/input/." "$TARGET/input/"
fi
cp -a "$ROOT"/README_*.md "$TARGET"/ 2>/dev/null || true
cp -a "$ROOT/manifest.json" "$TARGET/manifest_all_provider_bucket_filter.json"
echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml input/extra_sources_urls.txt README_*.md && git commit -m 'Filter extra alive nodes into provider input buckets' && git push"

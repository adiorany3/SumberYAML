#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Usage: bash install_patch.sh /path/to/SumberYAML"
  exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "Target directory not found: $TARGET"
  exit 1
fi
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"
cp "$ROOT/scripts/apply_openclash_strict_safe_fix.py" "$TARGET/scripts/apply_openclash_strict_safe_fix.py"
cp "$ROOT/scripts/validate_openclash_outputs.py" "$TARGET/scripts/validate_openclash_outputs.py"
cp "$ROOT/scripts/assert_latest_openclash_outputs.py" "$TARGET/scripts/assert_latest_openclash_outputs.py"
cp "$ROOT/scripts/force_output_update_marker.py" "$TARGET/scripts/force_output_update_marker.py"
cp "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp "$ROOT/README_STRICT_SAFE_SPECIAL_NODES_PATCH.md" "$TARGET/README_STRICT_SAFE_SPECIAL_NODES_PATCH.md"
chmod +x "$TARGET/scripts/apply_openclash_strict_safe_fix.py" \
         "$TARGET/scripts/validate_openclash_outputs.py" \
         "$TARGET/scripts/assert_latest_openclash_outputs.py" \
         "$TARGET/scripts/force_output_update_marker.py"
echo "Patch installed to $TARGET"

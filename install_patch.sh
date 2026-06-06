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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"

cp -f "$SCRIPT_DIR/scripts/apply_openclash_clean_responsive_rules.py" "$TARGET/scripts/apply_openclash_clean_responsive_rules.py"
cp -f "$SCRIPT_DIR/scripts/validate_openclash_outputs.py" "$TARGET/scripts/validate_openclash_outputs.py"
cp -f "$SCRIPT_DIR/scripts/assert_latest_openclash_outputs.py" "$TARGET/scripts/assert_latest_openclash_outputs.py"
cp -f "$SCRIPT_DIR/scripts/force_output_update_marker.py" "$TARGET/scripts/force_output_update_marker.py"
cp -f "$SCRIPT_DIR/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp -f "$SCRIPT_DIR/README_CLEAN_RESPONSIVE_REDDIT_PATCH.md" "$TARGET/README_CLEAN_RESPONSIVE_REDDIT_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_clean_responsive_rules.py"
chmod +x "$TARGET/scripts/validate_openclash_outputs.py"
chmod +x "$TARGET/scripts/assert_latest_openclash_outputs.py"
chmod +x "$TARGET/scripts/force_output_update_marker.py"

echo "Patch installed into: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml README_CLEAN_RESPONSIVE_REDDIT_PATCH.md && git commit && git push"

#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-.}"
if [ ! -d "$TARGET" ]; then
  echo "ERROR: target directory not found: $TARGET" >&2
  exit 1
fi

PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PATCH_DIR"

mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"

cp -f scripts/apply_openclash_app_aware_groups.py "$TARGET/scripts/apply_openclash_app_aware_groups.py"
cp -f scripts/validate_openclash_outputs.py "$TARGET/scripts/validate_openclash_outputs.py"
cp -f scripts/assert_latest_openclash_outputs.py "$TARGET/scripts/assert_latest_openclash_outputs.py"
cp -f scripts/force_output_update_marker.py "$TARGET/scripts/force_output_update_marker.py"
cp -f .github/workflows/update-openclash.yml "$TARGET/.github/workflows/update-openclash.yml"
cp -f README_SMART_APP_PROBE_STRICT_SAFE_PATCH.md "$TARGET/README_SMART_APP_PROBE_STRICT_SAFE_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_app_aware_groups.py" \
         "$TARGET/scripts/validate_openclash_outputs.py" \
         "$TARGET/scripts/assert_latest_openclash_outputs.py" \
         "$TARGET/scripts/force_output_update_marker.py"

echo "Patch installed to: $TARGET"
echo "Next: git add scripts .github/workflows/update-openclash.yml README_SMART_APP_PROBE_STRICT_SAFE_PATCH.md && git commit && git push"

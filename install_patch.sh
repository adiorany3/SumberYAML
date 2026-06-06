#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "Usage: bash install_patch.sh /path/to/SumberYAML"
  exit 1
fi

if [ ! -d "$TARGET" ]; then
  echo "Target folder not found: $TARGET"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$TARGET/scripts" "$TARGET/.github/workflows"

cp "$ROOT/scripts/apply_openclash_responsive_stability.py" "$TARGET/scripts/apply_openclash_responsive_stability.py"
cp "$ROOT/scripts/apply_openclash_rule_focus.py" "$TARGET/scripts/apply_openclash_rule_focus.py"
cp "$ROOT/scripts/apply_openclash_smart_qos.py" "$TARGET/scripts/apply_openclash_smart_qos.py"
cp "$ROOT/scripts/validate_openclash_outputs.py" "$TARGET/scripts/validate_openclash_outputs.py"
cp "$ROOT/scripts/force_output_update_marker.py" "$TARGET/scripts/force_output_update_marker.py"
cp "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp "$ROOT/README_SMART_SAFE_GENERATOR_PATCH.md" "$TARGET/README_SMART_SAFE_GENERATOR_PATCH.md"
cp "$ROOT/README_RULE_FOCUS_SMART_SAFE_PATCH.md" "$TARGET/README_RULE_FOCUS_SMART_SAFE_PATCH.md"
cp "$ROOT/README_SMART_QOS_OPENCLASH_SAFE_PATCH.md" "$TARGET/README_SMART_QOS_OPENCLASH_SAFE_PATCH.md"
cp "$ROOT/README_SELECTOR_ONLY_POLICY.md" "$TARGET/README_SELECTOR_ONLY_POLICY.md"
cp "$ROOT/README_FORCE_OUTPUT_UPDATE_PATCH.md" "$TARGET/README_FORCE_OUTPUT_UPDATE_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_responsive_stability.py" || true
chmod +x "$TARGET/scripts/apply_openclash_rule_focus.py" || true
chmod +x "$TARGET/scripts/apply_openclash_smart_qos.py" || true
chmod +x "$TARGET/scripts/validate_openclash_outputs.py" || true
chmod +x "$TARGET/scripts/force_output_update_marker.py" || true

echo "Force-output smart-qos patch installed to: $TARGET"
echo "Next steps:"
echo "  cd $TARGET"
echo "  python scripts/force_output_update_marker.py --root ."
echo "  git add scripts/apply_openclash_responsive_stability.py scripts/apply_openclash_rule_focus.py scripts/apply_openclash_smart_qos.py scripts/validate_openclash_outputs.py scripts/force_output_update_marker.py .github/workflows/update-openclash.yml README_SMART_SAFE_GENERATOR_PATCH.md README_RULE_FOCUS_SMART_SAFE_PATCH.md README_SMART_QOS_OPENCLASH_SAFE_PATCH.md README_SELECTOR_ONLY_POLICY.md README_FORCE_OUTPUT_UPDATE_PATCH.md"
echo "  git commit -m 'Force output update commit after OpenClash generation'"
echo "  git push"

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
cp "$ROOT/scripts/apply_openclash_input_vmess_loadbalance.py" "$TARGET/scripts/apply_openclash_input_vmess_loadbalance.py"
cp "$ROOT/scripts/validate_openclash_outputs.py" "$TARGET/scripts/validate_openclash_outputs.py"
cp "$ROOT/scripts/force_output_update_marker.py" "$TARGET/scripts/force_output_update_marker.py"
cp "$ROOT/scripts/assert_latest_openclash_outputs.py" "$TARGET/scripts/assert_latest_openclash_outputs.py"
cp "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp "$ROOT/README_SMART_SAFE_GENERATOR_PATCH.md" "$TARGET/README_SMART_SAFE_GENERATOR_PATCH.md"
cp "$ROOT/README_RULE_FOCUS_SMART_SAFE_PATCH.md" "$TARGET/README_RULE_FOCUS_SMART_SAFE_PATCH.md"
cp "$ROOT/README_SMART_QOS_OPENCLASH_SAFE_PATCH.md" "$TARGET/README_SMART_QOS_OPENCLASH_SAFE_PATCH.md"
cp "$ROOT/README_INPUT_VMESS_LOADBALANCE_PATCH.md" "$TARGET/README_INPUT_VMESS_LOADBALANCE_PATCH.md"
cp "$ROOT/README_SELECTOR_ONLY_POLICY.md" "$TARGET/README_SELECTOR_ONLY_POLICY.md"
cp "$ROOT/README_FORCE_OUTPUT_UPDATE_PATCH.md" "$TARGET/README_FORCE_OUTPUT_UPDATE_PATCH.md"
cp "$ROOT/README_FIX_OUTPUT_COMMIT_STAGING_PATCH.md" "$TARGET/README_FIX_OUTPUT_COMMIT_STAGING_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_responsive_stability.py" || true
chmod +x "$TARGET/scripts/apply_openclash_rule_focus.py" || true
chmod +x "$TARGET/scripts/apply_openclash_smart_qos.py" || true
chmod +x "$TARGET/scripts/apply_openclash_input_vmess_loadbalance.py" || true
chmod +x "$TARGET/scripts/validate_openclash_outputs.py" || true
chmod +x "$TARGET/scripts/force_output_update_marker.py" || true
chmod +x "$TARGET/scripts/assert_latest_openclash_outputs.py" || true

echo "Input-VMess load-balance smart-qos patch installed to: $TARGET"
echo "Next steps:"
echo "  cd $TARGET"
echo "  python scripts/force_output_update_marker.py --root ."
echo "  git add scripts/apply_openclash_responsive_stability.py scripts/apply_openclash_rule_focus.py scripts/apply_openclash_smart_qos.py scripts/apply_openclash_input_vmess_loadbalance.py scripts/validate_openclash_outputs.py scripts/force_output_update_marker.py scripts/assert_latest_openclash_outputs.py .github/workflows/update-openclash.yml README_SMART_SAFE_GENERATOR_PATCH.md README_RULE_FOCUS_SMART_SAFE_PATCH.md README_SMART_QOS_OPENCLASH_SAFE_PATCH.md README_INPUT_VMESS_LOADBALANCE_PATCH.md README_SELECTOR_ONLY_POLICY.md README_FORCE_OUTPUT_UPDATE_PATCH.md README_FIX_OUTPUT_COMMIT_STAGING_PATCH.md"
echo "  git commit -m 'Route marketplace social banking via input vmess load-balance'"
echo "  git push"

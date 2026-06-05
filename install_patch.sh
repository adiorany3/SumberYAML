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
cp "$ROOT/.github/workflows/update-openclash.yml" "$TARGET/.github/workflows/update-openclash.yml"
cp "$ROOT/README_SS_SSR_104_FALLBACK_PATCH.md" "$TARGET/README_SS_SSR_104_FALLBACK_PATCH.md"

chmod +x "$TARGET/scripts/apply_openclash_responsive_stability.py" || true

echo "Patch installed to: $TARGET"
echo "Next steps:"
echo "  cd $TARGET"
echo "  python scripts/apply_openclash_responsive_stability.py --root ."
echo "  git add scripts/apply_openclash_responsive_stability.py .github/workflows/update-openclash.yml README_SS_SSR_104_FALLBACK_PATCH.md"
echo "  git commit -m 'Add SS SSR 104 fallback source injection'"

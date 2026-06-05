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

if [ ! -f "$TARGET/telegram_openclash_alive.py" ]; then
  echo "WARNING: telegram_openclash_alive.py tidak ditemukan di target. Pastikan path adalah root repo SumberYAML."
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="$TARGET/.patch_backup_manual_fallback_safe_$STAMP"
mkdir -p "$BACKUP"

for file in \
  "scripts/apply_openclash_responsive_stability.py" \
  ".github/workflows/update-openclash.yml" \
  "README_MANUAL_FALLBACK_SAFE_PATCH.md"; do
  if [ -f "$TARGET/$file" ]; then
    mkdir -p "$BACKUP/$(dirname "$file")"
    cp -a "$TARGET/$file" "$BACKUP/$file"
  fi
  mkdir -p "$TARGET/$(dirname "$file")"
  cp -a "$file" "$TARGET/$file"
done

chmod +x "$TARGET/scripts/apply_openclash_responsive_stability.py" || true

echo "Patch installed to: $TARGET"
echo "Backup previous files: $BACKUP"
echo "Next: git add scripts/apply_openclash_responsive_stability.py .github/workflows/update-openclash.yml README_MANUAL_FALLBACK_SAFE_PATCH.md && git commit -m 'Add safe manual input fallback to OpenClash output' && git push"

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-.}"

mkdir -p "${REPO_ROOT}/scripts"
mkdir -p "${REPO_ROOT}/.github/workflows"

cp -f "scripts/apply_openclash_responsive_stability.py" "${REPO_ROOT}/scripts/apply_openclash_responsive_stability.py"
cp -f ".github/workflows/update-openclash.yml" "${REPO_ROOT}/.github/workflows/update-openclash.yml"
cp -f "README_RESPONSIVE_PATCH.md" "${REPO_ROOT}/README_RESPONSIVE_PATCH.md"

chmod +x "${REPO_ROOT}/scripts/apply_openclash_responsive_stability.py" || true

echo "Patch responsive SumberYAML berhasil dipasang ke: ${REPO_ROOT}"
echo "Langkah berikutnya: git add, git commit, git push, lalu jalankan workflow Update OpenClash mode update/optimize_openclash."

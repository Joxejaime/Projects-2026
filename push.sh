#!/usr/bin/env bash
# Publish this repository to GitHub as <user>/projects-2026.
# 1. On github.com create an EMPTY repository named projects-2026 (no README, license or .gitignore).
# 2. Run:  GITHUB_USER=<your-github-username> ./push.sh
# Uses HTTPS; authenticate with `gh auth login` or a personal access token when prompted.
set -euo pipefail
: "${GITHUB_USER:?set GITHUB_USER to your GitHub username (or organization)}"
cd "$(dirname "$0")"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GITHUB_USER}/projects-2026.git"
git push -u origin main
echo "Pushed. Next: replace the 'example-org' placeholders with ${GITHUB_USER}: grep -rn example-org ."

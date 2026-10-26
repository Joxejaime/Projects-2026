#!/usr/bin/env bash
# Publish this repository to GitHub as <user>/projects-2026.
# 1. On github.com create an EMPTY repository named projects-2026 (no README, license or .gitignore).
# 2. Run:  ./push.sh   (defaults to GITHUB_USER=Joxejaime; override with GITHUB_USER=<other>)
# Uses HTTPS; authenticate with `gh auth login` or a personal access token when prompted.
set -euo pipefail
GITHUB_USER="${GITHUB_USER:-Joxejaime}"
cd "$(dirname "$0")"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GITHUB_USER}/projects-2026.git"
git push -u origin main
echo "Pushed. Remaining placeholder: the @example-org/<team> CODEOWNERS handle (needs a GitHub organization)."

#!/usr/bin/env bash
###############################################################################
# Push WitnessReplay to GitHub
# Creates repo if it doesn't exist, then pushes all commits.
###############################################################################
set -euo pipefail

PROJECT_DIR="/mnt/media/witnessreplay/project"
GITHUB_USER="gil906"
GITHUB_REPO="witnessreplay"
REPO_URL="https://github.com/${GITHUB_USER}/${GITHUB_REPO}.git"

cd "$PROJECT_DIR"

# Ensure we're in a git repo
if [ ! -d .git ]; then
    echo "❌ No git repo found in ${PROJECT_DIR}. Run the builder first."
    exit 1
fi

# Add remote if not present
if ! git remote get-url origin &>/dev/null; then
    git remote add origin "$REPO_URL"
    echo "✅ Remote added: $REPO_URL"
fi

# Detect default branch
BRANCH=$(git branch --show-current 2>/dev/null || echo "main")
[ -z "$BRANCH" ] && BRANCH="main"

# Push
echo "🚀 Pushing to ${REPO_URL} (branch: ${BRANCH})..."
git push -u origin "$BRANCH" 2>&1 || {
    echo ""
    echo "⚠️  Push failed. The repo might not exist yet on GitHub."
    echo ""
    echo "Create it by visiting: https://github.com/new"
    echo "  Repo name: ${GITHUB_REPO}"
    echo "  Visibility: Public"
    echo "  Do NOT add README, .gitignore, or license"
    echo ""
    echo "Then re-run this script."
    exit 1
}

echo "✅ Pushed successfully!"
echo "🔗 https://github.com/${GITHUB_USER}/${GITHUB_REPO}"

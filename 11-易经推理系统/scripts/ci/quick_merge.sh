#!/usr/bin/env bash
set -euo pipefail

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" == "main" ]]; then
  echo "Do not run quick_merge.sh on main branch."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes first."
  exit 1
fi

REPO="${1:-yunya1991/dream-multiskill-v2}"
TITLE="${2:-$(git log -1 --pretty=%s)}"
BODY="${3:-Auto PR created by quick_merge.sh}"

echo "Remote-first guard check..."
python3 scripts/ci/remote_repo_guard.py "$REPO"

echo "Sync remotes..."
git fetch origin --prune

echo "Push branch: ${BRANCH}"
git push -u origin "$BRANCH"

if gh pr view --repo "$REPO" --json number >/dev/null 2>&1; then
  PR_NUMBER="$(gh pr view --repo "$REPO" --json number --jq .number)"
  echo "Using existing PR #${PR_NUMBER}"
else
  PR_URL="$(gh pr create --repo "$REPO" --base main --head "$BRANCH" --title "$TITLE" --body "$BODY")"
  echo "Created PR: ${PR_URL}"
  PR_NUMBER="$(gh pr view --repo "$REPO" --json number --jq .number)"
fi

echo "Waiting for PR checks..."
gh pr checks "$PR_NUMBER" --repo "$REPO" --watch --interval 5

echo "Merging PR #${PR_NUMBER}..."
gh pr merge "$PR_NUMBER" --repo "$REPO" --squash --delete-branch

echo "Updating local main..."
git checkout main
git fetch origin --prune
git rebase origin/main

echo "Done. Main is up to date."

#!/usr/bin/env bash
# Put the hosted Replay on GitHub Pages.
#
#   gh auth login                 # once, as the account that will own the repo
#   bash scripts/publish_pages.sh [owner/name] [password]
#
# Creates the repository, pushes this branch, turns Pages on and sets the password the site asks for. Everything it
# does is printed before it happens, and it stops at the first thing that is already done differently rather than
# changing it. Run it again after a failure: each step is skipped when it is already in place.
#
# The password is a latch, not a lock. A static host serves files to whoever asks, so every take, still and receipt
# stays reachable by its own URL whatever the page does. Do not put anything here that must not be read.
set -euo pipefail

REPO="${1:-d0rb/openfield-studio}"
PASSWORD="${2:-}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

say() { printf '\n== %s\n' "$*"; }

command -v gh >/dev/null || { echo "gh is not installed"; exit 1; }

say "Who is signed in"
gh auth status 2>&1 | sed -n '1,4p'
ME="$(gh api user --jq .login)"
OWNER="${REPO%%/*}"
if [ "$ME" != "$OWNER" ]; then
  echo "Signed in as '$ME' but the repository would be '$REPO'."
  echo "A user account can only be created in by itself: run  gh auth login  as '$OWNER', or pass another owner/name."
  exit 1
fi

say "The repository $REPO"
if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "already exists; leaving it as it is"
else
  echo "creating it (public, so GitHub Pages is free)"
  gh repo create "$REPO" --public --description "OpenField Studio: direct shots on open weights, and keep the receipt"
fi

say "The remote"
if git remote get-url origin >/dev/null 2>&1; then
  echo "origin is $(git remote get-url origin)"
else
  git remote add origin "https://github.com/$REPO.git"
  echo "origin added: $(git remote get-url origin)"
fi

say "Pushing $BRANCH (about 820 MB the first time, so give it a few minutes)"
git push -u origin "$BRANCH"

if [ -n "$PASSWORD" ]; then
  say "The password the site asks for"
  gh secret set SITE_PASSWORD --body "$PASSWORD" --repo "$REPO"
  echo "SITE_PASSWORD set. It is a latch, not a lock: the media stays reachable by URL."
else
  say "No password given, so the site will be open"
  echo "To add one later:  gh secret set SITE_PASSWORD --repo $REPO"
fi

say "GitHub Pages"
if gh api "repos/$REPO/pages" >/dev/null 2>&1; then
  echo "already on"
else
  gh api -X POST "repos/$REPO/pages" -f build_type=workflow >/dev/null
  echo "turned on, building from the workflow"
fi

say "The build"
echo "The pages workflow runs on this push. Watch it with:"
echo "  gh run watch --repo $REPO"
echo "When it finishes the site is at:"
echo "  https://${OWNER}.github.io/${REPO#*/}/"

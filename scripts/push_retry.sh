#!/usr/bin/env bash
# Rebase onto origin/main and push, up to 3 attempts. Extra arguments go to `git pull` (e.g. -X theirs).
# A failed rebase is aborted so the work tree is never left mid-rebase, and the script exits 1 after the last
# failed attempt so the workflow run fails visibly (the old inline loop exited 0 after 3 failures).
set -u
attempts=3
for i in $(seq 1 "$attempts"); do
  if git pull --rebase "$@" origin main && git push; then
    exit 0
  fi
  echo "::warning::git pull --rebase / push failed (attempt $i of $attempts)"
  git rebase --abort 2>/dev/null || true
  [ "$i" -lt "$attempts" ] && sleep 5
done
echo "::error::push to main failed after $attempts attempts"
exit 1

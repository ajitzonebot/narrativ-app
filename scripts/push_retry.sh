#!/usr/bin/env bash
# Rebase onto origin/main and push, up to 3 attempts. Extra arguments go to `git pull` (e.g. -X theirs).
# A failed rebase is aborted so the work tree is never left mid-rebase, and the script exits 1 after the last
# failed attempt so the workflow run fails visibly (the old inline loop exited 0 after 3 failures).
#
# Token: public jobs check out with `persist-credentials: false`, so no earlier step can read a repo token from
# .git/config. The pushing step passes GIT_PUSH_TOKEN; it is given to this script's git calls only. A checkout that
# kept its credentials is used as it is.
#
# Packs: docs/data/packs/ is rewritten whole by the daily run, while the reader (narrativ/reader.py save) patches its
# rows into the same files on main. A rebase conflict ONLY in PUSH_MINE (default docs/data/packs/) keeps this run's
# copy; the reader re-attaches its rows at its next save (it resets to main and patches again), and the next daily build
# attaches them from data/reader/store.json. A conflict in any other file still fails the attempt.
set -u
attempts=3
mine="${PUSH_MINE-docs/data/packs/}"
auth=()
if [ -n "${GIT_PUSH_TOKEN:-}" ] && [ -z "$(git config --get-all http.https://github.com/.extraheader 2>/dev/null)" ]; then
  auth=(-c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GIT_PUSH_TOKEN" | base64 | tr -d '\n')")
fi

rebasing() { [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; }

# Inside a stopped rebase: keep this run's copy of conflicted files under $mine, continue; fail on any other conflict.
resolve_mine() {
  [ -n "$mine" ] && rebasing || return 1
  local n=0 f conflicted
  while rebasing; do
    n=$((n + 1)); [ "$n" -gt 100 ] && return 1
    conflicted=$(git diff --name-only --diff-filter=U)
    [ -n "$conflicted" ] || return 1
    while IFS= read -r f; do
      case "$f" in "$mine"*) ;; *) echo "conflict outside $mine: $f"; return 1 ;; esac
    done <<< "$conflicted"
    while IFS= read -r f; do
      # in a rebase, stage 3 ("theirs") is the commit being replayed: this run's work
      if git cat-file -e ":3:$f" 2>/dev/null; then git checkout --theirs -- "$f" && git add -- "$f"; else git rm -q -- "$f"; fi
    done <<< "$conflicted"
    echo "kept this run's copy of $(wc -l <<< "$conflicted") file(s) under $mine"
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true  # may stop again at the next commit
  done
  return 0
}

# App files to R2 (the Worker serves /data from R2 first): only AFTER the push succeeded, so R2 never runs ahead of git.
# Needs CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID in the step's env (otherwise skipped); never fails the step. A skipped or
# failed upload is safe: the Worker reads every file changed since R2's manifest commit from GitHub (narrativ/appsync.py).
app_r2() {
  [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ "${APP_R2:-1}" != "0" ] || return 0
  timeout 900 python3 -m narrativ.appsync || echo "::warning::app files to R2 did not finish (the Worker reads changed files from GitHub)"
}

for i in $(seq 1 "$attempts"); do
  if { git "${auth[@]}" pull --rebase "$@" origin main || resolve_mine; } && git "${auth[@]}" push origin HEAD:main; then
    app_r2
    exit 0
  fi
  echo "::warning::git pull --rebase / push failed (attempt $i of $attempts)"
  git rebase --abort 2>/dev/null || true
  [ "$i" -lt "$attempts" ] && sleep 5
done
echo "::error::push to main failed after $attempts attempts"
exit 1

#!/usr/bin/env bash
# One commit step for every job that publishes data (narrativ/databranch.py, README "Data branch").
#
#   bash scripts/publish.sh -m "data: ..." [--mine all|PREFIX] [--gate] [--no-picks] [--archive] -- PATH...
#
# DATA_STAGE (Actions variable, default 0):
#   0     today's step: git add PATHS, nothing staged -> exit 0, [gate], commit, scripts/push_retry.sh
#         (--mine all = push_retry.sh -X theirs; --archive = ARCHIVE_R2=1 for push_retry.sh)
#   1, 2  the same, then `databranch follow` (the data branch copies main's data paths; never fatal)
#   3+    data paths go to the data branch (`databranch commit`: gate, no rebase, appsync / archive from that commit);
#         anything else (RULES.md, theses.json, docs/research/*.md) is committed to main as at stage 0, without gate,
#         R2 upload or archive. Generated files are ignored on main from stage 3, so `git add` there skips them.
# A path that neither exists nor is tracked is left out (git add would fail on it).
set -u
msg=""; mine=""; gate=0; nopicks=0; archive=0
while [ $# -gt 0 ]; do
  case "$1" in
    -m) msg="$2"; shift 2 ;;
    --mine) mine="$2"; shift 2 ;;
    --gate) gate=1; shift ;;
    --no-picks) nopicks=1; shift ;;
    --archive) archive=1; shift ;;
    --) shift; break ;;
    *) echo "publish.sh: unknown option $1"; exit 2 ;;
  esac
done
[ -n "$msg" ] || { echo "publish.sh: -m MESSAGE is required"; exit 2; }
paths=()
for p in "$@"; do
  if [ -e "$p" ] || [ -n "$(git ls-files -- "$p" 2>/dev/null | head -1)" ]; then paths+=("$p"); fi
done
[ "${#paths[@]}" -gt 0 ] || { echo "publish.sh: nothing to publish (no given path exists)"; exit 0; }
stage="${DATA_STAGE:-0}"
case "$stage" in ''|*[!0-9]*) stage=0 ;; esac
here="$(cd "$(dirname "$0")" && pwd)"
pull_args=()
[ "$mine" = "all" ] && pull_args=(-X theirs)

to_main() {  # $1 = 1: run the gate and archive (stages 0-2); 0: plain commit of main-owned files (stage 3+)
  local full="$1" p add=()
  for p in "${paths[@]}"; do
    # stage 3+: a generated path is ignored on main (git add would refuse it); it went to the data branch above
    if [ "$full" = 0 ] && git check-ignore -q -- "$p"; then continue; fi
    add+=("$p")
  done
  [ "${#add[@]}" -gt 0 ] || return 0
  git add -A -- "${add[@]}" || return 1
  git diff --cached --quiet && return 0
  if [ "$full" = 1 ] && [ "$gate" = 1 ]; then
    if [ "$nopicks" = 1 ]; then python3 "$here/publish_gate.py" --no-picks || return 1; else python3 "$here/publish_gate.py" || return 1; fi
  fi
  git commit -m "$msg" || return 1
  if [ "$full" = 1 ]; then
    # stage 2: the app reads the data branch; R2 is uploaded from the data commit after `follow`, not from main
    local r2="${APP_R2:-1}"; [ "${APP_REF:-main}" = "data" ] && r2=0
    ARCHIVE_R2="$archive" APP_R2="$r2" bash "$here/push_retry.sh" "${pull_args[@]}"
  else
    APP_R2=0 ARCHIVE_R2=0 bash "$here/push_retry.sh" "${pull_args[@]}"
  fi
}

if [ "$stage" -lt 3 ]; then
  to_main 1 || exit 1
  if [ "$stage" -ge 1 ]; then
    python3 -m narrativ.databranch follow || echo "::warning::data branch did not follow main (run: python -m narrativ.databranch resync --from main)"
  fi
  exit 0
fi

# stage 3+: data paths to the data branch first (the app's data), then the rest to main
dargs=(-m "$msg")
if [ -n "$mine" ]; then dargs+=(--mine "$mine"); fi
[ "$nopicks" = 1 ] && dargs+=(--no-picks)
[ "$archive" = 1 ] && dargs+=(--archive)
python3 -m narrativ.databranch commit "${dargs[@]}" "${paths[@]}" || exit 1
to_main 0 || exit 1
exit 0

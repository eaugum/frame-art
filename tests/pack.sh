#!/bin/bash
# The source as a tar on stdout, for a container from the test image (scripts/check.sh, tests/serve_page.sh). It's
# streamed rather than bind-mounted, since Colima's mount shows a file that was just replaced as missing for a while.
# In a git checkout: the files git has and the new ones it doesn't ignore. Elsewhere (an exported copy): frame_art and
# tests without the names in .gitignore. In both, never the tokens, options and state below. Says which on stderr.
# tests/pack.sh more.tar adds what's in more.tar.
set -euo pipefail
extra=()
if [ -n "${1:-}" ]; then
  [ -f "$1" ] || { echo "tests/pack.sh: no such tar to add: $1" >&2; exit 1; }
  extra=("@$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")")
fi
cd "$(dirname "$0")/.."
SECRETS=(token.txt stasera_token.txt options.json settings.json 'state.json*' next.jpg)  # file names; and out/
list=$(mktemp "${TMPDIR:-/tmp}/frameart-pack.XXXXXX")
trap 'rm -f "$list"' EXIT
pack() { tar --no-xattrs --no-mac-metadata -cf - "$@"; }  # without macOS's extended attributes

secret() {
  local p
  case "/$1" in */out/*) return 0 ;; esac
  for p in "${SECRETS[@]}"; do
    case "${1##*/}" in $p) return 0 ;; esac  # unquoted: state.json* is a pattern
  done
  return 1
}

if [ "$(git rev-parse --show-toplevel 2>/dev/null)" = "$(pwd -P)" ]; then
  git ls-files -z --cached --others --exclude-standard | while IFS= read -r -d '' f; do
    if [ -e "$f" ] && ! secret "$f"; then printf '%s\0' "$f"; fi  # not those deleted and not yet committed
  done > "$list"
  echo "source: git ls-files, $(tr -cd '\0' < "$list" | wc -c | tr -d ' ') files" >&2
  pack --null -T "$list" ${extra[@]+"${extra[@]}"}
else
  excludes=(--exclude out)
  for p in "${SECRETS[@]}"; do excludes+=(--exclude "$p"); done
  if [ -f .gitignore ]; then
    while IFS= read -r p || [ -n "$p" ]; do
      p=${p%$'\r'}
      p=${p#"${p%%[![:space:]]*}"}
      p=${p%"${p##*[![:space:]]}"}
      p=${p#/}
      p=${p%/}
      case "$p" in "" | "#"*) continue ;; esac
      excludes+=(--exclude "$p")
    done < .gitignore
  fi
  echo "source: no git checkout here, so frame_art and tests without .gitignore's names" >&2
  pack "${excludes[@]}" frame_art tests ${extra[@]+"${extra[@]}"}
fi

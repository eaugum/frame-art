#!/bin/bash
# Every check before a push: the tests in the add-on's Python (3.12, in Docker, without network), every module
# importing, the version, the add-on's YAML and the page's JavaScript. Ends with "All checks passed." or exits non-zero.
# The YAML is parsed with Ruby (macOS has it); without Ruby it fails, unless FRAMEART_SKIP_YAML=1.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
IMAGE=frameart-test
work=$(mktemp -d "${TMPDIR:-/tmp}/frameart-check.XXXXXX")
trap 'rm -rf "$work"' EXIT

step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

step "The page's JavaScript (node --check)"
node=$(command -v node || ls -d "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | tail -1 || true)
[ -n "$node" ] || fail "no node on PATH or in ~/.nvm"
page=frame_art/frameart/page.html
[ "$(grep -c '<script' "$page")" = 1 ] || fail "$page should have one <script>"
# blank lines outside the script, so node's line numbers are page.html's
awk '/<script>/ { inside = 1; print ""; next } /<\/script>/ { inside = 0 } { print inside ? $0 : "" }' "$page" \
  > "$work/page.js"
"$node" --check "$work/page.js" || fail "$page: the script doesn't parse (line numbers are page.html's)"
echo "ok ($("$node" --version))"

step "The add-on's YAML (parsed with Ruby's YAML)"
yaml=()  # the parsed YAML goes in with the source, for the tests
if command -v ruby >/dev/null; then
  mkdir "$work/.check"
  (cd frame_art && ruby -ryaml -rjson -e 'puts JSON.generate(ARGV.map { |f| [f, YAML.load_file(f)] }.to_h)' \
    config.yaml translations/*.yaml) > "$work/.check/yaml.json" || fail "the add-on's YAML doesn't parse"
  tar --no-xattrs --no-mac-metadata -cf "$work/yaml.tar" -C "$work" .check
  yaml=("$work/yaml.tar")
  echo "ok (config.yaml, $(cd frame_art && echo translations/*.yaml))"
elif [ "${FRAMEART_SKIP_YAML:-}" = 1 ]; then
  echo "SKIPPED: no ruby, and FRAMEART_SKIP_YAML=1"
else
  fail "no ruby to parse the YAML with; FRAMEART_SKIP_YAML=1 goes on without it"
fi

step "The test image ($IMAGE, the add-on's requirements)"
tar --no-xattrs --no-mac-metadata -cf - -C tests Dockerfile -C "$ROOT/frame_art" requirements.txt \
  | docker build -q -t "$IMAGE" - || fail "couldn't build $IMAGE"

step "Tests, imports, version, YAML structure and texts (Python 3.12, no network)"
env=()
[ ${#yaml[@]} = 1 ] && env=(-e FRAMEART_YAML=/src/.check/yaml.json)
echo "+ tests/pack.sh ${yaml[*]:-} > source.tar"
tests/pack.sh ${yaml[@]+"${yaml[@]}"} > "$work/source.tar" || fail "couldn't pack the source (tests/pack.sh)"
tests='tar -xf - --no-same-owner && python --version && python -m unittest discover -s tests -v'
echo "+ docker run --rm -i --network none ${env[*]:-} $IMAGE sh -c '$tests' < source.tar"
docker run --rm -i --network none ${env[@]+"${env[@]}"} "$IMAGE" sh -c "$tests" < "$work/source.tar" || fail "the tests"

if [ ${#yaml[@]} = 1 ]; then
  printf '\nAll checks passed. (%ds)\n' "$SECONDS"
else
  printf '\nAll checks passed, but the YAML was SKIPPED: not parsed, no ruby (FRAMEART_SKIP_YAML=1). (%ds)\n' "$SECONDS"
fi

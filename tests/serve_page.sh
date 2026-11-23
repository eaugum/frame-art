#!/bin/bash
# The add-on's page on http://127.0.0.1:$PORT/ (18099 by default) against fakes (tests/serve_page.py), in a container
# from the test image that scripts/check.sh builds. "tests/serve_page.sh stop" stops it.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=frameart-test-page
PORT=${PORT:-18099}

docker rm -f "$NAME" >/dev/null 2>&1 || true
[ "${1:-}" = stop ] && exit 0
docker image inspect frameart-test >/dev/null 2>&1 || { echo "no frameart-test image: run scripts/check.sh" >&2; exit 1; }

# the source copied in (tests/pack.sh), not mounted
echo "+ docker create --rm --name $NAME -p 127.0.0.1:$PORT:8099 frameart-test python tests/serve_page.py"
docker create --rm --name "$NAME" -p "127.0.0.1:$PORT:8099" frameart-test python tests/serve_page.py >/dev/null
echo "+ tests/pack.sh | docker cp - $NAME:/src && docker start $NAME"
tests/pack.sh | docker cp - "$NAME:/src" >/dev/null && docker start "$NAME" >/dev/null \
  || { docker rm -f "$NAME" >/dev/null 2>&1; exit 1; }
for _ in $(seq 40); do
  if curl -sf -o /dev/null "http://127.0.0.1:$PORT/"; then
    echo "http://127.0.0.1:$PORT/ (logs: docker logs $NAME; stop: tests/serve_page.sh stop)"
    exit 0
  fi
  sleep 0.5
done
docker logs "$NAME" >&2 || true
docker rm -f "$NAME" >/dev/null 2>&1 || true
echo "the page didn't answer on 127.0.0.1:$PORT" >&2
exit 1

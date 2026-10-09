#!/bin/sh
# Run the overlay's unit tests against the pristine pinned packages (Dockerfile.v3 stage `odp`).
set -eu
cd "$(git rev-parse --show-toplevel)"
docker build -q -f Dockerfile.v3 --target odp -t openbq-odp-test . >/dev/null
exec docker run --rm -v "$PWD:/src:ro" -w /src openbq-odp-test sh -c \
  'python provider-fixes/apply.py && python -m unittest discover -s provider-fixes/tests "$@"' sh "$@"

#!/bin/sh
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# Run the overlay's unit tests against the pristine pinned packages (Dockerfile stage `odp`).
set -eu
cd "$(git rev-parse --show-toplevel)"
docker build -q --target odp -t openbq-odp-test . >/dev/null
exec docker run --rm -v "$PWD:/src:ro" -w /src openbq-odp-test sh -c \
  'python provider-fixes/apply.py && python -m unittest discover -s provider-fixes/tests "$@"' sh "$@"

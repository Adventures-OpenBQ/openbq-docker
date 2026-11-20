#!/bin/sh
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# Build the pinned release image, applying its guarded overlay, then run source tests.
set -eu
cd "$(git rev-parse --show-toplevel)"
test_image="${OPENBQ_TEST_IMAGE:-openbq-provider-tests}"
docker build -q -t "$test_image" . >/dev/null
exec docker run --rm -v "$PWD:/src:ro" -w /src "$test_image" \
  python -m unittest discover -s provider-fixes/tests "$@"

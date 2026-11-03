#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
artifacts=${1:?Provide a new protected task artifact directory}
: "${DOCKER:=docker}"
: "${PYTHON:=python3}"
cd "$root"
"$PYTHON" v11/prepare-provider-build.py --eodhd ../openbq-eodhd-v11 --yfinance ../openbq-yfinance-v11 --build --tag openbq-task51:fixture
"$DOCKER" run --rm --network none -v "$root/v11/settings/tests:/tests:ro" --entrypoint python openbq-task51:fixture /tests/test_contracts.py
"$PYTHON" v11/settings/tests/verify_fixture.py --artifacts "$artifacts"
"$DOCKER" run --rm --network none -v "$root:/work:ro" -w /work/funnel-gateway node:22 npm test
"$DOCKER" run --rm --network none -v "$root/../bdobb-v11:/work:ro" -w /work node:22 node --test web/security.test.mjs

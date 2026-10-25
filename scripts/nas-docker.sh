#!/bin/sh
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# QNAP SSH shells may omit Container Station from PATH or have unwritable HOME.
set -eu
if command -v docker >/dev/null 2>&1; then
  docker_bin=$(command -v docker)
else
  docker_bin=''
  for candidate in /share/*/.qpkg/container-station/bin/docker; do
    if [ -x "$candidate" ]; then docker_bin=$candidate; break; fi
  done
  test -n "$docker_bin" || { echo 'Docker not found' >&2; exit 1; }
fi
export DOCKER_CONFIG="${DOCKER_CONFIG:-$(pwd)/.docker}"
mkdir -p "$DOCKER_CONFIG"
exec "$docker_bin" "$@"

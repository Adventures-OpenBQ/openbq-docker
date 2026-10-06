#!/usr/bin/env bash
# Run from a second trusted device, never from the Docker host.
set -euo pipefail
host="${1:?usage: verify-isolation.sh <actual-tailnet-hostname>}"
curl --fail --silent --show-error --max-time 30 "https://$host/widgets.json" >/dev/null
# Any TCP listener is a failure, even if it returns an HTTP error.
if nc -z -w 5 "$host" 6900; then
  echo 'FAIL: raw API TCP port 6900 is reachable' >&2
  exit 1
fi
printf 'PASS: HTTPS catalogue reachable; raw API port 6900 unreachable.\n'

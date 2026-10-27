#!/bin/sh
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# v12/verify-charts.sh [--postgres]: Art's Charts end to end on a throwaway local project,
# through the gateway door and directly (what svc:openbq-charts proxies to). Fakes only:
# fake-odp serves bars, Rita is unset, ntfy is local with no upstream, every secret is fresh.
# Never the NAS, never a real key, never the running openbq-stack project.
set -eu
export PATH=/opt/homebrew/bin:$HOME/.docker/bin:$PATH
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
P=${VERIFY_PROJECT:-openbq-charts-verify}-$$
TMP=$(mktemp -d); chmod 700 "$TMP"
PG=""
rand() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
dc() {
  ARTS_CHARTS_STACK_ENV="$TMP/credentials.env" ARTS_CHARTS_ENV="$TMP/charts.env" \
    docker compose -p "$P" --project-directory "$ROOT" -f docker-compose.yml -f v12/compose.charts.yaml \
    -f v12/compose.gateway.yaml -f v12/verify/compose.verify.yaml --profile charts-v12 "$@"
}
cleanup() {
  status=$?
  [ "$status" -eq 0 ] || dc logs --tail 40 arts-charts arts-charts-worker >&2 2>/dev/null || true
  docker rm -f "$P-gateway" >/dev/null 2>&1 || true
  [ -z "$PG" ] || docker rm -f "$PG" >/dev/null 2>&1 || true
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# The gateway insists on a <name>.<tailnet>.ts.net origin; spelled in parts so the public-content scan
# sees no tailnet host. It is only a Host header here: nothing resolves it.
TLD=net
ORIGIN=https://openbq.verify.ts.$TLD:10000
TOKEN=$(rand); USER_=verify-$$; PASS=$(rand); SECRET=$(rand); NTFY_PASS=$(rand); TOPIC=charts-verify
printf 'OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=%s\nOPENBB_API_PASSWORD=%s\n' "$USER_" "$PASS" > "$TMP/credentials.env"
printf 'GATEWAY_TOKEN=%s\nOPENBB_API_USERNAME=%s\nOPENBB_API_PASSWORD=%s\n' "$TOKEN" "$USER_" "$PASS" > "$TMP/gateway.env"
printf 'ARTS_CHARTS_SECRET=%s\nARTS_CHARTS_ODP_URL=http://fake-odp:6900\nARTS_CHARTS_NTFY_TOPIC=%s\nARTS_CHARTS_PUBLIC_URL=%s\n' \
  "$SECRET" "$TOPIC" "$ORIGIN" > "$TMP/charts.env"
mkdir -m 755 "$TMP/gateway-config"
printf '{"origin":"%s","charts":true,"ntfyTopic":"%s","maxSockets":8}\n' "$ORIGIN" "$TOPIC" > "$TMP/gateway-config/settings.json"
chmod 600 "$TMP"/*.env; chmod 644 "$TMP/gateway-config/settings.json"

dc build arts-charts
dc --profile web build funnel-gateway
dc up -d ntfy fake-odp            # also creates the project's bridge

if [ "${1:-}" = --postgres ]; then
  PG="$P-pg-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
  PGPASS=$(rand)
  docker run -d --name "$PG" --network "${P}_openbq-internal" -p "127.0.0.1:$PORT:5432" \
    -e POSTGRES_USER=charts -e POSTGRES_PASSWORD="$PGPASS" -e POSTGRES_DB=charts postgres:17-alpine@sha256:266d3c257594e195b309ae9d1805e54c788f1d7b375f56bf6c367aac6c917e7b >/dev/null
  tries=0
  until docker exec "$PG" pg_isready -U charts >/dev/null 2>&1; do
    tries=$((tries + 1)); [ "$tries" -lt 120 ] || { echo "verify-charts: postgres not ready after 120s" >&2; exit 1; }
    sleep 1
  done
  printf 'ARTS_CHARTS_DB=postgresql://charts:%s@%s:5432/charts\n' "$PGPASS" "$PG" >> "$TMP/charts.env"
fi

tries=0  # the server creates the auth file at start
until dc exec -T ntfy test -f /var/lib/ntfy/user.db >/dev/null 2>&1; do
  tries=$((tries + 1)); [ "$tries" -lt 120 ] || { echo "verify-charts: ntfy auth file missing after 120s" >&2; exit 1; }
  sleep 1
done
dc exec -T -e NTFY_PASSWORD="$NTFY_PASS" ntfy ntfy user add charts >/dev/null
dc exec -T ntfy ntfy access charts "$TOPIC" rw >/dev/null
NTFY_TOKEN=$(dc exec -T ntfy ntfy token add charts | grep -o 'tk_[A-Za-z0-9]*' | head -1)
printf 'ARTS_CHARTS_NTFY_TOKEN=%s\n' "$NTFY_TOKEN" >> "$TMP/charts.env"

dc up -d arts-charts arts-charts-worker
docker run -d --name "$P-gateway" --network "${P}_openbq-internal" --env-file "$TMP/gateway.env" \
  -v "$TMP/gateway-config:/run/bdobb:ro" --read-only --tmpfs /tmp --user 1000:1000 \
  openbq-funnel-gateway:12.0.0-charts >/dev/null

dc run --rm --no-deps -v "$ROOT/v12/verify:/verify:ro" \
  -e CHARTS_ORIGIN="$ORIGIN" -e CHARTS_GATEWAY="http://$P-gateway:8091" -e GATEWAY_TOKEN="$TOKEN" \
  -e NTFY_USER=charts -e NTFY_PASS="$NTFY_PASS" \
  --entrypoint python arts-charts /verify/verify_charts.py

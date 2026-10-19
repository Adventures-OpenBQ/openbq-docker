<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# key-maint

Transport-tiered OpenBB widget reporting provider API key state: the "key
status" widget from *Adventures in OpenBQ, Episode 3*, and the backend behind
BDOBB's **Settings ▸ Provider API Keys**.

The idea: **what you can see depends on how you connected.** Same service,
three postures:

| Tier | How you connect | Sees |
|---|---|---|
| 1 | anything forwarded from outside the tailnet | key status + demo flag |
| 2 | `https://openbq-keys.<your-tailnet>.ts.net` from a tailnet device, or `http://127.0.0.1:8447` on the host | + `run_tests` live probes |
| 3 | Unix socket on the host, via an SSH exec session | + the key values, and writing a key |

**Auth follows the API.** key-maint reads the same `credentials.env` as the
API. While `OPENBB_API_AUTH` is off the API is open and so is key-maint; when
it is on, every tier (tier 3 included) needs the API's own
`OPENBB_API_USERNAME` / `OPENBB_API_PASSWORD`, and an empty username or
password denies everything. A missing `credentials.env` also denies
everything. Tier 1 never shows a key's value, only whether it is set.

What tier 3 does not have is a **port**: the admin server binds a **unix
socket** in a host directory you create with mode 0700, so being able to open
that file is what raises a caller to tier 3. The filesystem stands in for a
second credential; there is no separate admin password to store, leak or
rotate.

## Deploy

key-maint is part of the Episode 3 overlay (`docker-compose.v3.yml`).

1. One-time, beside the compose files:
   `mkdir -p key-maint-admin && chmod 700 key-maint-admin`
2. `docker compose -f docker-compose.yml -f docker-compose.v3.yml up -d key-maint`
   (builds `openbq-key-maint:10.0.0` from this directory the first time; add
   `--build` to rebuild it after a change).
3. On the host it answers on `http://127.0.0.1:8447` only. That port is
   loopback-only, so the compose file sets `KEYMAINT_DIRECT_TIER=2`: a direct,
   un-forwarded caller (the host itself) gets live tests. Without it a direct
   caller is tier 1. It cannot be raised to 3.
   Docker Desktop on macOS cannot chmod a unix socket on a bind-mounted host
   folder, so key-maint exits at start there. On a Mac, mount a named volume
   at `/config/admin` instead of `./key-maint-admin`; tier 3 is then reached
   with `docker exec`, which is the same host-level privilege.
4. Tailnet (optional): create the Tailscale Service `svc:openbq-keys` in your
   tailnet's admin console and approve this node as its host, replace
   `<your-tailnet>` in `ts-config/serve-v3-keys.json`, then point the
   `tailscale` service's `TS_SERVE_CONFIG` at `/config/serve-v3-keys.json`.
   That file is `serve-v3.json` plus the Service; it is tailnet-only and never
   funneled. Until the Service exists, keep `serve-v3.json`.
   With the Episode 6 overlay (`docker-compose.v6.yml`), use
   `ts-config/serve-v6-keys.json` instead: `serve-v6.json` plus the same Service, or
   `ts-config/serve-v6-services.json`, which also names Rita and MCP (README, Episode 6).

## Use

- **BDOBB:** add `http://127.0.0.1:8447` (on the host) or
  `https://openbq-keys.<your-tailnet>.ts.net` as a connection, with the same
  Authorization header as the API when its auth is on. `widgets.json` carries
  `provider_api_keys_settings`, a `type: "settings"` entry that puts the keys
  panel in BDOBB's **Settings** dialog as **Provider API Keys**, one section
  per key-maint connection. It also serves the key status widgets for the
  library. OpenBB Workspace ignores the settings type.
- **Tier 3 (values, writing a key):** run curl on the host over SSH; it never
  opens a forwarded channel, so the host's sshd forwarding policy does not
  matter:

      ssh <host> "curl -s -u <api-user>:<api-password> \
        --unix-socket <stack-dir>/key-maint-admin/key-maint-admin.sock \
        http://localhost/keys"

  (Drop `-u` while the API's auth is off.) If your sshd permits streamlocal
  forwarding:
  `ssh -L 18446:<stack-dir>/key-maint-admin/key-maint-admin.sock <host>` →
  `http://localhost:18446`. `scripts/smoke_live.py` needs this `-L` form.
  A written key reaches the API at its next restart.

## Provider connectivity

In addition to the credential probes above, key-maint reads the OpenBB
API's own provider inventory (`GET /providers.json`) and can round-trip a
real request through the API itself. `OPENBB_API_URL` (default
`http://openbq-api:6900` on the compose bridge network) tells it where; the
compose service declares `depends_on: [openbq-api]` so key-maint starts after
the API it talks to.

- **`GET /keys?run_tests=true`, tier ≥ 2** — now fires BOTH probe kinds per
  provider: the existing vendor-direct **credential** check, and a new
  **connectivity** check that sends the provider's one stored example
  request (`app/catalog.py::EXAMPLES`) through the OpenBB API rather than
  straight to the vendor. A provider's `checks` array in the response
  carries both; `test` is the worse of the two.
- **`GET /providers/{provider_id}/test`** — tier ≥ 2. Fires the
  connectivity check alone for one provider, addressed by its OpenBB
  provider id (e.g. `fmp`, `sec`) rather than an env var — the per-row
  "test this service" action for keyless providers and for providers the
  local registry hasn't learned yet. 404 for an unknown provider id or one
  with no stored example; 403 below tier 2.
- **`GET /keys/{env_var}/test`** — same route as before, but now also runs
  the connectivity check alongside the credential check when the provider
  is installed on the backend, has a stored example, and has a value set.


## Release check

`python -m app.catalog --check <OPENBB_URL>` runs every stored example
(`app/catalog.py::EXAMPLES`) against a live OpenBB API and enforces the
demo policy: every example marked `demo_ok=True` must classify `ok` (its
public demo key still works), and every other (keyed) example must
classify `ok`, `auth_failed`, or `skipped` — `ok` passes there too because
a keyed example run against a deployment that HAS real keys configured
legitimately succeeds; that is not drift, just a live key doing its job.
Any other result (`no_response`, or an `error` such as
`unexpected_response`, `rate_limited`, or `upstream_error`) counts as
drift and fails the check. A drifted vendor call — a changed endpoint, a
symbol that stopped returning data, a demo key that expired — fails the
release cut. The fix is to update that example, and its `doc` URL, in
`app/catalog.py`, not to loosen the check. A failure can also mean the
classifier itself doesn't recognize a real API error shape (the marker
matching in `app/catalog.py::_marker_code`) — in that case the fix is to
add the missing marker there, not to touch the example. Auth for the check
comes from `KEYMAINT_AUTH_FILE` (default `/config/credentials.env`).


## Test

    pip install -e . && pytest

The suite mocks all probes; nothing needs a live deployment.

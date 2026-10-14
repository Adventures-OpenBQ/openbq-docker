<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# funnel-gateway (openbq-docker v8.0.0, `web` profile)

The door the sidecar publishes on Funnel port 8443 for BDOBB's browser (web) preview. Port 443
stays `openbq-api` for your tailnet and is never funneled. Ported from bdobb-dev/openbb-docker
**v8.0.3** (`775354f`, `funnel-gateway/`, Apache-2.0) with the `/ai` (Rita) family and its SOCKS5
dialer removed; the route contract is otherwise unchanged, so BDOBB's vendored `web/policy.mjs`
and this `policy.mjs` agree byte for byte on what is admitted.

## Isolation and lock-first

`funnel-gateway` and `rss-ticker` are compose services under `profiles: [web]`: `docker compose
up -d` never starts them; `docker compose --profile web up -d` does. The gateway joins the
`openbq-internal` bridge, listens on `0.0.0.0:8091` with no host port, and is reached only through
Tailscale Serve. It runs `read_only`, as uid 1000, `cap_drop: [ALL]`, 256 MB, 64 pids; its only
writable mount is the `gateway-state` volume behind `/state`.

Nothing is public until two separate steps both happen: the profile is started, **and** the
sidecar's Serve config is swapped to `ts-config/serve-funnel.json` (a deliberate copy over
`ts-config/serve.json`, never automatic). Before the swap, run both preflights below. The API's
own lock must be on first: `OPENBB_API_AUTH=true` with a Basic pair in `credentials.env`;
`check-upstreams.mjs` refuses to pass an open API.

## Routes

Every request, including health, needs exactly one `Authorization: Bearer <GATEWAY_TOKEN>`
(timing-safe). `Host` must be the configured `origin`; an `Origin`, if present, must equal it.
Caller headers, cookies and credentials are never relayed.

| Route | Method | What happens |
|---|---|---|
| `/_gateway/health` | GET | `200 {"ok":true}` behind the lock |
| `/api/widgets.json`, `/api/apps.json` | GET | openbq-api's root documents with the Basic pair injected; no query; not metered daily |
| `/api/api/v1/**` | GET | under the shape bounds (lowercase route ≤ 200 chars, ≤ 40 query pairs, name grammar, ≤ 1024-char values, no control characters, ≤ 4096 chars leaving), query re-serialised; one unit of `quoteDailyLimit` |
| `/api/api/v1/calendar/trading` | GET | only `exchange=<MIC>&year=1990..2040` |
| `/news/api/news?feed_id=<id>&limit=<1-50>` | GET | rss-ticker's history page for **one approved feed id**; no credential |
| `/news/ws/news` | GET + Upgrade | the wire's socket (below); `503` until `feeds` names a feed |
| `/state/<digits>` | GET | the user's saved files `{files: {name: text}}` |
| `/state/<digits>/<file>` | PUT, DELETE | one of the app's JSON stores (`policy.mjs` `stateFile`); 256 KiB a file, 2 MiB and 200 files a user; `application/json` only |
| `/ai/**` | — | not served by openbq-docker: 404 (POST 405) |
| everything else | — | 404 |

Budgets (settings): `requestsPerMinute` (default 60, ≤ 600), `maxConcurrent` (8, ≤ 32),
`maxSockets` (4, ≤ 32), `quoteDailyLimit` (100, ≤ 10000, UTC day). A socket costs six units,
charged before the upgrade. Counters are in memory and reset on restart; keep one instance.

## The wire (`/news`)

`feeds` in `settings.json` maps each **approved** feed URL to its rss-ticker id. It is the whole
access control: rss-ticker has no authentication, and the door takes no feed URL from any caller.
`/news/api/news` names a feed only by an approved id; the socket's single subscription frame
`{"subscribe":[{"url":…}]}` (1–50 unique urls, no other key) is rebuilt from the approved urls
alone, unapproved ones dropped, and closed if none is left. A second frame, a binary or oversized
frame closes it. The upstream opens only after a valid frame; a socket lives at most 240 s and
must send its frame within 10 s; frames are capped at 64 KiB.

```json
{
  "rssOrigin": "https://openbq.YOUR-TAILNET.ts.net:8088",
  "rssAddress": "<the tailnet IPv4 rssOrigin resolves to>",
  "feeds": { "https://feeds.example.com/news.xml": 7 }
}
```

The gateway dials rss-ticker by its **tailnet HTTPS name** (`rssOrigin`, port 8088 as
`ts-config/serve-funnel.json` publishes it, or portless) at the **pinned tailnet IPv4**
`rssAddress`, never `http://rss-ticker:8088`: the pool may move to another node without the
contract changing. A bridge container reaches the tailnet CGNAT range only if the host routes it; check
before configuring the three keys (200 or 401 = routable):

```sh
docker run --rm --network openbq-episode1_openbq-internal curlimages/curl \
  -s -o /dev/null -w '%{http_code}\n' --max-time 5 \
  --resolve "openbq.<tailnet>.ts.net:8088:<rssAddress>" \
  "https://openbq.<tailnet>.ts.net:8088/api/news?feed_id=<an approved id>&limit=1"
```

If it is not routable, leave the three keys unset: the door serves `/api` and `/state`, and the
two `/news` routes answer 404/503.

## Socket tickets

A browser cannot carry the machine token on a WebSocket, so BDOBB's web layer (which checked the
GitHub session) signs a ticket and the browser opens
`wss://<origin>/news/ws/news?ticket=<expiry>.<nonce>.<sig>` directly:

- `expiry`: 13-digit epoch ms, at most 30 s ahead; `nonce`: 16 random bytes, base64url (22);
  `sig`: base64url (43) of `HMAC-SHA256(K, "<expiry>.<nonce>.<target>")` with
  `K = HMAC-SHA256(GATEWAY_TOKEN, "bdobb socket ticket v1")`; `target` is the canonical path and
  query `socketTarget()` returns (only `/news/ws/news`).
- The ticket is the last parameter, spelled literally, once; the request carries no
  `Authorization` and `Origin: <previewOrigin>`. Each nonce is admitted once. Tickets are off
  until `previewOrigin` is set.

## Configuration

- `gateway.env` (from `gateway.env.example`, `chmod 600`): `GATEWAY_TOKEN` (32–256 base64url;
  the web preview's `BACKEND_GATEWAY_TOKEN`), and `OPENBB_API_USERNAME`/`OPENBB_API_PASSWORD`,
  the same pair as in `credentials.env` (repeated so the gateway never loads provider keys).
- `gateway-config/settings.json` (from `funnel-gateway/settings.example.json`, read-only bind):
  `origin` (`https://openbq.<tailnet>.ts.net:8443`), `previewOrigin`, `stateDir`
  (`/var/lib/bdobb/state` to turn `/state` on), the budgets, and `rssOrigin`/`rssAddress`/`feeds`
  (both-or-neither; feeds need them). An unknown key, including Rita's `ritaOrigin`,
  `ritaAddress` and `socksProxy`, is refused at startup.
- `rss-ticker-config/config.yaml` (from `config.yaml.example`).

## Verification

```sh
docker compose --profile web up -d
docker compose --profile web exec funnel-gateway node check-upstreams.mjs  # API pair works, API locked, wire answers
docker compose --profile web exec funnel-gateway node verify.mjs           # the door's own lock, on the bridge
cp ts-config/serve-funnel.json ts-config/serve.json.new && jq empty ts-config/serve.json.new && mv ts-config/serve.json.new ts-config/serve.json   # the door opens; the sidecar live-applies it, and a malformed file would kill it
docker compose --profile web exec -e GATEWAY_URL=https://openbq.<tailnet>.ts.net:8443 funnel-gateway node verify.mjs
```

`git checkout ts-config/serve.json` and a sidecar restart close the door again. Then test from a
device off the tailnet. Neither preflight queries a quote, subscribes to a feed or prints a credential. Tests: `cd
funnel-gateway && npm ci --ignore-scripts && npm test`.

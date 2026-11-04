# v12 Art's Charts runbook

Art's Charts (arts-charts) is opt-in: nothing here changes the default stack. Run every
command from the repository root. `v12/verify-charts.sh` runs the whole path with fakes and
is the reference for each step.

## 1. Build

```sh
docker compose -f docker-compose.yml -f v12/compose.charts.yaml --profile charts-v12 build
```

The image is `openbq-arts-charts:12.0.0`, built from the vendored tree in `v12/arts-charts`
(pin and licence in `v12/arts-charts.lock.json`). It is never pulled.

## 2. Settings

```sh
cp v12/charts.env.example v12/charts.env && chmod 600 v12/charts.env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'   # paste as ARTS_CHARTS_SECRET
```

`charts.env` is read after `credentials.env` (the stack's Basic pair, with
`OPENBB_API_AUTH=true`). Set `ARTS_CHARTS_SECRET`, `ARTS_CHARTS_NTFY_TOPIC`,
`ARTS_CHARTS_NTFY_TOKEN` (step 3) and `ARTS_CHARTS_PUBLIC_URL` (step 7).

In the repository's `.env` (not `charts.env`), set the two ntfy values for iOS delivery:

```
NTFY_BASE_URL=<the one door the phone subscribes through>
NTFY_UPSTREAM_BASE_URL=https://ntfy.sh
```

ntfy has one base URL, and iOS wakeups are keyed on it, so pick one door for the phone. Leave
both empty for a stack that must never call out. Which door works in the ntfy app is the
pending phone check in step 11.

## 3. ntfy account and topic

ntfy runs deny-all with one account and one topic. Start ntfy once so it creates its auth
file, then:

```sh
TOPIC=<topic>   # the topic name chosen below
read -rs NTFY_PASSWORD; export NTFY_PASSWORD
docker compose -f docker-compose.yml -f v12/compose.charts.yaml --profile charts-v12 up -d ntfy
docker compose ... exec -T -e NTFY_PASSWORD ntfy ntfy user add charts
docker compose ... exec -T ntfy ntfy access charts "$TOPIC" rw
docker compose ... exec -T ntfy ntfy token add charts      # prints tk_...: ARTS_CHARTS_NTFY_TOKEN
```

(`docker compose ...` is the same `-f` and `--profile` flags as above.) Use a topic name
that is hard to guess, and set it as `ARTS_CHARTS_NTFY_TOPIC` and in the gateway's
`ntfyTopic`. Keep the password for the phone; the worker uses the token.

## 4. Start

```sh
docker compose -f docker-compose.yml -f v12/compose.charts.yaml --profile charts-v12 up -d
```

With TemporalDB (`ARTS_CHARTS_TEMPORAL_URL` set), `temporaldb-api` and `openbq-v11` join
`openbq-internal` only through `v11/compose.gateway.yaml` or `v11/compose.tailnet.yaml`, so
apply `v12/compose.charts.yaml` after one of those. Point `ARTS_CHARTS_ODP_URL` at
`http://openbq-v11:6900` for TemporalDB-captured history. With the `live` profile, set
`ARTS_CHARTS_LIVE_GRID_URL=http://live-grid:6903`.

## 5. Gateway

Add `-f v12/compose.gateway.yaml` (after any v11 overlays, with `--profile web`) and set in
`gateway-config/settings.json`:

```json
{ "charts": true, "ntfyTopic": "<topic>" }
```

The gateway image is `openbq-funnel-gateway:12.0.0-charts`; `policy.mjs` is unchanged.
The door forwards arts-charts' own paths at its root, all behind `GATEWAY_TOKEN` and each
checked in `funnel-gateway/charts-policy.mjs`:

| Route | Methods |
|---|---|
| `/charts`, `/charts/{id}` (+ `/history`, `/restore/{n}`) | GET POST PUT DELETE as the route allows |
| `/charts/events` | GET (SSE) |
| `/charts/widgets.json`, `/charts/widgets/documents`, `/charts/widgets/alerts` | GET (BDOBB's companion widgets; read-only; no query. The bars widget is live-grid's, not on the door) |
| `/charts/mcp` | POST (MCP, 600 calls an hour per principal) |
| `/charts/{id}/snapshot.png`, `/charts/{id}/snapshots/{id}.png` | GET |
| `/charts/ws_ticket`, `/ta_series_ws` | the study socket's ticket and socket |
| `/series`, `/ta_registry`, `/ta_macros`, `/ta_snapshot` | GET |
| `/inbox`, `/inbox/{id}` (+ `/read`, `/snapshots/{n}.png`) | GET POST DELETE |
| `/watches`, `/schedules` | GET |
| `/ntfy/<topic>/json`, `/ntfy/<topic>/ws` | GET, before the lock, ntfy's own login |

Three routes are token-only: they carry a signed token instead of the gateway token and are
forwarded with no credential: `GET /inbox/{id}?t=`, `GET /inbox/{id}/snapshots/{n}.png?t=`
(an ntfy push's click and picture links) and `POST /watches/action` (the push buttons). A
forged button token is refused with a JSON 401, which the door relays. A forged link token is
refused by arts-charts with an empty-body 401; on these token-only routes the door relays that as 401, so an expired or forged push link shows as unauthorized. (On credentialed routes an empty-body 401 still shows as 502.) The `POST /watches/action` body is capped at 8 KiB.

## 6. Tailnet names

Create `svc:openbq-charts` and `svc:openbq-ntfy` (with the five v11 Services, seven in all) in
the admin console and approve the stack's tailscale node for them. Replace `<your-tailnet>`
in `ts-config/serve-v12.json`, then add `-f v12/compose.tailnet.yaml` after the v11 files.

## 7. Push address

`ARTS_CHARTS_PUBLIC_URL` is the base of every link and button in a push, and takes no path.
With the gateway's `"charts": true`, use the door origin:
`https://openbq.<your-tailnet>.ts.net:10000`. Without the gateway, use
`https://openbq-charts.<your-tailnet>.ts.net`.

## 8. Verify

```sh
v12/verify-charts.sh              # SQLite
v12/verify-charts.sh --postgres   # PostgreSQL
```

Both end with `verify-charts: all checks passed`. The script uses a throwaway project, fresh
secrets, a fake ODP, a local ntfy with no upstream and no key; it does not touch a running
stack's containers, volumes or networks and removes everything it created, but it does rebuild
the image tags `openbq-arts-charts:12.0.0` and `openbq-funnel-gateway:12.0.0-charts` on the host. Set `VERIFY_PROJECT=<prefix>` to name its compose
project and containers.

## 9. Re-pin

Re-pinning moves the vendored tree to a new arts-charts commit or tag. Update `source_commit` and `source_tree_sha256` in `v12/arts-charts.lock.json`, re-vendor `v12/arts-charts/source` from that commit, then rebuild (step 1) and re-run step 8.

## 10. Coordination and limits

- OpenPort's sidecar shares `openbq-internal`: keep service names unique there. It can therefore reach `arts-charts:8000` and `ntfy:2586` directly. That is acceptable: arts-charts demands the stack pair and ntfy is deny-all.
- ntfy counts every door caller as one visitor, the gateway's address. A flood of
  bad-credential requests at `/ntfy/...` can use up ntfy's per-visitor budget and lock the
  phone out too. If the phone stops receiving, check ntfy's logs for rate limiting and
  restart ntfy; keep the door reachable only over the tailnet or Funnel you trust.
- A forged or expired link token (`/inbox/...?t=`) and a forged button token (`/watches/action`) are both a 401 at the door.

## 11. Pending: phone check (plan Q8, Task 4 step 8)

PENDING for the user. Not done by the agent. After the stack runs on your machine with your
own tailnet: subscribe the ntfy app to `https://<door>:10000/ntfy` and to
`https://openbq-ntfy.<your-tailnet>.ts.net`, and press **Snapshot now** on a push. Record
which doors deliver. If the `/ntfy` path prefix does not work in the app, stop and ask before
changing anything. (The command-line path, through the gateway and directly to ntfy, is
verified by `v12/verify-charts.sh`; the iOS app is not.)

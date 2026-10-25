<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# v9: the openbb-eodhd port (ledger)

Episode 9. Branch `claude/openbq-docker-v9`, made from `claude/openbq-docker-v8`
a95969e. Local commits only. Nothing is pushed, tagged, built or deployed.

The donor is bdobb-dev/openbb-docker, read only. The base is v9.6.3 (99864f2), the
gateway contract that pairs with BDOBB v9.6.3. openbb-eodhd fixes are taken
through v9.6.6 (68afaa7). The two repositories share no git history, so every
carry is a hand port, and each commit names the donor commits it ports. This
line keeps its own OpenBB Platform 5.0 (openbb-core 2.0.1, `requirements.lock`).

## Ported paths

`openbb-eodhd/` on the donor maps to `v9/eodhd/source/` here.

| Path (under `v9/eodhd/source/`) | Donor commit(s) | Tag | Disposition |
|---|---|---|---|
| All 58 files of `openbb-eodhd/` at v9.6.3: package, models, tests, docs, `scripts/smoke.py`, LICENSE | 99864f2 (includes 25c63bd fiscal year/quarter fix, ed9bb9d and d162e85 economic calendar) | v9.6.3 | ADD, with key-hygiene edits (below) |
| `openbb_eodhd/aggregation.py`, `docs/aggregation-metadata.md`, `tests/test_aggregation.py`, `tests/test_widget_hints.py`; `models/{equity,crypto,currency}_historical.py`, `models/fundamental.py`, `README.md` (edits) | bbd67cd (PR #68), 9068e36 (PR #69), carried by 73d0c92 | v9.6.4 | CLEAN-APPLY |
| `openbb_eodhd/eodhd_router.py`, `openbb_eodhd/assets/apps.json`, `tests/test_eodhd_router.py`; `openbb_eodhd/__init__.py`, `pyproject.toml`, `docs/specs/...fmp-parity-design.md` (edits) | 498d317, eb73012, 564e5ee (test half) | v9.6.5 | CLEAN-APPLY |
| `pyproject.toml` (`openbb-core>=2.0.1,<3`), `tests/test_eodhd_router.py` (comment) | cd0aaeb (openbb-eodhd half only) | v9.6.6 | CLEAN-APPLY |

Wiring is written for this repo, not copied from the donor. It is adapted from
the donor's v9.6.3 `Dockerfile` (the EODHD install block) and its
`credentials.env.example`:

| Path | What |
|---|---|
| `Dockerfile.v3` | The build stage makes the openbb-eodhd wheel and the SDK wheel. The final stage installs the SDK (`requirements.lock` as constraints) and openbb-eodhd (`--no-deps`), then runs `pip check`, `openbb-build` and `v9/eodhd/verify.py`. |
| `credentials.env.example` | `EODHD_API_KEY=` with no value. |
| `v9/eodhd/verify.py`, `v9/eodhd/tests/` | The build gate and this line's tests (below). |
| `v9/eodhd/README.md`, `v9/eodhd/source.json`, `README.md`, `NOTICE` | Docs, provenance and attribution. The donor's Apache-2.0 LICENSE and SPDX headers are kept as they were. |

### Edits to donor files (key hygiene only; no code or assertion changed)

- `.env.example`: `EODHD_API_KEY=` is empty (it was `your_api_key_here`).
- `scripts/smoke.py`: the script no longer prints the token. It says only whether the public `demo` token is in use. Its usage line now reads `EODHD_API_KEY=<your token>`.
- Test fixtures: the fake credentials `"k"` and `"test_key_123"` are now `"PLACEHOLDER"`, so `scripts/check-public.py` passes. No test reads the value.
- The donor has no vcr cassettes or recorded EODHD responses. Its tests mock the SDK client inline, so there was nothing to scrub of `api_token`. `v9/eodhd/tests/fixtures/eod_bars.json` is new and holds fictional values.

## The EODHD app (`assets/apps.json`)

One app, `name: "EODHD"`, with no `id` field. The extension serves it on
`/api/v1/eodhd/apps.json`, and openbb-api merges that route into `/apps.json`
the same way it merges the other provider apps (checked by `test_stack.Catalogs`).
It is not added to `examples/bdobb/apps.json`. That file holds only BDOBB's own
examples, which the lanes hook appends.

| Tab | Cards (widget ids) |
|---|---|
| company | `eodhd_equity_profile_eodhd_obb`, `eodhd_equity_price_quote_eodhd_obb`, `eodhd_equity_price_historical_eodhd_obb`, `eodhd_equity_fundamental_income_eodhd_obb` |
| ownership | `eodhd_equity_fundamental_dividends_eodhd_obb`, `eodhd_equity_ownership_institutional_eodhd_obb` |
| markets | `eodhd_fixedincome_government_yield_curve_eodhd_obb`, `eodhd_index_price_historical_eodhd_obb` |

`scripts/verify-app-layouts.py v9/eodhd/source/openbb_eodhd/assets/apps.json`: no overlapping cards.

Note for the examples sync: the donor's BDOBB example "Example Dashboard - V9.6.2" (`workspace_apps.json`) uses standard-route widget ids. These ids do not exist on this backend:

| Missing id | Use instead |
|---|---|
| `equity_price_historical_eodhd_obb` | `eodhd_equity_price_historical_eodhd_obb` |
| `equity_fundamental_income_eodhd_obb` | `eodhd_equity_fundamental_income_eodhd_obb` |
| `economy_calendar_eodhd_obb` | `eodhd_economy_calendar_eodhd_obb` |
| `equity_calendar_earnings_eodhd_obb` | `eodhd_equity_calendar_earnings_eodhd_obb` |
| `fixedincome_government_treasury_auctions_government_us_obb` | `ustreasury_treasury_auctions_us_treasury_obb` |

## Excluded, and why

| Donor path or piece | Why |
|---|---|
| live-grid, kdb/kdb-x/kdb-ws, openbb-kdb, the /grid gateway routes, live-grid-studies, tick-lab, deltalake, minio, security-master, mcp_charts/charts | v10. openbb-eodhd imports none of them. |
| openbb-eodhd's ArcticDB L2 fundamentals cache (`models/_fundamentals.py`) | Not cut. The code soft-imports `openbb_arcticdb` inside a try block, and it turns itself off when that package is missing, which it always is here. The L1 cache and live fetch run as before. `tests/test_fundamentals_cache.py::test_arctic_library_passes_resolved_uri_not_none` is the donor's own `importorskip` and is recorded as SKIPPED. PROVISIONAL. |
| `tests/conftest.py` `_make_mock_pykx` | An unused helper that imports nothing. Kept verbatim. |
| `api_app.py` (`--factory` app: `/apps.json` served verbatim, Basic auth on every path, private-network CORS), the `rest_api.py` build-time rewrites, `docker-entrypoint.sh`, `extension-constraints.txt`, `api-auth.env.example` | These belong to the donor's own stack design, not to openbb-eodhd. This repo serves `/apps.json` through `lanes/openbq_lanes.py`, keeps `/widgets.json` and `/apps.json` open by design (`credentials.env.example`), and has its own web profile. `extension-constraints.txt`'s 5.0 floors (fastapi>=0.137.2, uvicorn>=0.48.0) are already met by the lock (fastapi 0.142.2, uvicorn 0.54.0). Its `pandas<3` comes from ArcticDB, not EODHD. The lock has pandas 3.0.6, and every openbb-eodhd test passes on it. |
| The donor's `credentials.env.example` EODHD demo websocket key | live-grid only (v10). This repo commits no key values. |
| `workspace_apps.json` (BDOBB examples) | Belongs to the examples sync (`EPISODE=9 scripts/apps-sync.mjs`), the next step. |
| The standard routers (`openbb[routers]`) | This line ships 17 providers and no standard routers. EODHD is served by its own `obb.eodhd.*` namespace. PROVISIONAL. |

## OpenBB Platform 5.0 fixes: taken or rejected

| Donor fix | Ruling | Proof |
|---|---|---|
| openbb-eodhd `openbb-core>=2.0.1,<3` (cd0aaeb) | TAKEN | Without it the package cannot install on openbb-core 2.0.1. No extension code needed changing. All non-SDK tests pass on 2.0.1 (receipts below). |
| `scripts/patch_openbb_core_auth.py` (cd0aaeb): with `OPENBB_API_AUTH=true`, stock core 2.0.1 fails to build the REST app ((1) duplicate `__authenticated_user_settings` for a function shared by several routes; (2) wrong parameter order after keyword-only parameters) | REJECTED: we already have both fixes | `provider-fixes/openbb_core/api/router/commands.py` already makes both edits: it rebuilds from `func.__dict__.setdefault("_openbb_original_signature", ...)` and adds the parameter as `Parameter.KEYWORD_ONLY`. On pristine locked packages with openbb-eodhd installed, `test_stack.ApiAuth.test_rest_app_builds_under_api_auth` FAILS with `ValueError: duplicate parameter name: '__authenticated_user_settings'`. With the overlay applied it PASSES, building all 52 `/api/v1/eodhd/` paths. The donor script would also fail the build either way. Run before `provider-fixes/apply.py`, it changes the pristine hash that `apply.py` checks. Run after, its anchors are already gone. |
| The CFTC lifespan/NULL-strip build patch and the `openbb-cftc==1.4.2` pin | Not applicable | The donor itself removed them in cd0aaeb (openbb-cftc 2.0.0 rewrote the router). This line runs openbb-cftc 2.0.0 with its own overlay. |
| 22e5a92 (drop providers 5.0 no longer ships) | Not applicable | It touches key-maint and the donor's provider maps only. |

## PROVISIONAL decisions

1. openbb-eodhd is taken at its v9.6.6 state: the v9.6.3 base plus aggregation hints (v9.6.4), the `obb.eodhd.*` namespace and app (v9.6.5), and the core 2 floor (v9.6.6). The core 2 floor is required, and the namespace is the only way EODHD is routed on this line. The aggregation hints are additive (per-column widget metadata and typed statement columns; same rows and values) and come in with the same `fundamental.py`.
2. No standard routers are installed. EODHD is served only on `/api/v1/eodhd/*` (52 commands).
3. The ArcticDB L2 cache stays as the donor wrote it: a soft import that is inert here.
4. The EODHD app ships inside the extension and is served by openbb-api. It is not copied into `examples/bdobb/apps.json`.

## Test receipts (cloud, 2026-10-12, Python 3.12.3, `requirements.lock` installed with uv)

| Suite | Environment | Result |
|---|---|---|
| `tests/` | lock + overlay | 8 passed (5 subtests) |
| `v3/tests` | lock + overlay | 68 passed |
| `workspace/tests` | system python | 12 passed |
| `lanes/tests` | lock + overlay | 22 passed |
| `provider-fixes/tests` | fresh lock, `apply.py` | 42 passed. Also 42 passed with openbb-eodhd installed. |
| `examples/episode3` `test_server`, `test_assembly` | system python | 6 passed |
| `funnel-gateway` `npm test` | node 22 | 47 passed |
| `v9/eodhd/tests` (this line) | lock + overlay + openbb-eodhd, no standard routers | 9 passed |
| the same `ApiAuth` test | pristine lock (no overlay) + openbb-eodhd | 1 failed, as expected (the bug the donor patch fixes) |
| `v9/eodhd/source/tests` (donor suite) | lock + overlay + the nine standard router packages at 2.0.0 (the donor CI's environment) | 465 passed, 1 skipped (ArcticDB `importorskip`), 5 failed: `test_client.py` SDK tests, `ModuleNotFoundError: eodhd`. NOT_RUN in substance. |
| `v9/eodhd/source/tests` (donor suite) | lock + overlay, no standard routers (the image's environment) | 314 passed, 1 skipped, 6 failed: the same 5 SDK tests, plus `test_no_extra_mirror_routes`, which expects every mirror to match a loaded standard route. That expectation holds only with the standard routers installed (row above, where it passes). `v9/eodhd/tests` checks the routers-less contract instead. |

No assertion was weakened, skipped or deleted. EODHD API calls used: 0 (`EODHD_API_KEY` is absent).

## NOT_RUN and Mac-pending

- The live stack: `/apps.json` and `/widgets.json` over Tailscale, `scripts/verify-app-layouts.py` against the running API, and Workspace or BDOBB rendering the EODHD app.
- Any live EODHD call (`scripts/smoke.py` and real-key queries): NOT_RUN, because no key is available.

## Renamed openbq-eodhd (2026-10-14, user ruling)

User ruling: "openbq-docker v9 should have openbq-eodhd" and "it should be Adventures-OpenBQ/openbq-eodhd". The extension now lives in its own repository, Adventures-OpenBQ/openbq-eodhd, and this stack vendors it, as it does openbq-yfinance (`v3/yfinance/`).
- The repository's first commit (8da2435, tag `v9.0.0`) imports `v9/eodhd/source` as of e393e13 with the rename. `v9/eodhd/source` is now `git archive v9.0.0` of that repository, and `source.json` records the repository, tag, commit and version, plus the donor block that used to be the whole file.
- Renamed: distribution `openbb-eodhd` → `openbq-eodhd`; module and directory `openbb_eodhd` → `openbq_eodhd` (imports, tests, `patch(...)` targets, package data, `verify.py`); the Dockerfile.v3 wheel `openbq_eodhd-9.0.0-py3-none-any.whl`; this repository's README, NOTICE, `v9/eodhd/README.md` and the synced BDOBB example description.
- Not renamed, for the OpenBB contract: the provider name `eodhd` (the `openbb_provider_extension` entry point), the core extension `eodhd` (`openbb_core_extension`, so `obb.eodhd.*` and `/api/v1/eodhd`), and therefore every widget id `eodhd_*_eodhd_obb`; the SDK distribution `eodhd`; and the donor's name in this ledger's rows above, `source.json`'s donor block and NOTICE's provenance.
- PROVISIONAL: the version is 9.0.0, matching the episode as openbq-yfinance 3.0.0 does, instead of the donor's 9.6.3.
- Tests: the package's own suite gave 314 passed, 1 skipped, and the same 6 failures before and after the rename. Five are the SDK tests, because the SDK archive cannot be fetched here; the sixth is `test_no_extra_mirror_routes`, which fails identically on the unrenamed tree in this venv. `v9/eodhd/tests`: 9 passed with openbq-eodhd 9.0.0 installed in place of openbb-eodhd.

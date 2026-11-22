# Shared study columns, first slice

The existing Apache `openbq_ta` registry is the single study definition owner.
`@study(..., param_schema=...)` adds typed parameter descriptions to its existing
`params` defaults. Descriptors support `integer`, `number`, `string`, `boolean`,
labels, defaults, minimum/maximum, positive editor step and enum choices. Existing
studies infer compatible descriptors; nullable time/ticker defaults remain valid.
`step` is an editor increment, not a new mathematical constraint. Window minima
remain positive; service resource budgets are separate from indicator definitions.

`openbq_ta.registry.catalog()` projects detached JSON metadata including
`param_schema` and `definition_version`; `catalog_entry(name)` returns one entry.
`resolve()` remains the common authoritative validator. Booleans cannot satisfy
integer parameters, nonfinite/overflowing numbers are rejected, and unknown
parameters remain errors. Catalogs cannot mutate registered defaults. Versions
hash metadata, engine source bytes and implementation code/defining-module bytes;
a same-size operator edit in the same second reloads exact source rather than an
old bytecode cache. Loaded source digests survive installation staging-file renames;
unloaded on-disk edits do not change the version of running code. Operator studies remain trusted Python, using the existing
operator-controlled folder and loader, with no new public code-upload route.

Art's Charts owns `/study_catalog` and `/study_results`, using its existing
composed bar sources and Python/Polars pipeline. Grid presentation does not
implement RSI or stochastic formulas. The default stochastic definition remains
fast (`smooth_k=1`); slow %K explicitly requests `smooth_k=3`.

Live-grid forwards GET `/study_catalog` and POST `/study_results` only when
`LIVE_GRID_STUDY_ORIGIN` is an explicit HTTP(S) origin and the existing Basic
server pair is configured with authentication enabled. It advertises
`live_grid.extra_metadata.study_columns_v1` only then. The v12 charts overlay sets
the origin to `http://arts-charts:8000`; the default stack leaves it disabled.
The browser never selects an upstream or receives the server credential.

The gateway exposes exact authenticated GET `/grid/study_catalog` and POST
`/grid/study_results`, without query parameters. Request bodies are at most
64 KiB; JSON responses at most 2 MiB. Live-grid admits eight simultaneous proxy
requests with a five-second whole-request deadline and no redirect following.
Gateway concurrency is governed by its existing configured ceiling. Both hops
hide upstream credential/error details. Art's Charts bounds/shared-caches the
actual computation; polling is batched HTTP at one second, without a new socket.

This slice adds registry metadata and study-column transport. It does not disable
anchors, extend the VWAP API, or claim completion of the accepted-data renderer
and anchored-history migration. No deployment or main-branch merge is implied.

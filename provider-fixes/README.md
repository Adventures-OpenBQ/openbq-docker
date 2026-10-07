# Provider compatibility overlay

Reviewed sources from OpenBQ PRs [7746](https://github.com/openbq-org/OpenBB/pull/7746) and [7747](https://github.com/openbq-org/OpenBB/pull/7747), commits `2462711` and `c2c8b60`. The application script verifies package versions and every original source hash before copying any file. It fails closed on upstream drift. Remove this overlay when published provider versions include the fixes. No credentials are required for applying it.

`openbb_cftc/cftc_router.py` is a local fix with no upstream PR yet: openbb-cftc 2.0.0 runs minutes of CPU-bound work (curve bootstraps over whole DTCC day slices) on the server's event loop, which froze every route, `/widgets.json` included. The overlay runs each CFTC command on its own event loop in a single worker thread.

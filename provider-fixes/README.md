# Provider compatibility overlay

Reviewed sources from OpenBQ PRs [7746](https://github.com/openbq-org/OpenBB/pull/7746) and [7747](https://github.com/openbq-org/OpenBB/pull/7747), commits `2462711` and `c2c8b60`. The application script verifies package versions and every original source hash before copying any file. It fails closed on upstream drift. Remove this overlay when published provider versions include the fixes. No credentials are required for applying it.

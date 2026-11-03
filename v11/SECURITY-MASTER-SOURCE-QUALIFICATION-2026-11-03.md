# Security Master standalone source qualification

The tracked `security-master-api` and `openbb-deltalake` source at
`b4b7f4b68ae200f82b2067dd6ade70a9d425509a` was archived read-only from the
original host checkout. Those paths had no uncommitted changes. The archive
SHA-256 is `3ebd2e93d198aa8a1ac26d16730c73dd6db0c747648bd96f44d861dacf268f73`.
The source archive and isolated environment are retained outside Git.

A separate Python 3.12 environment was synchronized with the source's existing
uv lock (`--frozen --extra dev`). All 238 service tests passed in 130.55 seconds.
Four warnings were upstream OpenBB/Pydantic deprecations. No provider acquisition,
production-store read/write, NAS service change or deployment was performed.

The actual installed versions are retained in
`qualification-2026-11-03/security-master-source/report.json`, including
security-master-api 0.2.0, openbb-deltalake 11.0.0, OpenBB core 1.6.13,
DuckDB 1.5.5 and deltalake 1.6.3. This is native macOS arm64 source qualification,
not an installed amd64 image, an HTTP bridge, or NAS durability qualification.

The standalone service can keep its own qualified dependency set behind HTTP.
It does not downgrade the v11 provider host's OpenBB core 2.0.1 or replace
TemporalDB's DuckDB 1.4.3. The ODP extension's OpenBB 2 compatibility and duplicate
calendar entry point still require separate integration and testing.

Next: freeze the standalone build context/lock, qualify an amd64 service image
against a new store with acquisition disabled, and map its actual temporal and
dependency receipts into a versioned retained-reference bridge. Do not claim
shared Basic authentication supplies workspace isolation. Preserve the distinct
calendar supplier and source-authority settings.

## Installed native NAS qualification

The frozen amd64 qualification image
`sha256:5b7c4bdf02858d1438ddc22b1b5256f8e9fe8e833379aeca02a6af47a56414d6`
passed all 238 offline tests natively on the NAS in 322.58 seconds, with the same
four upstream warnings. It ran without networking, ports or production mounts,
with a read-only root, dropped capabilities, no-new-privileges and bounded
memory/CPU/tmpfs. A test-only writable contract-recorder directory was provided.

The corresponding runtime image is
`sha256:1092c5a3cc01912e6ff0dfbc487aa7120706dc6f027885ddf901cc937f761d8c`.
Both use recipe commit `0b6ecfb399aa27a0c648b97560346a782663dd5f` and the source
archive above. The combined Docker-save SHA-256 is
`3af88acd6ef21bb36e2c092996aa0ac293311c532d4754b5763c8c983ab62c20`;
the retained native test log SHA-256 is
`c2f74b41a69d75b30de89b959f9ca500ba4aa86374f7d22e9af043558ec5b6ee`.

This qualifies the offline installed test artifact. It does not admit the real
S&P 500 data, establish classification history, qualify the ODP HTTP bridge or
prove service recovery against a retained real store. No donor service changed.

# table_ssrm roll-up handoff

For another process to integrate. Authoritative paired repositories:
Adventures-OpenBQ/bdobb and Adventures-OpenBQ/openbq-docker. Both feature branches:
`codex/table-ssrm-v10`. No merge, tag movement or deployment performed.

User requires inclusion before v7 for physical iPad testing. Proposed placement is
v4 execution/large cached-table foundation and v5 generic Statement presentation;
receiving process chooses and ports dependencies. This branch derives from v10 work,
so do not import its whole ancestry into an earlier release.

Reviewed Docker head before this documentation-only handoff:
`41641c684af4db1c6390ea682e5663daff331bfd` (base
`186034209b38c9774a211d6ccbea581129b6e8fc`). Main advanced independently to
`72834aa6b58c5e2addd36aec0692f028a93fa2be`; this branch was not rebased.

`source.lock.json` pins bdobb source
`1382c316d3838355a4366a163e63f280500d7284`, tree
`d7c9a9a11122ea90b72925ca33363563c0dd81d4`. Source export and Compose checks pass.
Canonical gateway changes are in `e1a602911018ad5a82eed3c5d5f706934b90081f`;
policy SHA256 `c4d1a2bd75523d75b53a0cb579116ecf4e627210e6c8bd2196eb3deba672fc7a`.
bdobb vendors this policy and pairs Docker41641c6. Handoff docs do not require a
circular source/policy repin. New code changes do require exact pin reconciliation.

The opt-in table profile remains private. Cancel, session disposal and export cleanup
have two reserved control requests, independent of ordinary concurrency and finite
rate allowance. Gateway96, web57, native service72 and native browsers4 pass; bdobb
fullJS8171/29skip. Independent scoped review passes with no open findings.

Full design/qualification/optimization backlog is in bdobb's feature branch at
`docs/releases/table-ssrm-rollup-handoff.md`. Performance optimizations are reviewed
proposals, not implemented changes. Production image remains UNQUALIFIED after Docker
VM ENOSPC; actual host-backed non-root Linux runtime tests do not qualify assembled
layers, UID10001, named-volume initialization or release builds. Physical iPad and
cumulative target-release qualification remain with the receiving process.

## Walked (2026-10-15)

This roll-up was walked down to its home lines and carried forward v4 → v10 by real merges, with the
gateway moved down to v4 by the user's ruling. The pins above are the reviewed PR's; the paired pins
of each walked line are in `table-service/source.lock.json` and in bdobb's
`docs/releases/v4-ssrm-walk.md` … `v10-ssrm-walk.md`, which also classify every difference from this
handoff's sources.

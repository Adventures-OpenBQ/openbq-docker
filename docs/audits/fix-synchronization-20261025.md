<!-- Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0 -->

# Fix synchronization on 25 October 2026

This record tracks the version 9.0.0 source synchronization and the subsequently authorized V9 release-branch integration. No version tag is published by this integration.

- Public base: `bdaa5ab34d895a5ad78dc81dac6e54d15a58fb2a`.
- Original audit source: `4787af3b5930255475ed976ad6146c79297c4ff6`.
- Validation: fresh repository root tests passed on the combined tree. The full test summary follows.

```text
51 passed, 15 subtests passed in 22.38s
```

Key-maint is AGPL-3.0-only from version 3 onward; RSS is AGPL-3.0-only from version 8 onward. Component license files, package metadata and container notices preserve earlier grants and third-party notices. The latest key-maint and vendored RSS service suites passed 230 and 250 tests respectively.

Reconciliation: Kept newer public calendar bounds/catalogue and existing widget exclusion; added lowercase legacy-route regression only.

At the original source-synchronization checkpoint, V8–V10 release promotion remained on hold and V11 testing remained paused. That source synchronization updated no release branch or version tag. Earlier V7 device observations qualified only the recorded audit binary.

## V9 release integration approved on 25 October 2026

The user authorized merging the verified V9 fixes into `release/v9`. The combined tree retains the newer TMX document-host restriction from `c2918cf008b1717761a565d8d56641139d19cf29` alongside the audited candidate `f992cfab2631ce39f7647c5b6f1c7fe081550cf4`. The provider hash manifest retains every entry from both parents.

Fresh combined-tree verification: 51 root tests and 15 subtests passed; all 54 provider-overlay tests passed on the pristine pinned `odp` image after applying all 41 reviewed provider source files. The first root-test invocation lacked Docker on PATH; the complete retry with Docker available passed. No model API calls were made for this merge.

V10 remains on hold and V11 remains paused. Only the V9 release branch is authorized for this integration; existing version tags remain unchanged. The earlier image/device qualification applies to its recorded source commits, while these fresh checks qualify the combined backend source tree.

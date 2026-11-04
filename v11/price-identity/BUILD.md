# One-day Block price qualification

This exporter is a bounded qualification example, not a general historical
security-master importer. It validates retained source bytes against
[the evidence manifest](block-xyz-evidence.json), then emits the existing
five-field IdentityMap entry and its digest. It fetches no data and does not
write to Security Master.

Keep the four original bodies in an operator-owned private directory using the
manifest's filenames. The committed manifest records integrity and the declared
rationale; hashes are not source signatures. Run:

```sh
python v11/price-identity/block_xyz.py --manifest v11/price-identity/block-xyz-evidence.json --bodies-dir /private/retained-block-evidence --output /private/new-block-map-export.json
```

Output refuses overwrite. Install only its `mappings` array as
`TEMPORALDB_IDENTITIES`, after preserving the old qualification configuration.
Bind the returned map/evidence digests into the qualification receipt; archive
the runtime using that exact map before starting acquisition. No provider
credential belongs in this manifest, command output, receipt or widget.

The assertion covers **XYZ.US on January 21, 2025 only**, as current corrected
analysis of retained historical prices. It does not establish what we knew in
January 2025. It does not cover SQ, ASX, another date or historical S&P membership.
Both current General and ReferenceSecurity omit CUSIP/ISIN here, so the admitted
security identity remains provisional. The issuer announcement supplies the NYSE
ticker transition date; the one-day association to the admitted current listing
is explicitly an operator assertion. Security Master's unknown business dates
remain unknown. Final v11 qualification must still demonstrate the real saved
policy miss, acceptance, hit without IO, and the shared release gates.

# S&P 500 security-master bootstrap — 2026-11-03

## Authorized scope and build order

Build a real current-observed S&P 500 reference snapshot, retaining source bytes and acquisition evidence. Keep paid-provider data outside Git. Acquire index constituents and listing references, enrich individual General profiles, reconcile issuer CIKs against SEC submissions, normalize identities, then export and independently review. Do not infer historical membership or deploy the service as part of this bootstrap.

## Implemented

`build_sp500_security_master.py` is an offline builder consuming a credential-free source manifest. It validates retained hashes, generates deterministic identity keys, preserves share classes and separate classification taxonomies, and exports DuckDB, CSV and Parquet with source captures, schema, reproducible builder, checksums and example queries.

Live retained inputs: 503 EODHD constituent General profiles, current GSPC.INDX components, US listing reference, Wikipedia constituent reference, and 500 SEC submissions responses. All SEC requests returned HTTP 200. CIK selection requires matching both SEC CIK and ticker; otherwise verification remains explicitly unconfirmed. Twelve provider/community CIK conflicts were resolved using SEC evidence, with original reported values retained in issue records.

The output contains 503 securities/listings/memberships and 500 issuer groups, 1,006 source captures, 503 valid ISINs, 503 SEC-ticker-confirmed CIK associations, 503 reported FIGIs and 27 reported CUSIPs. Source weights sum to 1.0008 and remain unchanged. One CBOE BATS/OperatingMIC discrepancy is retained with canonical MIC withheld.

## Endpoint and access distinctions

Individual ETF fundamentals worked with the configured key (VTI.US). Bulk-v2 BATS returned HTTP 403; entitlement remains unconfirmed. The documented bulk-v2 exchange set is NASDAQ, NYSE, AMEX, BATS, TO and V; US is not supported by that endpoint. The separate exchange-symbol-list/US endpoint did work. No subscription changes were made.

## Validation and boundaries

Nine focused tests passed, including share-class handling, malformed identity evidence, conflicting CIK reconciliation, rejection of SEC evidence without matching ticker, and credential-bearing source metadata rejection. Ruff F/E9 passed. All delivered checksums were verified; DuckDB and Parquet rows match and all 503 CIK associations have SEC ticker evidence.

Artifact location (outside Git): ../artifacts/sp500-security-master/sp500-master-verified/.

This is a local bootstrap snapshot, not historical S&P-certified membership, a deployed Security Master API, or an admitted TemporalDB dataset. Observation timestamps are retained; historical effective dates are not invented. Independent final review follows the data build. Full service integration, temporal ingestion and ongoing refresh remain separate work.

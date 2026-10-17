# Provider API usage in the key check — design

Date: 2026-10-17. Status: approved in brainstorming (approach A, sections 1–2).

## Goal

When a provider key is tested, show how many API calls have been spent in the
vendor's current window and how big that window is — for every vendor that
reports it. Usage is informational: it never changes a check's pass/fail.

## Scope

| Vendor | Source | Window |
|---|---|---|
| EODHD | `GET https://eodhd.com/api/user` (free, does not spend a call) | day, resets 00:00 UTC |
| Intrinio | `GET https://api-v2.intrinio.com/account/current_usage` | period (per access code) |
| EIA | `x-ratelimit-limit` / `x-ratelimit-remaining` headers on the existing probe (api.data.gov) | hour |
| Alpaca | `x-ratelimit-limit` / `-remaining` / `-reset` headers on the existing probe | minute |

Out of scope: Congress.gov (no key-maint probe on any OpenBQ line; it would
report hourly headers if one is added), FMP, Tiingo, FRED, BLS, Alpha Vantage and the rest (no usage
reported); polling or a separate usage refresh; thresholds or warning colours;
the legacy `KeysRenderer` table widget; the Library provider badge.

## Placement

Adventures-OpenBQ, per the series' release lines (vN.0.0 tags are definitive):
- **openbq-docker `key-maint/`:** home line **`release/v3`** — first line with
  `probes.Check` and the EODHD, Intrinio, EIA and Alpaca probes. Work branch
  `claude/v3-provider-api-usage` off `origin/release/v3`.
- **Adventures-OpenBQ/bdobb:** home line **`release/v3`** — already has
  `ProviderDetailsDialog` with the per-check list.
- Carry into v4–v10 and the v3.0.0 re-cut follow the series' walk, not this spec.

## Wire shape (key-maint → app)

`Check` gains one optional field, serialised by `_check_dict` and passed
through `rows.py` unchanged (it rides inside `checks[]` and `test`):

```
usage?: {
  used: number,        // calls spent in the current window
  limit: number,       // allowance for the window
  window: "day" | "hour" | "minute" | "period",
  resets_at?: string,  // UTC ISO-8601, only when known
  extra?: number       // EODHD extraLimit only
}
```

Only the **credential** check carries usage. Absent `usage` = vendor does not
report it, or the probe could not parse it.

## key-maint

**Probe changes**
- `_eodhd` requests `/api/user?api_token=…&fmt=json` instead of
  `/api/eod/AAPL.US`. A bad key returns 401 (verified 2026-10-17), so it still
  validates the credential, and checks stop spending a call.
- `_intrinio` requests `/account/current_usage`, keeping the existing `api_key`
  query param. A bad key returns 401 (verified 2026-10-17).
- EIA and Alpaca probe URLs are unchanged.

**Parsing** — one `parse_usage(provider_id, response) -> dict | None`, called in
`_probe_credential` only when the result is `ok`:
- EODHD body: `used` = `apiRequests` (0 when `apiRequestsDate` ≠ today UTC —
  the counter has not reset yet), `limit` = `dailyRateLimit`, `window` = day,
  `resets_at` = next 00:00 UTC, `extra` = `extraLimit`. Accept numbers or
  numeric strings (docs say string; the live response is numeric).
- Intrinio body: pick the entry with the highest `percentage_used`; `used` =
  `count`, `limit` = `limit`, `window` = period, `resets_at` = now +
  `seconds_until_reset`.
- Headers: a provider→window map (`eia` → hour, `alpaca` → minute). `used` = limit − remaining; `resets_at` from `x-ratelimit-reset`
  (epoch seconds) when present. Providers not in the map are never parsed.
- Any missing, non-numeric or negative value → `None`. Parsing never raises
  and never changes `result`, `detail` or `code`. `detail` stays built from
  status codes only; numbers live only in `usage`.

## bdobb (Adventures-OpenBQ/bdobb)

- `KeyCheck` gains `usage?`. A guard keeps it only when `used` and `limit` are
  finite numbers and `window` is one of the four values; otherwise it is dropped.
- `deriveProvider` copies the credential check's usage to `Provider.usage`.
- **Dashboard card:** one muted line under "Credential: …" —
  `API calls: 1,234 / 100,000 today` (`today` / `this hour` / `this minute` /
  `this period`; `toLocaleString`). No line when there is no usage.
- **Details dialog:** an "API usage" block under the check list —
  `1,234 of 100,000 calls today (1.2%)`; `Resets 00:00 UTC · in 9h 12m` when
  `resets_at` is present; `Extra calls remaining: 5,000` when `extra` > 0;
  `As of <checked_at>` via `formatCheckedAt`.

## Testing

- key-maint (pytest): EODHD parse incl. stale `apiRequestsDate` and string
  values; the EODHD probe URL is `/api/user`; Intrinio worst-code selection;
  header parse incl. missing/garbage headers and an unmapped provider; usage
  absent on non-`ok` results; `result`/`detail` unchanged when usage parses.
- bdobb (vitest): the guard; `deriveProvider` carries usage; card line text
  per window; Details block lines incl. the optional ones.
- Live: run one Check on each vendor whose key is configured and confirm the
  figures match the vendor's dashboard. Alpaca's data-API headers are
  unverified — if absent, Alpaca simply shows no usage.

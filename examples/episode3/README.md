<!-- Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0. SPDX-License-Identifier: Apache-2.0 -->

# Episode 3 — OpenBQ reference backend

This is a separate FastAPI container built from OpenBQ's reference backend at
`a6293707576e16edda8305adda95b07b6a4b968b`, with the recorded CORS and PDF
fixes from our tested reference recipe. Omni code execution (SQL, Python) is
off unless `OPENBQ_OMNI_EXEC_ALLOWED` lists the language, e.g. `sql` or `sql,python`. The upstream MIT
license is retained; the series additions are Apache-2.0.

It advertises one app and **70 cards** through `/apps.json`: the reference app. Its
actual registry contains **72 widgets**: 70 reference widgets plus two fictional example
widgets; repeated reference cards reuse widget IDs. Every advertised card resolves locally.
The two fictional widgets supply deterministic prices and null-handling rows for the
pivot examples, which arrive with BDOBB v4: BDOBB v3 has no analytical pivot and refuses
an app that carries BDOBB layout extensions, so v3 serves none.

The keyless market dashboard is a separate download at `/market-examples.apps.json`.
It uses the original OpenBQ yfinance V5 extension and the current SEC widget ID
from the ODP backend. `/bundle.apps.json` combines both dashboards and **76
cards** (70 + 6) for BDOBB's multi-backend file import. The reference catalog does not
advertise unresolved ODP widgets as its own.

The "Onboarding App for Devs" entry in this directory's `apps.json` is upstream data and is never
served: `assemble.py` keeps only the app named "Episode 3*" from that file, and the reference app comes
from the pinned upstream source (70 cards there; the copy here has 69).

## Build and run

From the repository root, use the v3 overlay:

```sh
cp v3.env.example v3.env
# Optional: set EXTRA_CORS_ORIGINS to your Workspace or Vercel browser origin.
docker compose -f docker-compose.yml -f docker-compose.v3.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.v3.yml build
docker compose -f docker-compose.yml -f docker-compose.v3.yml up -d
```

The overlay builds ODP with our yfinance extension and the reference backend in
separate containers. The existing Tailscale sidecar forwards private HTTPS 443
to ODP and private HTTPS 8443 to `openbq-reference`. No host ports are published,
Funnel is disabled, and another Tailscale key is not required. The reference
container runs as UID/GID 10001 with a read-only filesystem and a temporary
scratch filesystem. It has no account database or provider credentials.

Connect the reference endpoint `https://openbq.YOUR-TAILNET.ts.net:8443` and the
ODP endpoint `https://openbq.YOUR-TAILNET.ts.net`. BDOBB's **Apps** row lists the reference
service's self-contained `/apps.json`; `/bundle.apps.json` is the same set plus the
market examples, for My Dashboards → Import apps.json.
Workspace accounts and the Episode 2 installation are not required.

```sh
python3 scripts/verify-reference.py https://openbq.YOUR-TAILNET.ts.net:8443
```

Keep actual origins in ignored `v3.env`. Cross-origin permission is separate
from network reachability or backend authentication.

## Pivot examples (v4)

The fictional price and null rows, and the pivot configuration of the market examples'
statement cards, belong to BDOBB's v4 `pivot-v1` extension. In v3 the market examples
open as plain tables, and the Pivot examples app is not served.

## Branding

The Episode 3 entry embeds the existing BDOBB square logo in `img`,
`img_dark` and `img_light`. The SVG is also served at `/assets/bdobb-logo.svg`.
Downloads retain their image without a hostname or external image host. The
upstream reference app keeps its original branding.

## Source assembly and gates

`source.json` pins the upstream commit. `assemble.py` refuses a wrong revision,
a dirty source checkout, or an existing output directory. It copies the reference
source and assets, applies the recorded patches, and constructs the catalogs.
`requirements.lock` records the resolved Python 3.12 dependency versions; the
Python base is pinned by digest. This is a version lock, not a claim of byte-identical
builds across dependency artifacts or Debian package repositories.

The Docker build checks catalog resolution, representative reference routes,
PDF, forms, WebSocket delivery, CORS, logo, and that Omni code execution is
refused unless allowed. It
also imports the application as the actual non-root runtime UID. Native BDOBB
quit/reopen, live Yahoo/SEC requests and private HTTPS acceptance are separate
checks before a v3.0.0 release claim.

# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# Art's Charts (v12, profile charts-v12): one image for arts-charts and its worker, built from
# the vendored arts-charts-openbq snapshot in ./source (BUSL-1.1, its own LICENSE; recorded in
# v12/arts-charts.lock.json). Build context: v12/arts-charts.

# The snapshot renderer's page: the real card, built once, served to Chromium in-process.
FROM node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS render
WORKDIR /src
COPY source/client/package.json source/client/pnpm-lock.yaml client/
RUN corepack enable && cd client && pnpm install --frozen-lockfile
COPY source/client client
COPY source/dev/tokens.css dev/tokens.css
RUN cd client && pnpm exec vite build -c vite.render.config.ts

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright HOME=/tmp
WORKDIR /srv
COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --no-deps -r /tmp/requirements.lock
# The study engine (spec 2026-11-04 S6), from this repository's live-grid/openbq-ta (the
# compose build's `openbq-ta` context). Its one dependency, polars, is in the lock.
COPY --from=openbq-ta . /srv/openbq-ta
RUN pip install --no-deps /srv/openbq-ta
COPY source/server /srv/server
RUN pip install --no-deps /srv/server && pip check
# Chromium's headless shell and its system libraries, readable by the unprivileged user.
RUN playwright install --with-deps --only-shell chromium && chmod -R a+rX /ms-playwright
COPY --from=render /src/client/render/dist /srv/render
COPY source/LICENSE source/client/ARTS_CHARTS_TERMS.md source/client/THIRD_PARTY_NOTICES.md /srv/licenses/
ENV ARTS_CHARTS_RENDER_DIR=/srv/render ARTS_CHARTS_DB=sqlite:////data/arts-charts.db
# Unprivileged; /data is the arts-charts-data volume (a new volume inherits this owner).
RUN install -d -o 10001 -g 10001 /data
RUN install -d -o 10001 -g 10001 /studies
USER 10001:10001
CMD ["uvicorn", "--factory", "arts_charts.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

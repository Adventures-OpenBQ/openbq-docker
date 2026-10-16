# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

# live-grid: OpenBB Workspace live_grid backend streaming EODHD websocket
# prices, plus tick recording and a unified chart over kdb+ (Ep. 10).
# Loopback-only; Tailscale Serve publishes it (see repo compose).
#
# Built with the REPO ROOT as build context (see docker-compose.yml) --
# COPY paths below are repo-root-relative, because a Dockerfile can only
# reach paths inside its build context and v10/kdb/source/ (openbq-kdb) sits outside live-grid/,
# not its descendant.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

# plotly.js is vendored: the page must render on a network with no CDN route.
ADD https://cdn.plot.ly/plotly-2.35.2.min.js /srv/app/static/plotly.min.js

# Shared kdb+ session/store plumbing (Ep. 10). Installed before live-grid
# itself, since live-grid's own pyproject.toml depends on it and it is not
# published to PyPI.
COPY v10/kdb/source/ /srv/openbq-kdb/
RUN pip install /srv/openbq-kdb

COPY live-grid/pyproject.toml ./
COPY live-grid/app/ app/
# openbq-kdb's q demo chart (v10/kdb/source/q/live-chart.html) is NOT copied (D19): it takes
# any ?ws= URL and writes feed data into innerHTML unescaped, on this origin, and no route on
# this stack reaches it.
COPY live-grid/widgets.json ./
# apps.json is served by GET /apps.json; the route reads it from disk, so
# leaving it out of the image is a 500, not a missing feature.
COPY live-grid/apps.json ./
COPY live-grid/macros/ macros/
RUN pip install . && chmod 644 app/static/plotly.min.js
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "6903"]

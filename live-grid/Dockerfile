# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

# live-grid: OpenBB Workspace live_grid backend streaming EODHD websocket
# prices, plus tick recording and a unified chart over kdb+ (Ep. 10).
# Run alone, the CMD binds loopback. openbq-docker's compose runs it on
# 0.0.0.0:6903 on its bridges, with no host port and no Serve entry; the
# funnel-gateway's /grid family is the way in.
#
# Built with the REPO ROOT as build context (see docker-compose.yml) --
# COPY paths below are repo-root-relative, because a Dockerfile can only
# reach paths inside its build context and v10/kdb/source/ (openbq-kdb) sits outside live-grid/,
# not its descendant.
# Pinned by digest (the multi-arch index), as Dockerfile.lake is (D21).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# matplotlib (pulled in by the eodhd SDK) keeps its config and font cache under $HOME/.config,
# which for uid 10001 is /.config on the read-only root (L2); compose's /tmp tmpfs is writable.
ENV MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /srv

# plotly.js is vendored: the page must render on a network with no CDN route.
ADD --checksum=sha256:6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603 https://cdn.plot.ly/plotly-2.35.2.min.js /srv/app/static/plotly.min.js

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
RUN pip install . && pip check && chmod 644 app/static/plotly.min.js
# Unprivileged (D21). /data is made here, owned by that uid, so a new live-grid-data volume
# inherits it; compose adds a read-only root, a /tmp tmpfs, cap_drop ALL and no-new-privileges.
RUN install -d -o 10001 -g 10001 /data
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "6903"]

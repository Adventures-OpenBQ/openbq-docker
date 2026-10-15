# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
# Extensions with no PyPI release for openbb-core 2 (v3/videos, v3/econdb), built as wheels with a pinned builder.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS extensions-build
RUN python -m pip install hatchling==1.32.4 packaging==26.3 pathspec==1.1.1 pluggy==1.6.0 trove-classifiers==2026.9.21.13
COPY v3/videos/source /videos
COPY v3/econdb/source /econdb
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels /videos /econdb
# v9: openbq-eodhd 9.0.0 and the official EODHD SDK, built exactly as Dockerfile.v3 builds them
# (v9/eodhd/source.json), so the base image serves obb.eodhd.* too.
RUN python -m pip install setuptools==84.0.0
COPY v9/eodhd/source /eodhd
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels /eodhd \
    && python -m pip wheel --no-deps --wheel-dir /wheels \
       "eodhd @ https://github.com/EodHistoricalData/EODHD-APIs-Python-Financial-Library/archive/f98e69d797140ca03f16fa7451046d84aab9643e.tar.gz"

FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS odp
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install -r /tmp/requirements.lock && python -m pip check

# Pristine pinned packages end here; scripts/test-provider-fixes.sh tests the overlay on this stage.
FROM odp
COPY provider-fixes /tmp/provider-fixes
RUN python /tmp/provider-fixes/apply.py && rm -rf /tmp/provider-fixes
# v3: the Video Library (openbb-videos 3.0.1, v3/videos) and EconDB (openbb-econdb, OpenBB's MIT-era
# provider ported to openbb-core 2, v3/econdb) extensions. No PyPI release fits the lock; their
# dependencies are all in requirements.lock, so --no-deps.
COPY --from=extensions-build /wheels/openbb_videos-3.0.1-py3-none-any.whl /wheels/openbb_econdb-1.0.0+openbq.1-py3-none-any.whl /tmp/ext/
RUN python -m pip install --no-deps /tmp/ext/*.whl && python -m pip check && openbb-build && rm -rf /tmp/ext
COPY v3/videos/verify.py /tmp/ext-verify/videos.py
COPY v3/econdb/verify.py /tmp/ext-verify/econdb/verify.py
COPY v3/econdb/tests /tmp/ext-verify/econdb/tests
RUN python /tmp/ext-verify/videos.py && python /tmp/ext-verify/econdb/verify.py && rm -rf /tmp/ext-verify
# v9: EODHD provider extension, served as obb.eodhd.* (/api/v1/eodhd/*) with its "EODHD" app, installed
# as in Dockerfile.v3: the SDK's dependencies resolve under the ODP lock as constraints.
COPY --from=extensions-build /wheels/eodhd-*.whl /wheels/openbq_eodhd-9.0.0-py3-none-any.whl /tmp/eodhd/
RUN python -m pip install --constraint /tmp/requirements.lock /tmp/eodhd/eodhd-*.whl \
    && python -m pip install --no-deps /tmp/eodhd/openbq_eodhd-9.0.0-py3-none-any.whl \
    && python -m pip check && openbb-build && rm -rf /tmp/eodhd
COPY v9/eodhd/verify.py /tmp/eodhd-verify/verify.py
COPY v9/eodhd/tests /tmp/eodhd-verify/tests
RUN python /tmp/eodhd-verify/verify.py && rm -rf /tmp/eodhd-verify
COPY lanes/openbq_lanes.py /usr/local/lib/python3.12/site-packages/openbq_lanes.py
WORKDIR /workspace
# BDOBB example dashboards, appended to /apps.json by the lanes hook (examples/bdobb/README.md).
COPY examples/bdobb/apps.json /workspace/bdobb_apps.json
# BDOBB's logo, served without auth at /openbq/bdobb-logo.svg (the examples' img; examples/bdobb/README.md).
COPY examples/episode3/assets/bdobb-logo.svg /workspace/bdobb-logo.svg
# v5: fixture widgets served by the lanes hook (synthetic_cash_flow; v5/fixtures/README.md).
COPY v5/fixtures /workspace/openbq-fixtures
COPY lanes/openbb.toml /workspace/openbb.toml
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=5 CMD curl -fsS http://127.0.0.1:6900/widgets.json > /dev/null || exit 1
CMD ["openbb-api", "--host", "0.0.0.0", "--port", "6900"]

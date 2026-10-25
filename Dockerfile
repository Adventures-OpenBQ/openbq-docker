# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
# Extensions with no PyPI release for openbb-core 2 (v3/videos, v3/econdb), built as wheels with a pinned builder.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS extensions-build
RUN python -m pip install hatchling==1.32.4 packaging==26.3 pathspec==1.1.1 pluggy==1.6.0 trove-classifiers==2026.9.21.13
COPY v3/videos/source /videos
COPY v3/econdb/source /econdb
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels /videos /econdb

FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS odp
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install -r /tmp/requirements.lock && python -m pip check

# Pristine pinned packages end here; scripts/test-provider-fixes.sh tests the overlay on this stage.
FROM odp AS api
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
COPY lanes/openbq_lanes.py /usr/local/lib/python3.12/site-packages/openbq_lanes.py
WORKDIR /workspace
# BDOBB example dashboards, appended to /apps.json by the lanes hook (examples/bdobb/README.md).
COPY examples/bdobb/apps.json /workspace/bdobb_apps.json
# BDOBB's logo, served without auth at /openbq/bdobb-logo.svg (the examples' img; examples/bdobb/README.md).
COPY examples/episode3/assets/bdobb-logo.svg /workspace/bdobb-logo.svg
COPY lanes/openbb.toml /workspace/openbb.toml
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=5 CMD curl -fsS http://127.0.0.1:6900/widgets.json > /dev/null || exit 1
CMD ["openbb-api", "--host", "0.0.0.0", "--port", "6900"]

# Episode 3 (docker-compose.v3.yml, target v3): the original Apache-2.0 yfinance extension on the API image.
FROM extensions-build AS yfinance-build
COPY v3/yfinance/source /source
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels /source

FROM api AS v3
COPY v3/yfinance/requirements.extra.lock /tmp/yfinance-extra.lock
COPY --from=yfinance-build /wheels/openbq_yfinance-3.0.0-py3-none-any.whl /tmp/openbq_yfinance-3.0.0-py3-none-any.whl
RUN python -m pip install --no-deps -r /tmp/yfinance-extra.lock \
    && python -m pip install --no-deps /tmp/openbq_yfinance-3.0.0-py3-none-any.whl \
    && python -m pip check && cd / && openbb-build
COPY v3/yfinance/verify.py /tmp/verify-yfinance.py
RUN python /tmp/verify-yfinance.py && rm /tmp/verify-yfinance.py /tmp/openbq_yfinance-3.0.0-py3-none-any.whl
COPY v3/openbq_settings.py /usr/local/lib/python3.12/site-packages/openbq_settings.py
COPY v3/openbb.toml /workspace/openbb.toml

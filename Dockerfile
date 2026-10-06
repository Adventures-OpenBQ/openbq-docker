# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install -r /tmp/requirements.lock && python -m pip check
WORKDIR /workspace
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=5 CMD curl -fsS http://127.0.0.1:6900/widgets.json > /dev/null || exit 1
CMD ["openbb-api", "--host", "0.0.0.0", "--port", "6900"]

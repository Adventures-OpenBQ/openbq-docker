# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
LABEL org.opencontainers.image.licenses="AGPL-3.0-only"
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /opt/key-maint
COPY pyproject.toml LICENSE LICENSE.previous LICENSING.md ./
COPY app/ ./app/
COPY requirements.lock requirements-build.lock ./
RUN python -m pip install --no-deps -r requirements-build.lock -r requirements.lock \
    && python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check
CMD ["python", "-m", "app.main"]

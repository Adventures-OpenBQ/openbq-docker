# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

FROM python:3.12-slim
LABEL org.opencontainers.image.licenses="AGPL-3.0-only"
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /opt/key-maint
COPY pyproject.toml LICENSE LICENSE.previous LICENSING.md ./
COPY app/ ./app/
RUN pip install .
CMD ["python", "-m", "app.main"]

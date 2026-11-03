# SPDX-License-Identifier: Apache-2.0
# Build context: the verified archive's source/ directory, never a deployment tree.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS dependencies
ENV PYTHONUNBUFFERED=1 UV_NO_CACHE=1
WORKDIR /opt/security-master
RUN python -m pip install --no-cache-dir --root-user-action=ignore uv==0.11.19
COPY openbb-deltalake/ ./openbb-deltalake/
COPY security-master-api/ ./security-master-api/
WORKDIR /opt/security-master/security-master-api
RUN uv sync --python /usr/local/bin/python --frozen --no-dev --no-editable

FROM dependencies AS runtime
ARG SOURCE_REVISION
ARG SOURCE_ARCHIVE_SHA256
ARG RECIPE_REVISION
LABEL org.opencontainers.image.title="OpenBQ Security Master staging" \
      org.opencontainers.image.version="0.2.0" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      io.openbq.source-archive-sha256=$SOURCE_ARCHIVE_SHA256 \
      io.openbq.recipe-revision=$RECIPE_REVISION
ENV PATH="/opt/security-master/security-master-api/.venv/bin:$PATH" \
    HOME="/run/security-master" OPENBB_HOME="/run/security-master/.openbb_platform" \
    PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /data /run/security-master && chown 65532:65532 /data /run/security-master
WORKDIR /run/security-master
USER 65532:65532
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6905/security-master/v1/health',timeout=3).read()"]
CMD ["uvicorn", "security_master_api.app.main:app", "--host", "0.0.0.0", "--port", "6905", "--no-access-log"]

FROM runtime AS qualification
USER 0:0
WORKDIR /opt/security-master/security-master-api
RUN uv sync --python /usr/local/bin/python --frozen --extra dev --no-editable
USER 65532:65532
CMD ["python", "-m", "pytest", "tests", "-q", "--basetemp=/tmp/security-master-tests", "-p", "no:cacheprovider"]

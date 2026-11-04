# SPDX-License-Identifier: Apache-2.0
# Context is an exact source archive containing these paths.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONTZPATH="" HOME=/tmp
WORKDIR /opt/calendar
COPY v11/calendar-source/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock
COPY calendar-core/openbq_calendar/ ./openbq_calendar/
COPY v4/routes/openbq_routes/calendar_v1.py ./calendar_v1.py
COPY v11/calendar-source/service.py ./service.py
ARG SOURCE_REVISION
ARG SOURCE_ARCHIVE_SHA256
LABEL org.opencontainers.image.title="OpenBQ bounded calendar source" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      io.openbq.source-archive-sha256=$SOURCE_ARCHIVE_SHA256
USER 65532:65532
HEALTHCHECK --interval=10s --timeout=4s --start-period=30s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6906/health',timeout=3).read()"]
CMD ["uvicorn", "service:application", "--factory", "--host", "0.0.0.0", "--port", "6906", "--no-access-log"]

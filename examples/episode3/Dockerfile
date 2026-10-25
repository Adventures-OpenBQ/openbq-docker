# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS source
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG REF_BACKEND_REF=a6293707576e16edda8305adda95b07b6a4b968b
RUN git init --quiet /source \
    && git -C /source fetch --quiet --depth 1 https://github.com/openbq-org/backends-for-openbb.git "$REF_BACKEND_REF" \
    && git -C /source checkout --quiet FETCH_HEAD
COPY assemble.py source.json patch-cors.py patch-pdf.py reference_app.py server.py apps.json data.json /recipe/
COPY assets /recipe/assets
RUN python /recipe/assemble.py /source /assembled

FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ENV HOME=/tmp PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install -r /tmp/requirements.lock && python -m pip check
WORKDIR /app
COPY --from=source /assembled /app
COPY check-omni-gate.py test_reference.py /checks/
RUN chmod -R a+rX /app /checks \
    && chown -R 10001:10001 /app \
    && python /checks/check-omni-gate.py \
    && EXTRA_CORS_ORIGINS=https://demo.example.org PYTHONPATH=/app python -m unittest discover -s /checks -p test_reference.py \
    && rm -rf /checks
USER 10001:10001
RUN python -c "import reference_app"
EXPOSE 17783
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:17783/health', timeout=5)"
CMD ["uvicorn", "reference_app:app", "--host", "0.0.0.0", "--port", "17783"]

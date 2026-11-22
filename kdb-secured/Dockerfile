# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# Derive locally from the operator's existing licensed q runtime recipe/image.
# No runtime credential or license is copied into the image.
ARG KDB_BASE_IMAGE
FROM ${KDB_BASE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
# Server bootstrap is stdlib-only; pandas/PyKX remain client-side dependencies.
COPY v10/kdb/source/openbq_kdb /opt/openbq-server/openbq_kdb
ENV PYTHONPATH=/opt/openbq-server PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-m", "openbq_kdb.bootstrap"]

# syntax=docker/dockerfile:1
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
# The OpenBB MCP server on this episode's API image, built locally first by
# docker-compose.v3.yml (openbq-api, the Dockerfile's v3 stage). Compose passes that image in
# as the `base` build context, so nothing is pulled from a registry.
ARG BASE=openbq-local:10.0.0
FROM ${BASE}
COPY requirements.lock /tmp/mcp-requirements.lock
# The base pins every dependency (fastapi, fastmcp, mcp, openbb-core, sse-starlette).
RUN python -m pip install --no-deps --only-binary=:all: --require-hashes -r /tmp/mcp-requirements.lock \
    && python -m pip check \
    && rm /tmp/mcp-requirements.lock \
    && openbb-build \
    && python -c "from openbb import obb; assert hasattr(obb, 'calendar'); print('obb.calendar OK')"
# The base image's healthcheck probes the REST API on 6900, which this image does not serve.
HEALTHCHECK NONE
CMD ["openbb-mcp", "--host", "0.0.0.0", "--port", "6901", "--default-categories", "equity", "--tool-discovery"]

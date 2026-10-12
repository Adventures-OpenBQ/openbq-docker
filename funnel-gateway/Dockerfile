# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

# The stack's public door (openbq-docker v10.0.0, `web` profile; ported from openbb-docker
# v8.0.3, with the /grid family from v10.1.7): node:22-alpine plus a pure-JS npm ci.
# Built from ./funnel-gateway alone -- the policy lives beside the server now,
# so nothing is copied from outside this directory.
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY policy.mjs config.mjs server.mjs entry.mjs healthcheck.mjs verify.mjs check-upstreams.mjs ./
# A fresh named volume inherits the mount point's owner, and Docker creates it root-owned
# unless the image already carries it. The service runs as uid 1000, so without this every
# /state PUT would fail its mkdir and 502 on a volume the operator just declared.
RUN mkdir -p /var/lib/bdobb/state && chown node:node /var/lib/bdobb/state
USER node
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["node", "healthcheck.mjs"]
CMD ["node", "entry.mjs"]

# Reproduce the historical OpenBQ environment

Copyright 2026 SecretoftheUniverse.com LLC. Licensed under Apache-2.0; retain upstream licenses and notices.

This checkpoint exports source without importing the old repository history, accounts, volumes, credentials, Tailscale identity, or machine-specific evidence. Privacy hooks and ignore rules were carried forward from the current publication candidate.

```sh
gh auth login
gh repo clone Adventures-OpenBQ/openbq-docker
cd openbq-docker
git checkout v1.0.0
gh release download v1.0.0 --repo Adventures-OpenBQ/openbq-docker --pattern 'openbq-v1.0.0-images.tar.gz' --pattern 'SHA256SUMS'
shasum -a 256 -c SHA256SUMS
gzip -dc openbq-v1.0.0-images.tar.gz | docker load
cp ts.env.example ts.env
cp credentials.env.example credentials.env
```

Supply your own Tailscale authentication and provider credentials in ignored files. Configure the placeholder Serve domain for your own tailnet. The private repository and release assets require access granted by the organization. Images are the original NAS linux/amd64 builds; ARM hosts require amd64 emulation.

Start the backend with `docker compose up -d --no-build`. Backend settings and user data live in named volumes; no personal state is included. The original backend exposed 927 widgets and 1,148 paths; selected smoke/data checks passed, rather than qualification of every external provider.

Original backend image ID: `sha256:4b6bbfc98174821d97c3b33cd5c7eaa908f6e6cd91a3939ab6437a6bc420d96f`. This is the Episode 1 ODP backend without Workspace or the v3 Yahoo extension. Source tree checkpoint: `627396863ee32f2dff74e5fd336eb896d3bb9427`.

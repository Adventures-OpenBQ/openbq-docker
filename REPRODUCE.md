# Reproduce the historical OpenBQ environment

Copyright 2026 SecretoftheUniverse.com LLC. Licensed under Apache-2.0; retain upstream licenses and notices.

This checkpoint exports source without importing the old repository history, accounts, volumes, credentials, Tailscale identity, or machine-specific evidence. Privacy hooks and ignore rules were carried forward from the current publication candidate.

```sh
gh auth login
gh repo clone Adventures-OpenBQ/openbq-docker
cd openbq-docker
git checkout v2.0.0
gh release download v2.0.0 --repo Adventures-OpenBQ/openbq-docker --pattern 'openbq-v2.0.0-images.tar.gz' --pattern 'SHA256SUMS'
shasum -a 256 -c SHA256SUMS
gzip -dc openbq-v2.0.0-images.tar.gz | docker load
cp ts.env.example ts.env
cp credentials.env.example credentials.env
```

Supply your own Tailscale authentication and provider credentials in ignored files. Configure the placeholder Serve domain for your own tailnet. The private repository and release assets require access granted by the organization. Images are the original NAS linux/amd64 builds; ARM hosts require amd64 emulation.

Start the backend with `docker compose up -d --no-build`. Backend settings and user data live in named volumes; no personal state is included. The original backend exposed 927 widgets and 1,148 paths; selected smoke/data checks passed, rather than qualification of every external provider.

## Workspace browser environment

```sh
cp workspace/runtime.env.example workspace/runtime.env
cp workspace/ts.env.example workspace/ts.env
docker compose --profile workspace up -d
```

Set your own account settings and dedicated Tailscale identity before starting. The original Workspace image is `sha256:04222ea5bd191fd4a2fd4db9c01714bb882fa97fb3b3610b1cad43f47b7bc142`, built from official Workspace commit `be00e95019a55d57af146919ee46b7e1a4859226` with the three included patches. It runs from the main `docker-compose.yml` under the `workspace` profile, on its own `openbq-workspace` tailnet node, network (MTU 1500) and `openbq-episode2_workspace-data` volume. The saved source records the actual resolved Poetry lock and runtime package inventory.

The historical browser session rendered the local login form, signed in, and discovered 927 widgets, 38 apps and 7 prompts with Validate widgets set to No. Private HTTPS and raw-port isolation passed; selected backend responses passed separately. Dashboard save/reload, persistence after recreation and backup/restore were not completed in that rehearsal. The Workspace cancellation proposal was not included in the deployed image.

The v2 backend adds the deployed BLS/TMX provider fixes in `provider-fixes/`. It does not contain the later v3 Yahoo extension. Workspace accounts, dashboards and generated application secrets live in its separate named `/data` volume. Create new state rather than sharing the original user's volume or logs.

For source rebuilds, follow `workspace/README.md`. The archived image preserves the actual build: the original build re-resolved Poetry dependencies and downloaded unpinned external font/OS assets, so source pins alone do not establish a byte-identical rebuild.

The release gives the archived backend and Workspace images stable `2.0.0` aliases; their image configuration IDs are unchanged. Compose uses those aliases instead of the original candidate labels.

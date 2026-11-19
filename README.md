# OpenBQ — Episode 2: original Workspace companion

A source-built OpenBB V5 backend and an optional self-hosted original OpenBB Workspace/Lite, with separate private HTTPS Tailscale sidecars. This is an independent recipe using the OpenBQ-stewarded packages whose commands remain `openbb-*`.

Start with [REPRODUCE.md](REPRODUCE.md). Readers can verify the backend using [keyless sources and public demo credentials](DEMO-VERIFY.md); registered-key regression evidence is separate. The release's source archive and checksums describe this recipe. Historical image IDs in older receipts are not downloadable-image promises.

## Backend

```sh
cp ts.env.example ts.env
cp credentials.env.example credentials.env
chmod 600 ts.env credentials.env
mkdir -p ts-state
# Configure a dedicated Tailscale auth key and optional provider credentials.
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

For a fresh reader rehearsal, use the separate checkout and demo override in [DEMO-VERIFY.md](DEMO-VERIFY.md). It selects only the public EIA and Congress.gov tokens; BLS supports anonymous series queries. FRED requires registration. Do not copy another installation's credentials, account stores or Tailscale identity.

Generate a dedicated, non-reusable, non-ephemeral auth key in [Tailscale](https://login.tailscale.com/admin/settings/keys). Use pre-approval if your existing policy requires it. Enable MagicDNS and HTTPS certificates, and use server tags only when their existing access policy is appropriate. Read the actual node hostname from `docker compose exec tailscale tailscale status --json`.

From an authorized tailnet client, run `python3 scripts/smoke.py https://YOUR_ACTUAL_HOST` and the isolation check described by `scripts/verify-isolation.sh`. A smoke pass needs a nonempty catalogue, OpenAPI and Cboe quote. Provider data tests require real observations, not merely HTTP200. The host administrator and authorized Docker bridge members can also reach the API; the recipe does not isolate it from host administrators.

## Optional original Workspace

Follow [workspace/README.md](workspace/README.md) to assemble and build the archived original snapshot, then:

```sh
cp workspace/runtime.env.example workspace/runtime.env
cp workspace/ts.env.example workspace/ts.env
chmod 600 workspace/runtime.env workspace/ts.env
mkdir -p workspace/ts-state
# Configure the companion's own identity and actual HTTPS origin.
docker compose --profile workspace up -d
```

Workspace has its own node, bridge and account/dashboard volume. Its login protects Workspace accounts; the backend remains a separate tailnet service. Both Serve configurations disable Funnel. The base recipe preserves the former standalone Workspace volume for migration. The reader override instead gives each rehearsal project its own Workspace volume and image tags.

The original Workspace source is pinned at `be00e95019a55d57af146919ee46b7e1a4859226`. It is an archived control, with explicit packaging patches and recorded locks, rather than a claim of ongoing original-vendor updates. FINOS Workspace is a separate successor; compatibility with unchanged OpenBB widget catalogues must be measured rather than assumed. No FINOS renderer migration is included here.

Keep generated account credentials, private logs, provider keys and identity state out of source and published evidence. Workspace state is separate from backend settings and from BDOBB. Copilot/model services are disabled in this episode; later Rita functionality belongs to its own release.

## Build and historical evidence

The backend uses the pinned package lock and hash-gated provider overlay. Original provider attribution is retained in [provider-fixes](provider-fixes/README.md). Backend source builds target Linux AMD64 and ARM64; the original Workspace runtime build is the AMD64 path and needs emulation on an ARM host.

These are version-pinned recipes, not a promise of byte-identical image rebuilds: OS packages and original frontend font downloads can change independently. Consult the release receipts for actual source/image/platform and live-test results. [VERIFICATION.md](VERIFICATION.md) retains historical evidence and must not be interpreted as a new physical NAS test of every retagged source.

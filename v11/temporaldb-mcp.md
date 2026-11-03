# Opt-in TemporalDB MCP

Add `-f v11/compose.temporaldb-mcp.yaml --profile mcp` to the existing v11
Compose invocation. The adapter uses `http://temporaldb-api:8080`, and publishes
no host port. Connect existing trusted ingress to port 8081 and `/mcp`. The stack's own route is the Tailscale Service `svc:openbq-temporal-mcp` ([RUNBOOK](RUNBOOK.md#tailnet-names-tailscale-services)).

The adapter runs the same pinned local image ID as `v11/compose.temporaldb.yaml`
and depends on `temporaldb-api`. Set `TEMPORALDB_MCP_ALLOWED_HOSTS` to an exact JSON ingress
host/port list, `TEMPORALDB_MCP_ALLOWED_ORIGINS` to explicit browser origins (or
`[]`), and `TEMPORALDB_MCP_POLICY_HOST` to a private credential policy readable by
uid 65532 with mode 0600 or 0400. MCP replicas receive only this private mount and
the fixed API origin. They do not receive the API/worker environment files.

The producer's `docs/mcp.md` gives the credential-policy shape and generic client
setup. Tokens map to explicit workspace/principal/entitlement and capabilities;
the API independently checks that the downstream token has the same scope.
Use `--scale temporaldb-mcp=2` for stateless replicas with shared control state.
Existing verified runtime archive provisioning remains required for API/worker.

Rita is reached through bdobb's existing discovered-tool bridge. Configure MCP in
bdobb, whose tool descriptors and results travel through its existing Rita flow.
MCP-saved definitions appear in the ordinary shared query library. Widgets keep
the selected explicit revision when a newer revision is saved.

This overlay does not enable a public deployment or provider acquisition. The
candidate qualification report distinguishes protocol, widget, Rita and restored
protected-run evidence. Historical provider-host settings/Workspace/FUSE evidence
retains its original source and image identities.

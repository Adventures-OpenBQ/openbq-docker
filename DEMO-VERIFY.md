# Verify the reader installation

The reader pass uses keyless sources and public demo tokens. A separate registered-key pass expands coverage; registered success cannot substitute for this installation check.

Use a new checkout dedicated to this reader rehearsal. Never run this procedure inside an installation holding registered credentials or existing Tailscale identity state:

```sh
git clone --branch v1.0.0 https://github.com/Adventures-OpenBQ/openbq-docker.git openbq-reader-v1
cd openbq-reader-v1
```

Follow README.md there to configure a **new dedicated Tailscale node** with its own `ts.env` and `ts-state`. Then build with the reader override. It selects the public demo file directly and uses a distinct local image tag; it does not overwrite `credentials.env`:

```sh
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml config --quiet
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml build
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml up -d
docker compose -p openbq-reader -f docker-compose.yml -f docker-compose.demo.yml ps
```

Do not copy a registered installation's OpenBB data volumes or Tailscale identity state. The public demo file contains only EIA and Congress.gov demonstration tokens; FRED requires separate registration. BLS series requests support anonymous access with lower provider limits; a registered BLS key raises those limits. BLS publication endpoints and CFTC fetchers also work without a registered key, even though their provider metadata declares credential fields.

From another trusted tailnet device, run the recipe's `scripts/smoke.py` and `scripts/verify-isolation.sh` against the node's actual HTTPS hostname. Smoke acceptance requires nonempty catalogues/OpenAPI and a nonempty Cboe quote. TCP 6900 must remain inaccessible from that device. Verify the same APIs from the Docker host separately; host access does not prove tailnet isolation.

The public demo tokens have provider-imposed request limits. Use the widget's documented choices, valid dates/facets and bounded limits. The large EIA widgets open with a bounded newest-page selection; full datasets need explicit filters/limits or their bulk-download facilities. A 200 response must contain the expected data; an empty response or a displayed error is not a data pass. Deliberately invalid input tests are recorded separately.

Demo tokens are documented by [EIA](https://www.eia.gov/opendata/documentation.php) and [api.data.gov](https://api.data.gov/docs/api-key/). Do not put registered keys in logs, source files or published receipts. Registered credentials for the maintainer's qualification are supplied from the secret store at runtime.

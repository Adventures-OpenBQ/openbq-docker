# Isolated recipe regression mode

The release walk needs repeatable fresh containers and provider caches without
discarding reusable image layers or changing a recipe's volume ownership.
The user authorized implementation while V8 native testing continues, with the
first release-walk uses on V9 and V10. Existing release assemblies stay separate.

## Approach

A small Python wrapper reads Compose's canonical model and runs an isolated
project selected with `--regression`. Docker Compose builds selected services
using its ordinary input-aware layer cache. Blanket image rebuilds and manual
`docker run` setup were rejected because the former wastes qualified work and
the latter can drift from recipe behavior. This choice follows the user's
standing instruction to proceed without routine design questions.

Each run has a new project identity. Named volumes get new private names and
normal Docker initialization: do not apply `volume-nocopy` to application data.
Read-only configuration binds remain; writable directory binds become new owned
state volumes. Writable file binds, external volumes, host networking, published
ports and pre-existing container namespace references are refused rather than
silently sharing deployment state. Service namespace references within the
selected dependency closure remain supported. No Docker prune is allowed.

The command accepts Compose files, selected services, an optional verified
prebuilt-image binding, a private result receipt and a check command following
`--`. It builds only the selected dependency closure, creates fresh containers,
runs the check with project/container identities in environment variables, and
always removes its own containers, networks and volumes. Prebuilt services need
an explicit image-ID binding; changed build inputs go through Compose build.
It never prints resolved credentials or writes resolved env-file values.

Receipts contain image IDs, source revision, service names and cleanup outcomes.
They contain no container environment, private configuration or matched secrets.
The wrapper does not decide whether a provider response or native workflow passes;
the existing separate reader, registered and native checks retain those gates.

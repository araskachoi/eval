# Mandatory test boundary

Potentially malicious test content and generated test code may run only in the
dedicated disposable Linux VM and verified rootless containers. No host fallback.
Normal collector controls and rendering are trusted application code, not a
mechanism for executing a test payload.

## Effective controls

- Dedicated VM: no virtiofs/9p host-sharing mounts, no USB devices, rootless engine.
- Container: UID/GID 1000, no capabilities, no-new-privileges, seccomp enabled,
  private namespaces, no devices, no bind mounts, read-only image filesystem.
- No workload network, exposed ports, host services, real keys, inherited user
  config, SSH agents, runtime sockets, connectors, or production data.
- Bounded /work and /tmp tmpfs, file sizes, file descriptors, processes, CPU, RAM,
  and total execution time. Reviewed dependencies are staged before testing.
- Trusted launcher controls the runtime; the workload cannot control it. Only
  reviewed files are copied through stdin, never shared as writable host mounts.
- Containers are inspected before start and removed on interruption/failure.
  VM startup is separate from measured execution.

Image contents and source are identified by digest. A mutable image tag is only
used during explicit staging; execution resolves and uses the local image ID.
Review registry/image provenance before staging. No image pulls occur during tests.

## Development provisioning

Use the existing bundled Podman executable only after review. On this Mac, the
dedicated machine is `eval-sandbox` with Apple virtualization. The initial libkrun
attempt could not start; it was not used for tests.

Creation must explicitly request rootless operation and an empty volume list;
Podman defaults can share host directories. Do not reuse the unrelated
`rea-research` VM. Do not install the rootful macOS helper.

`scripts/isolated.py hold` starts and holds the dedicated VM in a managed foreground
session; Ctrl-C stops it. `preflight` verifies configuration plus effective engine
and guest mount state. `test --magen PATH` starts only an inspected, networkless
rootless workload. MAGEN source is copied; its repository is never mounted.

Initial tests use fake endpoints and synthetic credentials only. External APIs
and host Ollama are not accessed. Root filesystem inside the container is its
reviewed image, not the host root filesystem.

If runtime verification fails, stop affected execution. Do not enable rootful
operation, privileged mode, extra mounts, host networking, or real credentials
to make a test pass. User-facing diagnostics must distinguish containment tests
from detector and real-model effectiveness tests.

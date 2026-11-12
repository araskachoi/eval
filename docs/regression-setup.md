# Set up local regression on Apple Silicon macOS

The supported setup uses Python 3.14, the reviewed Podman 6.1.4 ARM64 client,
Apple virtualization, and the dedicated rootless `eval-sandbox` VM. Keep
the checkout and its private `.runtime` directory together.

## Provision the dedicated sandbox

1. Obtain the reviewed Podman ARM64 package. Verify its signature and checksum
   before expanding it locally. The reviewed 6.1.4 package has SHA-256
   `48f675622f66233ca2116e67fdab41ed9dbcc25b48b78a8e6ef0be6549031d22`.

   ```sh
   pkgutil --check-signature /path/to/podman-6.1.4-arm64.pkg
   shasum -a 256 /path/to/podman-6.1.4-arm64.pkg
   mkdir -p .runtime
   pkgutil --expand-full /path/to/podman-6.1.4-arm64.pkg .runtime/podman-package
   ```

2. Obtain a reviewed, local AppleHV machine image for the same Podman version
   and its trusted SHA-256. Use the exact reviewed image on machines you plan
   to compare. The setup command requires both the image and checksum and
   creates a private configuration with zero host volumes. It refuses to
   replace an existing machine or a different volume policy.

   ```sh
   python3.14 -B scripts/isolated.py init --machine-image /path/to/reviewed-image \
     --machine-sha256 REVIEWED_SHA256
   ```

3. In a dedicated terminal, hold the VM open for the benchmark. In another
   terminal, stage the digest-pinned Python container and run both dummy-only
   qualification checks.

   ```sh
   python3.14 -B scripts/isolated.py hold
   ```

   ```sh
   python3.14 -B scripts/isolated.py preflight
   python3.14 -B scripts/isolated.py stage
   python3.14 -B -m codex_eval regression qualify --benchmark filesystem-v1 --protocol independent
   python3.14 -B -m codex_eval regression qualify --benchmark ledger-v2 --protocol independent
   ```

The qualification commands exercise the same grader as real submissions.
They check a reference and deliberate failures with no inference or model
credentials. Filesystem qualification also requires the guest's Landlock
support. If a check fails, inspect the isolation boundary before running any
benchmark. Stop the VM from its hold terminal when finished.

## Run and verify a release

Use the [regression guide](../regression/README.md) for explicit baseline and
candidate runs. Keep the model revision, harness version, benchmark digest,
and run settings in the saved manifests. Codex CLI use requires a separate
trusted inference process with its own credentials. The network-disabled
grader receives only synthetic fixtures and submitted code.

For a source checkpoint, run the complete isolated suite using a reviewed
MAGEN source revision.

```sh
python3.14 -B scripts/isolated.py test --magen /path/to/reviewed/magen --no-export
```

The suite exercises the dummy-only kernel boundary and fails if the probe
can write or remove the outside-fixture canary or start a child process.
The [managed publisher](releases.md) runs the isolated suite before activation.
Keep result folders local and manage their lifetime manually.

[Podman machine initialization reference](https://docs.podman.io/en/latest/markdown/podman-machine-init.1.html)

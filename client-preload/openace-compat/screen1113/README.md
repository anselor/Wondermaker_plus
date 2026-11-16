# Native openACE screen: source and reproducible build

This directory contains the editable native C++ source, vendored JSON header,
portable tests, recorded fixtures and the sealed prebuilt ARM library. It reuses
`../wmp_openace_compat.c`, already in this repository, for the original C hooks.
No file from a developer's review-artifact directory is needed to build or test.
Historical121 review records under `review-history/` retain their old meaning;
they are not renamed into the new repository-path source manifest.

## Build

From the repository root:

```sh
bash client-preload/openace-compat/screen1113/build-offline-arm.sh
```

Requirements: Docker (and access to its daemon), the exact image digest in
`toolchain.json` already present locally, Python3.8+ and ordinary host filesystem
space. The container runs with networking disabled and contains the AArch64
cross compilers/binutils; the printer does not need g++. The repository does not
claim to contain that toolchain image: obtain that exact image through your normal
Docker image provisioning before running the build. `toolchain/` contains the
actual package/image history and a clearly labelled reconstructed Dockerfile;
that recipe does not promise the exact frozen image ID. No automatic toolchain
upgrade or on-printer build occurs.

The preserved `/src`, `/baseline`, `/out` mount paths and flags make the same
source produce the reviewed relinked ELF. Explicit `-ldl` follows the objects;
the ABI remains dlsym@GLIBC_2.17, with NODELETE. `repack-source.py` creates the
repo-relative `source-inputs.json`, deterministic `source.tar.gz`, exact descriptor,
and descriptive provenance from actual bytes. Its source archive contains every
build input, including the existing legacy C and packaging ELF helper; extract
at an empty directory root and run the same relative build command to reproduce.
A build is not an independent review, installation or physical qualification.

## Tests

Portable tests live under `tests/`; they require pytest, a host g++, capstone and
Unicorn. The ABI proof tests read the existing repository firmware fixture
`analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client`. Tests build disposable
host executables under ignored `build/`; that is not ARM UI execution.

The 31-case cross-repository integration under `tests/integration/` additionally
requires a declared openACE source checkout and its Python test dependencies:
set `OPENACE_NATIVE_BACKEND` to its absolute root and put that same root first
in `PYTHONPATH`. Tests assert the actual imported source root. Without that
explicit dependency, the integration modules report skips. These are test
inputs, never printer configuration or runtime qualification flags. Historical
fixture-capture scripts and superseded B-pinned backend snapshots stay in review
history, not in product test collection.

Actual screen layout/touch/Stop/modal, native client installation/restart and
physical filament handling remain separate attended gates. The owned manual
panel supports integer procedures and does not replace the stock opaque loader.

The vendor executable fixture is optional and is not git-tracked or part of the
application build/install. If absent, actual-profile/ABI tests skip with the exact
missing vendor version; basic source/package/unit cases still run. With a real
fixture available, those cases run unchanged against its guarded fingerprint.
The authoritative gate reports the actual available fixtures and all skips; a
source-only build is not evidence those optional proofs were executed.

# Toolchain provenance

The reproducibility gate uses the exact cached image ID recorded in
`../toolchain.json`; its current local tag is `wmp-inject-build:bullseye`.
`provenance.json` records the actual image metadata/history and installed cross
compiler/package versions. The original Dockerfile was not available. This
Dockerfile is an honest reconstruction of that recorded recipe, not a claim
that fresh Debian/apt state yields the same image ID or bit-identical toolchain.

The repository contains all native application/build sources but not a Docker
image distribution. Provision the exact recorded image through your normal
image cache/export mechanism before the default build; `docker image inspect`
refuses a missing image and the build never silently upgrades it. To preserve
an existing image elsewhere, use normal `docker image save` / `docker image load`
and verify its ID. A release promising public bit-identical rebuilds must also
make that pinned image/export obtainable. Building this Dockerfile produces a
new toolchain which must be deliberately selected/reviewed; it is not silently
substituted for the frozen one. No printer package/compiler installation occurs.

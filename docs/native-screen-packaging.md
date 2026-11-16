# Exact-profile native screen package

The existing `preload` component retains its original C fixes and component names.
`openace-compat/screen1113/bundle.json`, when present, describes one sealed prebuilt
AArch64 combined library: original C Resume/heater hooks plus C++ native screen.
It installs ONLY to the existing `libwmp_openace-compat.so` name on the exact
reviewed1113 client; it is not a second preload alongside the old compat hooks.
Older supported profiles use the unchanged C compile path. Unknown/modified
clients still fail the original preflight; runtime address guards remain.

The delivered descriptor now binds the independently reviewed121-input C5 screen
source/archive and exact ARM artifact SHA
`2d2ac997674dcc5f14a14a86f8e6c87a0341a3c7a00ec9fd9318f896a27f829c`.
`review-provenance.json` links the frozen source and independent software review.
This replaces the actual previous104 management library; it is not a relabeling.
The121 screen includes owned paused manual reload for integer procedures only.
Fractional requested/remainder amounts remain explicitly unsupported by this UI,
with the separate backend contract under review; this is not unrestricted numeric
or complete hardware qualification. A later changed native seal needs a new binding.
The original control-only bundle remains verbatim under
tests/fixtures/native-screen-control and is still refused for delivery.
No ARM execution, installed export, layout/touch, printer or deployment approval is
established by this package. Its head-specific owners and explicit actions do not
intercept the stock opaque filament loader.

The descriptor records exact profile/artifact lengths and SHA256, ELF AArch64,
NODELETE/dependencies, source-manifest/archive provenance and legacy C hash.
Local integrity, uploaded bytes and prospective output bytes are checked. A
stdlib verifier parses ELF metadata; it never loads the candidate. Disposable
remote preflight and staged selection invoke existing glibc `ldd -r` to check
actual library/symbol resolution WITHOUT executing candidate initializers. Missing
ldd/dependencies/timeouts refuse; no implicit apt, g++ rebuild or library upgrade.
The copied client version list alone is not target-export evidence. The actual
remote dependency port remains an approved-deployment prerequisite.

All selected preload outputs are staged outside the live library glob. Their
hashes are verified before publication. Known destination files and the one
service drop-in are backed up; individual replaces are recoverable, not a claim
of one filesystem-atomic multi-file operation. Duplicate compat/screen library
names refuse. The existing no-print gate remains and is rechecked before publish.
Publication lost replies and restart failures attempt current owned-file repair;
if the connection/repair fails, the failure says recovery is unconfirmed and
retains the staging journal. A retained failed stage is not active or auto-retried.
No generic crash/power-loss rollback is promised. Uninstall removes the same
owned combined-or-legacy component name; identities/configuration are untouched.

Status distinguishes local scope, exact installed bytes, current process/maps
and existing current-PID C diagnostics. The UI121 bundle has no new native application
log, so status explicitly says native hook/backend application is unconfirmed.
It never mistakes an old compat log or mapped filename for rendered UI success.
NODELETE/process-start ownership prohibits hot unload/injection claims.

## Build-only dynamic-loader dependency correction

The previous reviewed121 ELF failed its real target preflight with an unresolved
`dlsym`. The new link recipe adds `-ldl` after the existing native/compat objects.
Every reviewed C/C++ source byte, original C hook, runtime helper and target
profile remains unchanged. The exact relinked ELF now declares `libdl.so.2` and
`dlsym@GLIBC_2.17`; it does not introduce a GLIBC2.34 requirement. The original
undefined-symbol RED is preserved; the same unmodified packaging preflight now
passes against the actual1.1.13 target in a disposable, non-active scratch path.

Provenance distinguishes actual target dependency/relocation verification from
installed-candidate/UI execution. `target_dependency_exports_verified` is true;
`installed_exports_verified`, `installed` and `native_application_verified` remain
false. No constructor, native widget or printer action was used as a probe.
The required attended screen/touch/Stop/modal acceptance is still outstanding.

## Repository-complete source union

`client-preload/openace-compat/screen1113/source` contains all17 production native
source/header inputs. The repository's existing compat C file is reused. The
repo-relative build/repack scripts, pinned toolchain metadata/recorded recipe,
review history and the actual source archive are shipped beside the prebuilt
ELF. The31-entry source manifest uses repository-relative paths; it is a new
build-input layout, not a relabeling of the historical121 review manifest.

The source/archive binding is checked locally only when the actual target
selects the native screen bundle. Older supported C-only profiles and packages
with no native bundle retain their previous path and need no native source
archive or C++ compiler. Target staged ELF/dependency checks are unchanged.
Missing/tampered native source or archive refuses before publication, with an
ordinary deployment error; it does not alter installed files or restart a UI.

The source archive contains every application/build input and can be extracted
at an empty root and rebuilt using the same relative command. Docker/the exact
compiler image remain declared host build dependencies, not source that the
repository pretends to contain. `toolchain/` records real compiler versions and
an explicitly reconstructed Dockerfile; exact frozen-image availability remains
necessary for the claimed bit-identical rebuild. No printer compiler install.

## Unreleased unified-screen qualification

Exports default to `packaging-control-only`; normal installation refuses that scope.
Feature work should keep that scope until its release review is complete. The
checked-in release package may use `reviewed-delivery`. Package integrity tests
accept either scope; they do not grant release qualification.

For development qualification, use the exported installer:

```sh
uv run --python 3.12 --with paramiko --with jinja2 python tools/deploy.py install config material preload --qualify-unreleased-screen --preflight-only
```

This opt-in requires the current unified bundle and its exact supported client;
it cannot fall back to the legacy screen. Artifact integrity, source/archive
binding, target dependencies, and backend/configuration checks remain required.
It neither rewrites the descriptor nor promotes the package to a release.
Preflight checks do not install components or restart services. Removing
`--preflight-only` performs installation and the required restarts, so establish
the preservation and recovery baseline before that step. Qualification is not
clean-install acceptance until the actual installation, startup and recovery
behaviors have been demonstrated on the agreed target.

## Export after release review

After the release checklist is accepted, export a new directory with
`tools/package_unified_ui_delivery.py --candidate <candidate> --client <exact-client>
--output <new-output> --reviewed-release`. This explicit operator assertion writes
the supported `reviewed-delivery` scope, allowing normal installer checks without
the development qualification flag. It does not determine whether review is
complete, install anything, or publish a release. Do not use it to bypass an
outstanding acceptance item.

The default remains `packaging-control-only`. Both paths validate the candidate,
exact vendor client, artifact and complete source binding before atomically
publishing a new output directory. Normal installation still validates target
dependencies and backend compatibility. The exporter never edits an existing
qualification bundle in place.

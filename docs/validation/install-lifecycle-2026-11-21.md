# r4 install lifecycle validation — 2026-11-21

Branch: `fix/r4-install-lifecycle`, based on released r4 `8519032`.

The branch separates immutable originals from per-update rollback, records shared
helper ownership, restores bridge file/service/camera state, tracks retired
preload payloads, restores recognized legacy inline behavior, and checks removal
before changing its first component. Unified config/material/preload updates use
a matched dependency group. Hardware geometry is outside config reconciliation.

Local verification:

- 1,531 relevant installer, package, native-profile and compatibility tests passed
  in the full run, with no skips. Genuine retained 1.1.12/1.1.13 ELF fixtures and
  Tornado 6.3.3 were available.
- A subsequent static legacy-caller guard and its regression were verified with
  all 141 config/migration tests passing. This catches calls to removed commands
  without a `WMP_` prefix, while recognizing builtins exposed by removing wrappers.
- Sealed source package checks pass; the native screen binary is byte-identical
  to the released r4 artifact. Runtime helper source was not changed.
- Replay of the printer's preserved 52 `.cfg` files produced zero config changes
  on install and repeat-update, three changes on uninstall, no remaining managed
  dependencies, and a no-op second uninstall. All checked geometry/tuning sections
  were unchanged and all 17 critical macros matched a known vendor variant.
- Read-only removal preflight passed against the printer. The initial refusal
  exposed the distinct vendor active-config/factory-reset `NOZZLE_PREPARE`
  variants; these are now recognized using the retained matching 1.1.13 payload.

The configuration backup is protected local data and is not committed. No broad
log, machine-identity, service-file or binary export was performed.

Live install, repeated update, factory removal and attended print comparison
remain the next validation stage. The passing local checks do not claim a
physical timing result or that every operating-system file is factory content.
See [the comparison protocol](factory-timing-comparison.md).

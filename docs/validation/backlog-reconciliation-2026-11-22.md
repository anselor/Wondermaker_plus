# Backlog and quick-stop reconciliation — 2026-11-22

Candidate: `work/r4-backlog-reconcile`, starting at backlog `5a14436` and merging
published r4 `16bc1f9`. No printer installation, restart, motion or publication
is part of this reconciliation. openACE work remains with its owning agent.

## Quick-stop branch disposition

`fix/quick-stop-flag` ends at `0d36a18`. Its changes are already incorporated as
`b289692`, an ancestor of both published r4 and the backlog candidate. The range
diff differs only in coupling-guard context, where later code passes
`finish_coupling`; the stop flag still comes from the Printer object. Both
versions include the pickup-observation, identification-admission and
between-axis homing regressions. Applying the branch again would duplicate the
fix. Different commit identity was the reason the initial branch inventory
listed it as unmatched.

## Current r4 integration

The merge's only textual conflicts were generated screen source records and
the binary source archive. Preserve the backlog's compiled ARM screen artifact
and regenerate its source manifest/archive using the merged installer sources.
The legacy migration catalog is regenerated against published r4 `16bc1f9`,
retaining known vendor factory variants. Unreleased inline code is not promoted
to published legacy provenance.

The new installer ownership and removal implementation coexists with the
backlog's three additional helper modules and targeted recovery-marker read
permission migration. The latter remains in the stopped-screen activation
path; it does not replace factory resource ownership or rollback bookkeeping.

Legacy uninstall tests now use hash-checked compressed fixtures from published
r4, rather than treating changing candidate macros as previously published
code. Existing preservation/refusal assertions remain, with an explicit
unpublished-inline-edit refusal regression.

## Validation

- Initial focused run: 787 passed, four failed because legacy fixtures followed
  candidate source. After fixture correction, all 13 legacy-removal tests passed.
- All 26 Klipper configuration files pass static validation.
- Sealed package/source binding passes; the compiled backlog artifact is unchanged.
- An initial combined run was interrupted after missing optional native-hook
  fixture copies caused skips. It is not completion evidence. Exact retained
  firmware inputs and the candidate's own sealed artifact were restored locally.
- The first complete run finished with 6,744 passed, four failed, two skipped
  and three existing warnings in 452 seconds. The four failures were obsolete
  restart-result fixtures which supplied unowned overrides and intercepted the
  former shell `rm` path. Tests now create real publication receipts and inject
  unlink failures in the actual Python restoration path; privilege and honest
  failure/no-restart assertions remain. All 36 affected restart/factory/rollback
  tests then passed.
- The two skips were the retained A/B checkpoint-format examples. Their exact
  local copies were restored; they are format-only parser inputs, not admitted
  print-recovery authority. The final full rerun passed **6,750 tests with no skips**, with three existing
  empty-exception-match warnings, in 438.05 seconds. It used Python 3.11, four
  module-scoped xdist workers, Jinja2, Unicorn, Capstone, pyelftools and retained
  Tornado 6.3.3. Log: `/tmp/wmp-backlog-reconcile-final.log`.

## Remaining qualification

Reconciliation does not qualify the new operation-cancel implementation on
hardware. Use the existing 12-family attended matrix, including homing, probe
preparation, identification, tool/filament service, calibration and recovery.
Previously clean print tests used published r4, not this backlog screen/backend.
Off-bed cancellation parking and inspection movement after a dock fault remain
separate tracker tasks and are not silently added to this candidate.

# Earlier screen mockups

These are unchanged copies of the August 24–25, 2026 mockups from the local
`screen-mods` worktree. They preserve prior discussions; they are **not current
production screenshots or a specification of backend behavior**. See the
[consolidated plan](../../ui-plan.md) for what carries forward.

| Mockup | Useful design idea | What is superseded |
|---|---|---|
| [Scrollable mapping](mock-mapping.png) | Show every sliced filament; fixed footer; touch scrolling | Four numbered physical buttons are not the complete openACE tool/source model; Confirm only logged a demo map |
| [Print-start warnings](mock-printstart-warn.png) | Inline compatibility reasons and disabled Print | This earlier image permits PCTG→PETG; that rule was rejected in later discussion. Do not reuse it |
| [Print-start material/hardware constraints](mock-printstart-abrasive.png) | Keep unsupported materials visibly unmapped; distinguish reinforced materials and nozzle requirements | Demo data and heuristic name matching are not authoritative material admission |
| [Filament panel and hex colours](mock-filament-panel-hex.png) | Shared filament workspace, readable swatches, familiar navigation | Buttons were wired to vendor handlers, not an accepted openACE recovery workflow; physical action acceptance was pending |

The later print-start discussion kept PCTG distinct from PETG and ASA distinct
from ABS by default. The plan now delegates compatibility to backend policy,
including explicit overrides where supported, rather than enforcing old UI
string heuristics. Demo filenames/material quantities and shown options are
illustrative.

Original local design notes:

- `.claude/worktrees/screen-mods/docs/screen-modal/README.md`
- `.claude/worktrees/screen-mods/screen/inject/README.md`, iterations 3–8

Those notes include private reverse-engineering history and are not copied here.
`provenance.json` records the unchanged image hashes and original relative paths.

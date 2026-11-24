# R4 filament appearance

Scope: standalone external filament settings. Appearance is separate from
material: Standard, Translucent, Gradient and Co-extrusion. Missing appearance
means Standard, without rewriting old profiles. Save persists an optional
validated `appearance` string and retains the primary hex colour.

Translucent draws a subdued checker pattern in editor, filament cards, Home
mini-panel and mapped destination swatches. Cells reuse view widgets on stable
updates; circular swatches retain their circular outline. Gradient and
Co-extrusion save the classification but retain the primary solid colour in R4.
Additional colours, blended gradients and radial co-extrusion sectors are R5
work. Existing openACE identity editing is unchanged.

Appearance is excluded from physical recipe comparisons in both frontend and
backend. It does not change temperatures, loaded flags, service ownership or
recovery/print recipe admission. The editor keeps appearance drafts when a
material/profile changes and clears them on cancellation or completed save.

## Host validation

- New backend appearance persistence/invalid-value tests: 10 passed.
- Initial broad material/recipe run: 1,712 passed, 5 failures and 18 setup errors.
  The failures traced to the earlier R4 finish macro changes missing from the
  reviewed recovery effect fingerprints, not appearance data. Local c272f3e
  updates those two bodies and guards both new helper dependencies.
- Recovery, active recipe and cosmetic regressions after that correction:
  89 passed. Expanded macro tampering checks: 45 passed. Final cosmetic suite,
  including ordinary print startup with all four appearances: 23 passed.
- Native lifecycle/factory-font checks: 2 passed. These exercise selection,
  material preservation, checker geometry, and 100 stable updates without new
  widget allocations in both editor and Home; Standard hides the checker.
- Remaining UI and package checks: 74 passed, 2 skipped (optional emulator
  tests in that invocation). Native/font tests above used Unicorn separately.
- Explicit standalone request encoding/cosmetic admission follow-up: 1 passed.
- ARM artifact SHA256:
  `fe7a33a21f150cdd82e0e1c26f1af17ecba975a142e6c19acfe2779514ab5baf`.
  Reviewed delivery staged; screen package freshness check passed.

On-printer save/reopen verified: Head 3 defaulted to Standard, all four choices
were visible, Translucent saved and remained selected on reopening. Backend
comparison showed only appearance changed. All original filament attributes
were then restored exactly; heaters stayed off and no motion was commanded.
Evidence is in analysis/appearance-live-20261124/.

The first card review found checker cells extending into the stock image's
transparent padding. The final renderer insets those cells (and removes cell
borders), retaining the native smooth outline. Final native lifecycle/font
checks passed both cases in 70.50 seconds, including inset geometry. Final card
and Home screenshots confirm the corrected drawing on the installed candidate.
The exact original profiles were restored again afterward, with all heater
targets zero. Final package checks passed all 31 cases. Installer verified
Klipper Ready, artifact identity and native GUI/status synchronization (screen
PID 311287). The installed functional commit is c4d2320; this final documentation
record does not change its code or package.

Actual installed macro settings and transform-file hashes satisfy the corrected
reviewed recovery contract (installed-effect-proof.json in the same directory).
No release push, merge or tag is implied.

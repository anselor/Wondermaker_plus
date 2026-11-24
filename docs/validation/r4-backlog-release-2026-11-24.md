# R4 backlog release validation — 24 November 2026

## Scope

Candidate: work/r4-print-time-fixes, based on published R4 16bc1f9.
This is a scoped backlog/filament/startup release, not a claimed resolution of
intermittent extrusion timing, Z timing or print-stutter/CPU investigations.

The development history is consolidated into four logical changes: cooperative
cancellation/calibration checkpoints and progress; filament feedback fixes;
pending file-preparation progress and cancellation; and the final colour picker
with release notes. The final source tree and sealed ARM package are preserved.

## Existing evidence

- [Consolidated early-Stop validation](early-stop-consolidated-plan-2026-11-23.md)
  covers changed owners/ingresses/cleanup branches through host tests, exact
  client checks and representative attended physical runs. It does not claim
  every start page was replayed physically.
- [Early file-preparation verification](early-file-preparation-progress-2026-11-23.md)
  records the Vehicles touchscreen start and native Stop before SD execution,
  heating, homing or motion. The separate fallback guard was not needed.
- [Filament feedback checks](filament-feedback-fixes-2026-11-23.md) distinguish
  material/planner tests from physical PETG unload acceptance.
- [Colour picker validation](solid-colour-picker-2026-11-23.md) records native
  selection/lifetime checks, actual font fit, package checks, installation and
  on-device user approval. The final palette offers ten families of six shades.

Final installed ARM SHA256:
`d23fb96bea5346cbcf66119c08ed0b3c0cbefd03f94fa9b81f93ed10a2ff4129`.
The installer verified the running package (PID 130877), native GUI/status
synchronization and Klipper Ready, with zero configuration file changes.

## Final regression gate

The final regression used Python 3.11, four pytest-xdist workers
with --dist loadscope, Jinja2, Unicorn, Capstone, pyelftools and Tornado 6.3.3:

```bash
uv run --offline --python 3.11 --with pytest --with pytest-xdist \
  --with jinja2 --with unicorn --with capstone --with pyelftools \
  --with tornado==6.3.3 --with paramiko \
  python -m pytest -q -n 4 --dist loadscope tests klipper_extras
```

The initial console-entry invocation passed **6,891 tests** in 530.50 seconds,
with three existing empty-exception-match warnings, but could not collect
`tests/test_factory_defaults.py`: that invocation did not put the repository
root on the worker import path. No product test failed. Using `python -m pytest`
collected the entire inventory cleanly: **6,914 tests**. The missing factory
module contains exactly **23 cases**, all of which passed in the corrected
follow-up. That follow-up also repeated release-hygiene and sealed-package
checks: **36 passed** in 3.52 seconds (13 overlap with the main run).

Thus all 6,914 collected cases are covered by passing executions across the
main run and corrected module run; this is not represented as one error-free
full-suite invocation. No production change was made for the runner issue.
Logs: /tmp/wmp-r4-release-final-tests.log,
/tmp/wmp-r4-release-final-gates.log and /tmp/wmp-r4-release-inventory.log.
The final picker-specific native/header checks passed (2), as did all seven
sealed-package checks. Those are overlapping checks, not an aggregate total.

## Remaining scope and limitations

Intermittent motor/extrusion timing and CPU/stutter causes remain investigations.
Gauge repeatability, affected legacy-marker permissions, conditional pre-home
dock clearance and broader artwork/translation presentation retain separately
scoped verification. PETG target selection is tested; a supervised PETG unload
on this printer is not claimed. A full first-run setup, naturally triggered
nozzle disagreement and recovered-print quality are not represented as tested.
Off-bed parking after normal Cancel and scrub preparation detail remain backlog
items rather than implied features of this release.

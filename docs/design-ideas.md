# Earlier design ideas and decisions

This page records proposals from August–September 2026. It is a history of decisions,
not a list of features waiting for approval. Current behavior is documented in the
[configuration guide](../config/README.md).

## Probe with the first print tool: implemented

Implemented August 30, 2026; enabled by default September 13 after users reported
successful tests. A saved opt-out remains available.

Previously, startup fetched T0 for probing even when another head would print first.
Using the first printing head can avoid extra swaps and heating. Startup records the
physical probing head, and printing offsets are calculated relative to it. A
saved-default mesh still uses T0. End/cancel reset the idle reference to T0.

The original proposal identified power-loss recovery as incompatible because the
vendor rehomed with T0. The later recovery implementation saves and restores the
print's probing head and separate mesh. September 14 physical recovery tests covered
T0 and T2 references; see [the recovery guide](print-mesh-recovery.md).

Early estimates of time savings and implementation confidence were proposal
assumptions, not measured results. Actual savings depend on the attached head and
which head prints first. The rollout used a toggle, a T0 control print, a print
starting with T2, and instrumented startup checks.

## Left-edge purge: implemented

Implemented August 19, 2026. Startup purges on the plate at X0, Y100–150. X-2 was
observed to be off the lip, so the final route keeps the nozzle on the plate for
priming. It avoids the front panel and leaves the main printing area clear.

The stock Y-1 route could strike the front panel. An earlier Y2 workaround provided
clearance but still occupied the front edge. The original proposal instead suggested
an off-bed purge at X-13 Y80 followed by wiping. That variant was not needed.

The proposed off-bed variant would have required checks for purge waste handling,
adequate priming, and strings across the bed. Those checks explain the tradeoff;
they do not describe the installed on-plate purge.

## Auxiliary-fan cooling: removed

The cooling detour and temporary fan boost were implemented and functionally tested.
They were removed September 14, 2026 after repeated cooldown measurements found no
improvement with the part fan already at 100%. The independent cooldown-wait fixes
remain. See [the measurements](cooling-assist.md).

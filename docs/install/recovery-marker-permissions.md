# Recovery marker permission upgrades

The screen normally runs as root and Klipper runs as the printer user. Older
coordinate-marker writers could publish `plr_dataA.ini.wmp-coordinates` or
`plr_dataB.ini.wmp-coordinates` with mkstemp's 0600 permissions. The current writer
already publishes markers with 0644 permissions, but updating its library does
not repair an existing marker until that marker is replaced.

Preload installation now stops the screen, upgrades existing marker read access,
and only then performs its normal backend and screen restart. The upgrade walks
the configured printer home's `TM_T1/bin` through no-follow directory descriptors
and opens only the two exact coordinate-marker names. Both files are validated
before changes: regular, no hard links, at most 256 bytes. Missing markers are not
created. Symlink/special/oversized/replaced inputs fail rather than being followed.

The upgrade adds read bits matching the current writer policy. It preserves
contents, inode, owner/group and existing write permissions. It never changes
`TM_T1/bin` ownership or directory permissions. This idempotent access correction
is retained if later installation steps roll back; recovery admission still
validates the original marker contents and matching checkpoint/file evidence.

A directory traversal/write problem is a separate condition. This repair does
not establish that the community report's additional directory chown/chmod was
necessary: the original modes and full error trace were not available. Do not
apply recursive ownership changes or directory write grants as a generic repair.
If installation still reports a permission error, retain the exact path, process
user and existing ownership/modes so that condition can be diagnosed separately.

# Large-file startup bookkeeping

The observed 60,770,761-byte job took about 220 seconds from Moonraker job start
to the first heater targets. During that interval the Klipper main thread used
one full CPU core, object queries stalled, and a second handle advanced through
the job file. No Python stack was captured during that interval, so these
observations do not establish an exact breakdown of that particular delay.

A local profile of 200,000 representative G1 lines attributed 2.145 of 2.941
instrumented seconds (about 73%) to `classified_command` in the tool-membership
scanner. This scanner validates the supported dialect before authorizing unused
head recipe edits; it must not simply ignore unknown commands.

The optimized scanner validates short, ordered ASCII G0/G1 lines with a compiled
regular expression. It avoids building coordinate dictionaries and parsing
floats when it only needs membership. The short-line bound guarantees finite
numbers. Other parameter orders, longer lines, tool selections, startup/end
commands and unusual syntax retain the full parser. Commands before startup or
after PRINT_END cannot take the shortcut. Whole-file hashing, size/line bounds,
macro proof and file/context revalidation remain in place.

On this host, feeding the same 200,000 move lines took 1.239 seconds with the
shortcut disabled and 0.240 seconds with it enabled (~5.2x). These are synthetic
host results, not a printer-wide speedup claim. Differential tests compare
ordinary and malformed lines against the full dialect parser.

Recovery staging now yields after 64 KiB, or when a 20 ms deadline is observed
at a 64-line boundary, rather than only after 1 MiB. Each line chunk remains
bounded. This removes per-line `tell()` calls and prevents small but expensive
lines from holding the reactor for a full megabyte. Existing revalidation after
yielding is retained. Real-printer startup time and responsiveness remain to be
verified after the current print, without weakening recovery evidence checks.

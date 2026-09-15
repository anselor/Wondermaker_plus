#!/usr/bin/env python3
"""Review a three-way config migration without modifying stock or live.

    python tools/update_config_base.py config/stock_1.1.04 config/stock config/live
    python tools/update_config_base.py OLD NEW LIVE --output /tmp/wmp-candidate

Adapted from Florian Schroen's contributed migration helper. Stock remains
a real directory; older baselines live in stock_<version>. No baseline is
automatically promoted. --output creates a NEW review directory, never writes
to live, and includes unresolved conflict markers for manual review.
Exit 0 means no textual conflicts or outstanding file/marker decisions;
exit 1 means review is required; exit 2 means failure (no candidate written).
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'utils'))
from config_sync import body_of, excluded

MARKER = re.compile(r'wondermaker\+ begin:\s*([^\s(]+)')


def read_files(directory):
    result = {}
    for path in sorted(directory.iterdir()):
        if excluded(path.name):
            continue
        if path.is_symlink():
            raise ValueError(f'symlink config is not supported: {path}')
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.name == 'printer.cfg':
            data = body_of(data)
        if b'\0' in data:
            raise ValueError(f'binary config is not supported: {path}')
        result[path.name] = data.decode('utf-8')
    return result


def merge_text(name, current, old, new):
    with tempfile.TemporaryDirectory(prefix='wmp-merge-') as td:
        paths = [Path(td) / n for n in ('live', 'old', 'new')]
        for p, text in zip(paths, (current, old, new)):
            p.write_text(text)
        r = subprocess.run(['git', 'merge-file', '-p', '--diff3',
                            '-L', f'live/{name}', '-L', f'old/{name}',
                            '-L', f'new/{name}', *map(str, paths)],
                           capture_output=True, text=True)
    # Git caps conflict counts at 127; errors are outside that interval.
    if not 0 <= r.returncode <= 127:
        raise RuntimeError(f'{name}: git merge-file failed ({r.returncode}): {r.stderr.strip()}')
    return r.stdout, r.returncode


def plan(old_dir, new_dir, live_dir):
    old, new, live = map(read_files, (old_dir, new_dir, live_dir))
    candidate, decisions = {}, []
    for name in sorted(old.keys() | new.keys() | live.keys()):
        if name not in live:
            if name in new and name not in old:
                candidate[name] = new[name]
                decisions.append(f'ADD {name}: new vendor file; review includes/dependencies')
            elif name in new:
                decisions.append(f'SKIP {name}: absent from live; confirm intentional omission')
            continue
        if name not in old:
            candidate[name] = live[name]
            if name in new and new[name] != live[name]:
                decisions.append(f'COLLISION {name}: new vendor file overlaps a local file; kept local')
            continue
        if name not in new:
            candidate[name] = live[name]
            decisions.append(f'REMOVED {name}: vendor removed it; kept local pending review')
            continue
        merged, conflicts = merge_text(name, live[name], old[name], new[name])
        candidate[name] = merged
        if conflicts:
            ids = sorted(set(MARKER.findall(live[name])))
            decisions.append(f'CONFLICT {name}: {conflicts}; local change IDs: {", ".join(ids) or "unmarked"}')
        else:
            before, after = MARKER.findall(live[name]), MARKER.findall(merged)
            dropped = sorted({x for x in before if after.count(x) < before.count(x)})
            if dropped:
                decisions.append(f'WARNING {name}: marked changes lost: {", ".join(dropped)}')
    return candidate, decisions


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old_stock', type=Path)
    ap.add_argument('new_stock', type=Path)
    ap.add_argument('live', type=Path)
    ap.add_argument('--output', type=Path, help='new directory for review candidates; never config/live')
    args = ap.parse_args(argv)
    try:
        inputs = [p.resolve() for p in (args.old_stock, args.new_stock, args.live)]
        if not all(p.is_dir() for p in inputs):
            raise ValueError('all three input paths must be directories')
        if args.output:
            output = args.output.resolve()
            if args.output.exists() or args.output.is_symlink():
                raise ValueError(f'output must not exist: {args.output}')
            if any(output == p or p in output.parents for p in inputs):
                raise ValueError('output must be outside the input directories')
            if not output.parent.is_dir():
                raise ValueError('output parent directory must exist')
        candidate, decisions = plan(*inputs)
        if args.output:
            # Finish all merges first. Stage next to output, then publish together.
            with tempfile.TemporaryDirectory(prefix='.wmp-candidate-', dir=output.parent) as td:
                staged = Path(td) / 'candidate'
                staged.mkdir()
                for name, text in candidate.items():
                    (staged / name).write_text(text)
                staged.rename(output)
            print(f'Wrote review candidate: {output}')
        for line in decisions:
            print(line)
        print(f'{len(candidate)} candidate files; {len(decisions)} outstanding review items. Stock and live unchanged.')
        return 1 if decisions else 0
    except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

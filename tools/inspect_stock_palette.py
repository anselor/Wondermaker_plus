#!/usr/bin/env python3
"""Verify the native solid-colour table against local stock LVGL image assets.

Reads assets only. Does not upload, modify images, or connect to the printer.
The stock 32-bit image payload is BGRA, following its four-byte LVGL header.
Textured swatches have no single RGB identity and are reported without one.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def inspect(assets):
    rows = []
    for index in range(21):
        path = assets / f'screen_filament_edit_color_re_{index}.bin'
        raw = path.read_bytes()
        header = int.from_bytes(raw[:4], 'little')
        width, height = (header >> 10) & 2047, (header >> 21) & 2047
        if header & 31 != 5 or (width, height) != (83, 83) or len(raw) != 4 + width * height * 4:
            raise ValueError(f'Unexpected image format: {path.name}')
        pixels = Counter(raw[n:n+4] for n in range(4, len(raw), 4) if raw[n+3] == 255)
        pixel, count = pixels.most_common(1)[0]
        if index < 16 and count / sum(pixels.values()) < .9:
            raise ValueError(f'Expected a solid swatch: {path.name}')
        rows.append(dict(index=index, sha256=hashlib.sha256(raw).hexdigest(),
                         dominant_bgra=pixel.hex(), dominant_count=count,
                         opaque_pixels=sum(pixels.values()),
                         rgb=('#' + pixel[2::-1].hex()) if index < 16 else None))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assets', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = inspect(args.assets)
    header = Path(__file__).resolve().parents[1] / 'client-preload/unified-ui/native/stock_palette.hpp'
    compiled = re.findall(r'"(#[0-9a-f]{6})"', header.read_text())
    if compiled != [row['rgb'] for row in rows[:16]]:
        raise SystemExit('Native palette does not match stock assets')
    args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print('Verified 16 solid swatches; five textured swatches need richer profile support.')

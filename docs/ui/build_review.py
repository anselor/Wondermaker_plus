#!/usr/bin/env python3
"""Generate UI-review HTML and inventory tables from the shared planning data."""
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / 'plan-data.json').read_text())
DOCUMENT = HERE.parent / 'ui-plan.md'


def table(headers, rows):
    def cell(value):
        return str(value).replace('|', '&#124;').replace('\n', '<br>')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(cell(c) for c in row) + ' |' for row in rows])


for section in ('screens', 'features', 'new_screens', 'phases', 'requirements'):
    ids = [row['id'] for row in DATA[section]]
    assert len(ids) == len(set(ids)), 'Duplicate identifiers in ' + section
for screen in DATA['screens']:
    assert screen['decision'] in ('keep', 'overlay', 'override', 'replace')
    assert screen['phase'] in {p['id'] for p in DATA['phases']}
for image in DATA['history']:
    path = (HERE / image['file']).resolve()
    path.relative_to(HERE)
    assert path.is_file(), path

blocks = {
    'requirements': table(['ID', 'Requirement', 'User behavior', 'Backend / API status'],
                          [(r['id'], r['name'], r['behavior'], r['backend']) for r in DATA['requirements']]),
    'stock': table(['ID', 'Stock surface', 'Implemented stock features / limits'],
                   [(s['id'], s['name'], s['stock']) for s in DATA['screens']]),
    'features': table(['ID', 'Feature', 'Status', 'Current scope'],
                      [(f['id'], f['name'], f['status'], f['current']) for f in DATA['features']]),
    'dispositions': table(['ID', 'Surface', 'Primary disposition', 'Target change'],
                          [(s['id'], s['name'], s['decision'], s['target']) for s in DATA['screens']]),
    'newviews': table(['ID', 'New owned view', 'Content', 'Boundary'],
                      [(s['id'], s['name'], s['content'], s['boundary']) for s in DATA['new_screens']]),
    'phases': table(['Phase', 'Delivery', 'Exit gate'],
                    [(p['id'], p['name'], p['exit']) for p in DATA['phases']]),
}
text = DOCUMENT.read_text()
for name, content in blocks.items():
    pattern = r'(?s)(<!-- BEGIN ' + name + r' -->).*?(<!-- END ' + name + r' -->)'
    text, count = re.subn(pattern, lambda m: m[1] + '\n\n' + content + '\n\n' + m[2], text)
    assert count == 1, 'Missing or duplicate generated section: ' + name
DOCUMENT.write_text(text)
encoded = json.dumps(DATA, ensure_ascii=True).replace('<', '\\u003c')
html = (HERE / 'review-template.html').read_text()
assert html.count('__PLAN_DATA__') == 1
(HERE / 'review.html').write_text(html.replace('__PLAN_DATA__', encoded))
print('Generated review.html and six tables in ui-plan.md')

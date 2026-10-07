"""petite_parser.js (the submit page preview) agrees with the Python pipeline.

1. reconstruct() equals parse_petite_log.parse() without a livelog, for every
   saved cup not in tests/fixtures/excluded_cups.json.
2. parseCup() with the cup's mappers equals the published xlsx block for every
   cup in cup_meta.json that has structured map/mapper data or a known mapper list.
3. Synthetic rule tests (tests/js/test_rules.mjs).
"""
import json
import shutil
import subprocess

import openpyxl
import pytest

from conftest import REPO
from test_parser import CUPS, EXCLUDED, LOGS, saved

NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='node not installed')

# Mappers per published cup, as new_petite.py would be given them.
PUBLISHED = {
    51: ['[CSC] variableferret', '[Fenn]Lilly Fenn'],
    52: ['justMaki', 'agix'],
    53: ['[CSC] Shadynook', '[CSC] redal'],
}


def xlsx_rows(cup):
    meta = json.loads((REPO / 'cup_meta.json').read_text(encoding='utf-8'))[f'Petite Cup {cup}']
    ws = openpyxl.load_workbook(REPO / meta['xlsx']).active
    col = 1 + 6 * ((cup - 1) % 5)
    rows = []
    for r in range(6, ws.max_row + 1):
        vals = [ws.cell(r, c).value for c in range(col, col + 4)]
        if vals[0] is None:
            break
        rows.append(vals)
    return rows


def test_js_matches_python(tmp_path):
    cases = {
        'reconstructed': [{'cup': n, 'log': str(LOGS / f'petite_{n}.log'), 'expected': saved(n)}
                          for n in CUPS if str(n) not in EXCLUDED],
        'published': [{'cup': n, 'log': str(LOGS / f'petite_{n}.log'), 'mappers': m, 'exclude': [],
                       'rows': xlsx_rows(n)} for n, m in PUBLISHED.items()],
    }
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding='utf-8')
    r = subprocess.run([NODE, str(REPO / 'tests' / 'js' / 'run_fixtures.mjs'), str(path)],
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stdout + r.stderr


def test_js_rules():
    r = subprocess.run([NODE, '--test', str(REPO / 'tests' / 'js' / 'test_rules.mjs')],
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stdout + r.stderr

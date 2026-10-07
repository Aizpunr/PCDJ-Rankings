// Golden check of petite_parser.js against what the Python pipeline published.
// Usage: node tests/js/run_fixtures.mjs <cases.json>
// cases.json (written by tests/test_parser_js.py):
//   {"reconstructed": [{"cup", "log", "expected"}],          parse() output, no livelog
//    "published":     [{"cup", "log", "mappers", "exclude", "rows"}]}   xlsx blocks
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const P = require('../../petite_parser.js');

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const lines = (path) => P.pySplitlines(P.decodeBytes(readFileSync(path)));
let failed = 0;

for (const c of cases.reconstructed) {
  try {
    assert.deepStrictEqual(P.reconstruct(lines(c.log)), c.expected);
    console.log(`ok   reconstruct cup ${c.cup}`);
  } catch (e) {
    failed++;
    console.log(`FAIL reconstruct cup ${c.cup}\n${e.message.slice(0, 2000)}`);
  }
}

for (const c of cases.published) {
  try {
    const got = P.parseCup(lines(c.log), c.exclude, c.mappers);
    const rows = got.rows.map((r) => [r.pos, r.name, r.time === null ? 'DNF' : Math.round(r.time * 1e5) / 1e5,
      r.note === 'winner' ? null : r.round]);
    assert.deepStrictEqual(rows, c.rows);
    assert.ok(got.winner, 'single winner');
    console.log(`ok   published cup ${c.cup} (${rows.length} rows, excluded ${JSON.stringify(got.excluded)})`);
  } catch (e) {
    failed++;
    console.log(`FAIL published cup ${c.cup}\n${e.message.slice(0, 2000)}`);
  }
}

process.exit(failed ? 1 : 0);

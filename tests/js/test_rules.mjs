// Rule tests for petite_parser.js on synthetic logs. Run: node --test tests/js/test_rules.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../petite_parser.js');

const H = '[Info   :COTDTracker] Doing eliminations with leaderboard:';
const T = (n, t) => `[Info   :COTDTracker] Player ${n}: Time: ${t}`;
const D = (n) => `[Info   :COTDTracker] Eliminating DNF: ${n}`;
const E = (n) => `[Info   :COTDTracker] Eliminating on time: ${n}`;

// Warmup block (no eliminations) is dropped; R1 eliminates C on time and D, E as DNF;
// R2 eliminates B; A wins.
const LOG = [
  H, T('A', '40,0'), T('B', '41.0'), T('C', '42.0'), T('D', 'DNF'), T('E', 'DNF'), T('W', '39.0'),
  H, T('A', '40.0'), T('B', '41.0'), T('C', '42.0'), T('D', 'DNF'), T('E', 'DNF'),
  E('C'), D('D'), D('E'),
  H, T('A', '39.5'), T('B', '41.5'), E('B'),
].join('\r\n');

test('positions: timed by time, DNFs tie below them, winner last block time', () => {
  const r = P.reconstruct(P.pySplitlines(LOG));
  assert.deepStrictEqual(r.map((x) => [x.pos, x.name, x.time, x.round, x.note]), [
    [1, 'A', 39.5, null, 'winner'],
    [2, 'B', 41.5, 2, 'cotd'],
    [3, 'C', 42.0, 1, 'cotd'],
    [4, 'D', null, 1, 'dnf'],
    [4, 'E', null, 1, 'dnf'],
  ]);
});

test('a warmup-only player is not in the results', () => {
  const r = P.reconstruct(P.pySplitlines(LOG));
  assert.ok(!r.some((x) => x.name === 'W'));
  assert.ok(P.namedPlayers(P.pySplitlines(LOG)).includes('W'));
});

test('exclusion re-ranks with ties kept', () => {
  const got = P.parseCup(P.pySplitlines(LOG), ['C'], []);
  assert.deepStrictEqual(got.rows.map((x) => [x.pos, x.name]), [[1, 'A'], [2, 'B'], [3, 'D'], [3, 'E']]);
});

test('a mapper is excluded only when in the lobby, ignoring tags and case', () => {
  const got = P.parseCup(P.pySplitlines(LOG), [], ['[XYZ] d', 'nobody']);
  assert.deepStrictEqual(got.excluded, ['D']);
  assert.deepStrictEqual(got.mappersInLobby, ['[XYZ] d']);
  assert.equal(got.players, 4);
});

test('exact time tie is broken by name, as parse_petite_log.py does', () => {
  const log = [H, T('Z', '41.0'), T('Y', '41.0'), T('A', '40.0'), E('Z'), E('Y')].join('\n');
  const r = P.reconstruct(P.pySplitlines(log));
  assert.deepStrictEqual(r.map((x) => [x.pos, x.name]), [[1, 'A'], [2, 'Y'], [3, 'Z']]);
});

test('two players never eliminated is ambiguous', () => {
  const log = [H, T('A', '40.0'), T('B', '41.0'), T('C', '42.0'), E('C')].join('\n');
  assert.throws(() => P.reconstruct(P.pySplitlines(log)), (e) => {
    assert.deepStrictEqual(e.ambiguous, ['A', 'B']);
    return e instanceof P.ParseError;
  });
});

test('no elimination rounds is a ParseError', () => {
  assert.throws(() => P.reconstruct(P.pySplitlines([H, T('A', '40.0')].join('\n'))), P.ParseError);
});

test('splitlines matches Python str.splitlines', () => {
  assert.deepStrictEqual(P.pySplitlines('a\r\nb\rc\nd\x0be\x0cf\x1cg\x85h\u2028i\n'),
    ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']);
  assert.deepStrictEqual(P.pySplitlines(''), []);
});

test('comma decimal accepted; a player whose only time is unparseable never joins the roster', () => {
  // Same as parse_petite_log.py: B has no Player entry, so its elimination is ignored.
  const log = [H, T('A', '40,5'), T('B', 'garbage'), T('C', '42.0'), E('C'), D('B')].join('\n');
  const r = P.reconstruct(P.pySplitlines(log));
  assert.deepStrictEqual(r.map((x) => [x.pos, x.name, x.time]), [[1, 'A', 40.5], [2, 'C', 42.0]]);
});

test('stripTag mirrors petite_ranking.strip_tag', () => {
  assert.equal(P.stripTag('[CSC] redal'), 'redal');
  assert.equal(P.stripTag('[KBW]Kernkob'), 'Kernkob');
  assert.equal(P.stripTag('A [x] B'), 'A B');
});

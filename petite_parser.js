/* petite_parser.js: JavaScript port of the no-livelog path of parse_petite_log.py,
 * plus the exclusion re-rank of new_petite.py.
 *
 * Runs in the browser (window.PetiteParser, used by submit.html to preview a log
 * before upload) and under Node (require, used by tests/js/). No build step.
 *
 * parse_petite_log.py is the source of truth: parseCup() must equal
 * parse(log_path) (no livelog) for every saved cup, checked by
 * tests/js/run_fixtures.mjs, which pytest runs via tests/test_parser_js.py.
 * The pipeline can still differ from this preview when a livelog overrides a DNF.
 *
 * Python semantics kept (helpers copied from zeepkist cotd elo/cotd_parser.js):
 *   str.splitlines()  splits on \n \r \v \f \x1c-\x1e \x85 \u2028 \u2029 -> pySplitlines
 *   str.strip()       Python whitespace class                         -> pyStrip
 *   float()           raises on garbage                               -> pyFloat
 *   sorted(str)       code-point order                                -> cmpCodePoints
 *   dict/set          any string key                                  -> Map/Set
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PetiteParser = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var BLOCK_HEADER = 'Doing eliminations with leaderboard';
  var RE_PLAYER_TIME = /Player ([^\n]+?): Time: ([^\n]+)/;
  var RE_ELIM_DNF = /Eliminating DNF: ([^\n]+)/;
  var RE_ELIM_TIME = /Eliminating on time: ([^\n]+)/;

  function ParseError(message) {
    var e = new Error(message);
    Object.setPrototypeOf(e, ParseError.prototype);
    return e;
  }
  ParseError.prototype = Object.create(Error.prototype);
  ParseError.prototype.constructor = ParseError;
  ParseError.prototype.name = 'ParseError';

  // ── Python primitives ──────────────────────────────────────────────

  var PY_WS = '\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  var RE_LSTRIP = new RegExp('^[' + PY_WS + ']+');
  var RE_RSTRIP = new RegExp('[' + PY_WS + ']+$');

  function pyStrip(s) {
    return String(s).replace(RE_LSTRIP, '').replace(RE_RSTRIP, '');
  }

  var RE_PY_FLOAT = /^[+-]?(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;
  var RE_PY_SPECIAL = /^([+-]?)(inf|infinity|nan)$/i;

  // Python float(str), or null where Python raises ValueError.
  function pyFloat(s) {
    var t = pyStrip(s);
    var sp = RE_PY_SPECIAL.exec(t);
    if (sp) {
      if (sp[2].toLowerCase() === 'nan') return NaN;
      return sp[1] === '-' ? -Infinity : Infinity;
    }
    if (!RE_PY_FLOAT.test(t)) return null;
    return Number(t.replace(/_/g, ''));
  }

  function cmpCodePoints(a, b) {
    var i = 0, j = 0;
    while (i < a.length && j < b.length) {
      var ca = a.codePointAt(i), cb = b.codePointAt(j);
      if (ca !== cb) return ca < cb ? -1 : 1;
      i += ca > 0xffff ? 2 : 1;
      j += cb > 0xffff ? 2 : 1;
    }
    if (i < a.length) return 1;
    if (j < b.length) return -1;
    return 0;
  }

  // Python str.splitlines() (Path.read_text() first folds \r\n and \r into \n,
  // which splitting on all of them already covers).
  function pySplitlines(text) {
    if (text === '') return [];
    var parts = String(text).split(/\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/);
    if (parts.length && parts[parts.length - 1] === '') parts.pop();
    return parts;
  }

  // open(encoding='utf-8', errors='replace'): BOM kept, invalid bytes -> U+FFFD.
  function decodeBytes(bytes) {
    return new TextDecoder('utf-8', { ignoreBOM: true, fatal: false }).decode(bytes);
  }

  // petite_ranking.strip_tag: re.sub(r'\[.*?\]\s*', '', name).strip()
  var RE_TAG = new RegExp('\\[[^\\n]*?\\][' + PY_WS + ']*', 'g');
  function stripTag(name) {
    return pyStrip(String(name).replace(RE_TAG, ''));
  }

  // new_petite.same_player without the alias table: tags and case don't matter.
  // The pipeline also folds known aliases, so it may match a few more names.
  function samePlayer(a, b) {
    return stripTag(a).toLowerCase() === stripTag(b).toLowerCase();
  }

  // ── Port of parse_petite_log.parse_cotdtracker ─────────────────────

  function parseBlocks(lines) {
    var blocks = [];
    var cur = null;
    for (var k = 0; k < lines.length; k++) {
      var ln = lines[k];
      if (ln.indexOf(BLOCK_HEADER) !== -1) {
        if (cur) blocks.push(cur);
        cur = { players: new Map(), elimDnf: [], elimTime: [] };
      } else if (cur !== null) {
        var m = RE_PLAYER_TIME.exec(ln);
        if (m) {
          var name = pyStrip(m[1]);
          var tstr = pyStrip(m[2]);
          if (tstr === 'DNF') {
            cur.players.set(name, null);
          } else {
            var t = pyFloat(tstr.split(',').join('.'));
            if (t !== null) cur.players.set(name, t);
          }
        }
        var m2 = RE_ELIM_DNF.exec(ln);
        if (m2) cur.elimDnf.push(pyStrip(m2[1]));
        var m3 = RE_ELIM_TIME.exec(ln);
        if (m3) cur.elimTime.push(pyStrip(m3[1]));
      }
    }
    if (cur) blocks.push(cur);
    return blocks;
  }

  // Every name with a Player line in any block, code-point sorted (for pickers).
  function namedPlayers(lines) {
    var named = new Set();
    parseBlocks(lines).forEach(function (b) { b.players.forEach(function (_, n) { named.add(n); }); });
    return Array.from(named).sort(cmpCodePoints);
  }

  function countBlocks(lines) {
    var n = 0;
    for (var k = 0; k < lines.length; k++) if (lines[k].indexOf(BLOCK_HEADER) !== -1) n++;
    return n;
  }

  // ── Port of parse_petite_log.reconstruct (no livelog) ──────────────

  // Returns [{pos, name, time, round, note}] exactly as parse() does.
  // Throws ParseError with .ambiguous = [names] if several players are left standing.
  function reconstruct(lines) {
    var rounds = parseBlocks(lines).filter(function (b) { return b.elimDnf.length || b.elimTime.length; });
    if (!rounds.length) throw ParseError('no elimination rounds in this log');

    var remaining = new Set();
    rounds.forEach(function (r) { r.players.forEach(function (_, n) { remaining.add(n); }); });

    var results = [];
    rounds.forEach(function (cr, idx) {
      var roundNum = idx + 1;
      var allElim = new Set();
      cr.elimDnf.concat(cr.elimTime).forEach(function (n) { if (remaining.has(n)) allElim.add(n); });
      var timed = [], untimed = [];
      allElim.forEach(function (n) {
        var t = cr.players.has(n) ? cr.players.get(n) : null;
        if (t !== null) timed.push([n, t]); else untimed.push(n);
      });
      timed.sort(function (a, b) { return a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : cmpCodePoints(a[0], b[0]); });
      allElim.forEach(function (n) { remaining.delete(n); });
      var basePos = remaining.size;
      timed.forEach(function (e, i) {
        results.push({ pos: basePos + i + 1, name: e[0], time: e[1], round: roundNum, note: 'cotd' });
      });
      var dnfPos = basePos + timed.length + 1;
      untimed.forEach(function (n) {
        results.push({ pos: dnfPos, name: n, time: null, round: roundNum, note: 'dnf' });
      });
    });

    if (remaining.size > 1) {
      var names = Array.from(remaining).sort(cmpCodePoints);
      var err = ParseError(names.length + ' players were never eliminated: ' + names.join(', '));
      err.ambiguous = names;
      throw err;
    }
    if (remaining.size === 1) {
      var winner = Array.from(remaining)[0];
      var last = rounds[rounds.length - 1].players;
      results.push({ pos: 1, name: winner, time: last.has(winner) ? last.get(winner) : null, round: null, note: 'winner' });
    }

    results.sort(function (a, b) {
      if (a.pos !== b.pos) return a.pos - b.pos;
      var ta = a.time !== null ? 0 : 1, tb = b.time !== null ? 0 : 1;
      if (ta !== tb) return ta - tb;
      return cmpCodePoints(a.name, b.name);
    });
    return results;
  }

  // ── new_petite.py: exclusions + re-rank with ties kept (1, 2, 2, 4) ─

  // excludeNames: raw names to drop (exact, as picked from the log).
  // mappers: names as typed; dropped only if one matches a lobby name.
  function parseCup(lines, excludeNames, mappers) {
    var results = reconstruct(lines);
    var names = results.map(function (r) { return r.name; });
    var excluded = [];
    var mappersInLobby = [];
    (mappers || []).forEach(function (m) {
      if (!m) return;
      var hits = names.filter(function (n) { return samePlayer(n, m); });
      if (hits.length) mappersInLobby.push(m);
      hits.forEach(function (h) { if (excluded.indexOf(h) === -1) excluded.push(h); });
    });
    (excludeNames || []).forEach(function (x) {
      names.filter(function (n) { return samePlayer(n, x); })
        .forEach(function (h) { if (excluded.indexOf(h) === -1) excluded.push(h); });
    });

    var rows = [], prevPos = null, newPos = 0, seen = 0;
    results.forEach(function (e) {
      if (excluded.indexOf(e.name) !== -1) return;
      seen++;
      if (e.pos !== prevPos) { newPos = seen; prevPos = e.pos; }
      rows.push({ pos: newPos, name: e.name, time: e.time, round: e.round, note: e.note });
    });
    var nRounds = 0;
    rows.forEach(function (r) { if (r.round && r.round > nRounds) nRounds = r.round; });
    var winners = rows.filter(function (r) { return r.pos === 1; });
    return {
      rows: rows,
      results: results,
      excluded: excluded,
      mappersInLobby: mappersInLobby,
      winner: winners.length === 1 ? winners[0] : null,
      players: rows.length,
      rounds: nRounds,
    };
  }

  function parseText(text, excludeNames, mappers) {
    return parseCup(pySplitlines(text), excludeNames, mappers);
  }

  return {
    BLOCK_HEADER: BLOCK_HEADER,
    ParseError: ParseError,
    decodeBytes: decodeBytes,
    pySplitlines: pySplitlines,
    pyStrip: pyStrip,
    pyFloat: pyFloat,
    cmpCodePoints: cmpCodePoints,
    stripTag: stripTag,
    samePlayer: samePlayer,
    parseBlocks: parseBlocks,
    namedPlayers: namedPlayers,
    countBlocks: countBlocks,
    reconstruct: reconstruct,
    parseCup: parseCup,
    parseText: parseText,
  };
});

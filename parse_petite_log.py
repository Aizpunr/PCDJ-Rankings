"""Parse a petite cup using BOTH logs and flag discrepancies.

Usage: python parse_petite_log.py <cup_number>

Reads:
  cup logs/petite_<N>.log                  — COTDTracker (cup structure + baseline times)
  cup logs/petite_<N>_liveleaderboard.log  — LiveLeaderboardLogger (override for mid-round leavers)

Approach:
  COTDTracker is the scaffold for the cup structure (round count, who was eliminated when).
  LiveLeaderboardLogger is the override for DNFs that should actually have a time — e.g.
  someone who set a valid time then left the lobby before the round ended.

  For each DNF in COTDTracker, we scan live snapshots in the time window between the
  PREVIOUS elim decision and THIS elim decision. If we find a valid time for that player's
  steamId, we promote the DNF to a timed result with that time.

Rule for eliminated players (aizpun 2026-04-22):
  1. Eliminated = COTDTracker's decisions. Mid-round leavers still register via COTDTracker
     as DNF or on-time depending on whether the server got their time before they left.
  2. Within a round's eliminated group, rank by best valid time (fastest = best position);
     players without a valid time anywhere tie at the bottom.
  3. Live log overrides COTDTracker DNF when a valid time exists for that player in the
     round's time window.

Outputs:
  cup logs/petite_<N>_reconstructed.json   — corrected standings
  Prints flagged DNF->time overrides and any other oddities.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LIVE_ENTRY_RE = re.compile(r'(\d+):(\d{15,20}):(\d+,\d+)')
LIVE_LINE_RE = re.compile(
    r'^(\S+) \[LiveLeaderboardLogger\] PROBE_B\|SNAPSHOT\|(\d+)\|(\d+)\|(.+)$'
)


def parse_cotd_ts(line):
    """Extract the BepInEx log timestamp from a COTDTracker line.
    Format like '[Info   :COTDTracker] ...' — BepInEx prepends a time HH:MM:SS marker when --log-timestamps is on.
    In the observed cup 43 log these are not always present, so we fall back to line-number ordering."""
    m = re.search(r'^\[(\d{2}:\d{2}:\d{2})', line)
    return m.group(1) if m else None


def parse_cotdtracker(path):
    """Return (rounds, line_positions) where rounds[i] = {
        'block_players': {name: time_float or None},
        'elim_dnf': [name, ...],
        'elim_time': [name, ...],
        'block_start_line': int,   -- line index of 'Doing eliminations with leaderboard'
        'elim_decision_line': int, -- line index of 'Eliminating N players:'
    }.
    Initial non-elim blocks are dropped."""
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    blocks = []
    cur = None
    for ix, ln in enumerate(lines):
        if 'Doing eliminations with leaderboard' in ln:
            if cur:
                blocks.append(cur)
            cur = {
                'block_players': {},
                'elim_dnf': [],
                'elim_time': [],
                'block_start_line': ix,
                'elim_decision_line': None,
            }
        elif cur is not None:
            m = re.search(r'Player (.+?): Time: (.+)', ln)
            if m:
                name = m.group(1).strip()
                tstr = m.group(2).strip()
                if tstr == 'DNF':
                    cur['block_players'][name] = None
                else:
                    try:
                        cur['block_players'][name] = float(tstr.replace(',', '.'))
                    except ValueError:
                        pass
            m2 = re.search(r'Eliminating DNF: (.+)', ln)
            if m2:
                cur['elim_dnf'].append(m2.group(1).strip())
            m3 = re.search(r'Eliminating on time: (.+)', ln)
            if m3:
                cur['elim_time'].append(m3.group(1).strip())
            if re.match(r'.*Eliminating \d+ players:', ln) and cur['elim_decision_line'] is None:
                cur['elim_decision_line'] = ix
    if cur:
        blocks.append(cur)
    return [b for b in blocks if b['elim_dnf'] or b['elim_time']], lines


def parse_livelog(path):
    """Return list of (ts_str, plugin_round, count, [(pos, sid, time_float), ...])."""
    snaps = []
    for ln in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = LIVE_LINE_RE.match(ln)
        if not m:
            continue
        ts, rn, cnt, data = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        entries = [
            (int(em.group(1)), em.group(2), float(em.group(3).replace(',', '.')))
            for em in LIVE_ENTRY_RE.finditer(data)
        ]
        snaps.append((ts, rn, cnt, entries))
    return snaps


def build_sid_name_map(cotd_rounds, snaps):
    """Cross-reference by time-value matches. Returns ({sid: name}, {name: sid}, conflicts)."""
    name_times = defaultdict(set)
    for r in cotd_rounds:
        for name, t in r['block_players'].items():
            if t is not None:
                name_times[name].add(round(t, 5))
    sid_times = defaultdict(set)
    for _, _, _, entries in snaps:
        for pos, sid, t in entries:
            sid_times[sid].add(round(t, 5))
    sid_to_name = {}
    name_to_sid = {}
    conflicts = []
    for name, times in name_times.items():
        candidates = [(sid, len(times & sts)) for sid, sts in sid_times.items() if times & sts]
        candidates.sort(key=lambda x: -x[1])
        if not candidates:
            continue
        if len(candidates) == 1 or candidates[0][1] > candidates[1][1]:
            sid_to_name[candidates[0][0]] = name
            name_to_sid[name] = candidates[0][0]
        else:
            conflicts.append((name, candidates[:3]))
    return sid_to_name, name_to_sid, conflicts


def find_last_live_time_between(snaps, sid, start_idx, end_idx):
    """Find the LATEST time value for sid in snaps with list-index between start_idx and end_idx (exclusive)."""
    latest = None
    for i in range(start_idx, end_idx):
        if i < 0 or i >= len(snaps):
            continue
        for pos, s, t in snaps[i][3]:
            if s == sid:
                latest = t  # keep overwriting; snaps are in time order so we end on the latest
    return latest


def correlate_rounds_to_live_indices(cotd_rounds, snaps, cotd_all_lines):
    """For each COTD round, return the live-snap index range [start, end) that covers it.

    Strategy: use the COTDTracker log line index to determine relative ordering. For each
    cotd_round's elim_decision_line, find the live snap whose plugin_round's last appearance
    in our own log falls BEFORE the next round's decision. This is approximate — we really
    want timestamp ordering — but with COTDTracker log lacking reliable timestamps, and our
    log having timestamps, we use a heuristic: assume the two logs advance together in time
    and use COTDTracker line number as a proxy.

    A cleaner correlation: match by the NUMBER of plugin rounds seen between each cotd
    decision. COTDTracker eliminates once per cup round, and the plugin's round counter
    advances on RoundStarted (which fires at least once per cup round). Between two cotd
    decisions, there will be >=1 plugin-round ID transition.
    """
    # Group snap indices by plugin_round
    round_first_idx = {}
    round_last_idx = {}
    for i, (ts, rn, cnt, entries) in enumerate(snaps):
        if rn not in round_first_idx:
            round_first_idx[rn] = i
        round_last_idx[rn] = i
    sorted_plugin_rounds = sorted(round_first_idx.keys())

    # Assign one plugin round per COTD round, advancing monotonically.
    # Heuristic: use the LATEST plugin round seen before each COTD decision.
    # But we don't have timestamps on COTDTracker consistently. Alternative: just divide
    # plugin rounds proportionally among COTD rounds.
    #
    # Simplest correct approach for DNF recovery: for each COTD round, scan ALL live
    # snaps between (previous COTD round's plugin-round-last-idx) and (next COTD round's
    # plugin-round-first-idx). We can't compute these without some ordering — so instead,
    # we just scan the FULL live log for each DNF's sid and take their LATEST time that
    # is still within "the same map" as this COTD round's block (times match within ~3s).
    #
    # Return None here — caller will use the match-by-time-proximity approach below.
    return None


def correlate_plugin_rounds(cotd_rounds, snaps, name_to_sid):
    """Map each COTD round index to a plugin_round in the live log, advancing monotonically.
    Pick plugin_round whose union of snap-sids best matches the COTD block's sid set."""
    # Group snap indices by plugin round; also collect sid set per plugin round
    snaps_by_round = defaultdict(list)
    round_sids = defaultdict(set)
    for i, (ts, rn, cnt, entries) in enumerate(snaps):
        snaps_by_round[rn].append(i)
        for pos, sid, t in entries:
            round_sids[rn].add(sid)
    plugin_rounds_ordered = sorted(snaps_by_round.keys())

    mapping = []
    pointer = 0  # index into plugin_rounds_ordered
    for cr in cotd_rounds:
        cotd_sids = {name_to_sid[n] for n in cr['block_players'].keys() if n in name_to_sid}
        # Scan forward from pointer, find plugin_round with MAX sid-set similarity
        best_pr = None
        best_score = -1
        best_idx = pointer
        for j in range(pointer, len(plugin_rounds_ordered)):
            pr = plugin_rounds_ordered[j]
            overlap = len(cotd_sids & round_sids[pr])
            # Score favors overlap strongly, penalize extra sids slightly (shouldn't have players not in block)
            extra = len(round_sids[pr] - cotd_sids)
            score = overlap * 10 - extra
            if score > best_score:
                best_score = score
                best_pr = pr
                best_idx = j
        mapping.append(best_pr)
        pointer = best_idx + 1  # advance past best to ensure monotonic progress
    return mapping, snaps_by_round


def reconstruct(cotd_rounds, snaps, sid_to_name, name_to_sid):
    """Return list of {pos, name, time, round, note}. Apply live override for DNFs where valid time exists.

    DNF override: for each DNF in round N, look for a valid time in the CORRELATED plugin_round's
    snaps. Only observations from that window count — prevents picking up pre-cup / earlier-round times.
    """
    roster = set()
    for r in cotd_rounds:
        roster.update(r['block_players'].keys())

    plugin_mapping, snaps_by_round = correlate_plugin_rounds(cotd_rounds, snaps, name_to_sid)

    remaining = set(roster)
    results = []
    round_num = 0
    overrides = []
    for cr, plugin_rn in zip(cotd_rounds, plugin_mapping):
        round_num += 1
        block = cr['block_players']
        elim_dnf = set(cr['elim_dnf'])
        elim_time = set(cr['elim_time'])
        all_elim = (elim_dnf | elim_time) & remaining

        # Determine this round's time range (for filtering out map-carryover from previous round)
        valid_times = [t for t in block.values() if t is not None]
        if valid_times:
            t_min, t_max = min(valid_times), max(valid_times)
            # Tolerance: 0.5s below min (for potential faster override), 0s above max (no one slower than slowest)
            t_lo, t_hi = t_min - 0.5, t_max + 0.01
        else:
            t_lo, t_hi = None, None  # cannot filter; accept any

        # Collect live observations from the correlated plugin round only
        live_time_for_sid = {}
        if plugin_rn is not None:
            for i in snaps_by_round.get(plugin_rn, []):
                for pos, sid, t in snaps[i][3]:
                    live_time_for_sid[sid] = t

        time_for = {}
        note_for = {}
        for name in all_elim:
            t_cotd = block.get(name)
            override_time = None
            if name in elim_dnf and name in name_to_sid:
                sid = name_to_sid[name]
                if sid in live_time_for_sid:
                    candidate = live_time_for_sid[sid]
                    # Must fall within this round's time range (rejects previous-map carryover)
                    if t_lo is None or (t_lo <= candidate <= t_hi):
                        override_time = candidate
            if override_time is not None:
                time_for[name] = override_time
                note_for[name] = 'LIVE_OVERRIDE_DNF'
                overrides.append((round_num, name, override_time, plugin_rn))
            elif t_cotd is not None:
                time_for[name] = t_cotd
                note_for[name] = 'cotd'
            else:
                time_for[name] = None
                note_for[name] = 'dnf'

        timed = sorted(
            [(n, time_for[n]) for n in all_elim if time_for[n] is not None],
            key=lambda x: x[1],
        )
        untimed = [n for n in all_elim if time_for[n] is None]
        remaining -= all_elim
        base_pos = len(remaining)
        for i, (n, t) in enumerate(timed):
            results.append({
                'pos': base_pos + i + 1,
                'name': n,
                'time': t,
                'round': round_num,
                'note': note_for[n],
            })
        dnf_pos = base_pos + len(timed) + 1
        for n in untimed:
            results.append({
                'pos': dnf_pos,
                'name': n,
                'time': None,
                'round': round_num,
                'note': note_for[n],
            })

    if remaining:
        winner = next(iter(remaining))
        wt = cotd_rounds[-1]['block_players'].get(winner)
        results.append({'pos': 1, 'name': winner, 'time': wt, 'round': None, 'note': 'winner'})

    results.sort(key=lambda r: (r['pos'], 0 if r['time'] is not None else 1, r['name']))
    return results, overrides


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    cup = sys.argv[1]
    base = Path(__file__).parent / 'cup logs'
    cotd_path = base / f'petite_{cup}.log'
    live_path = base / f'petite_{cup}_liveleaderboard.log'
    if not cotd_path.exists():
        print(f'ERROR: {cotd_path} not found'); sys.exit(1)
    if not live_path.exists():
        print(f'ERROR: {live_path} not found'); sys.exit(1)

    print(f'Parsing cup {cup}...')
    cotd_rounds, cotd_lines = parse_cotdtracker(cotd_path)
    print(f'  COTDTracker: {len(cotd_rounds)} elim rounds')

    snaps = parse_livelog(live_path)
    print(f'  LiveLeaderboardLogger: {len(snaps)} snapshots')

    sid_to_name, name_to_sid, conflicts = build_sid_name_map(cotd_rounds, snaps)
    print(f'  sid-name map: {len(sid_to_name)} matched, {len(conflicts)} conflicts')
    for c in conflicts[:5]:
        safe = (c[0].encode('ascii', 'replace').decode('ascii'), c[1])
        print(f'    [conflict] {safe}')

    results, overrides = reconstruct(cotd_rounds, snaps, sid_to_name, name_to_sid)

    out_path = base / f'petite_{cup}_reconstructed.json'
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  Wrote {out_path}')

    if not overrides:
        print('\n  No DNF overrides — all COTDTracker DNFs are true DNFs.')
    else:
        print(f'\n  {len(overrides)} DNF -> LIVE TIME overrides:')
        for round_num, name, t, plugin_rn in overrides:
            safe_name = name.encode('ascii', 'replace').decode('ascii')
            print(f'    R{round_num:<2} {safe_name:<35} got live time {t:.5f} (plugin_round={plugin_rn})')

    # Extra: flag any player in our reconstructed results whose position differs from the
    # COTDTracker-only reconstruction (same rule, ignoring overrides).
    # Rebuild the COTD-only version for comparison
    cotd_only_results, _ = reconstruct(cotd_rounds, [], {}, {})
    ours_by_name = {r['name']: r for r in results}
    theirs_by_name = {r['name']: r for r in cotd_only_results}
    pos_diffs = []
    for name in sorted(set(ours_by_name) | set(theirs_by_name)):
        o = ours_by_name.get(name)
        t = theirs_by_name.get(name)
        if not o or not t:
            continue
        if o['pos'] != t['pos']:
            pos_diffs.append((name, o, t))
    if pos_diffs:
        print(f'\n  {len(pos_diffs)} POSITION CHANGES vs COTDTracker-only:')
        for name, o, t in pos_diffs:
            safe = name.encode('ascii', 'replace').decode('ascii')
            print(f'    {safe:<35} {t["pos"]} -> {o["pos"]} ({o.get("note","")})')


if __name__ == '__main__':
    main()

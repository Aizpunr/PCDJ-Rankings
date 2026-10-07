"""new_petite.py: process one REGULAR Petite Cup du Jour end to end.

Usage:
  python new_petite.py [N] --community M --map1 "..." [--mapper1 "..."]
                       --map2 "..." [--mapper2 "..."] --date YYYY-MM-DD
                       [--exclude a,b] [--log PATH] [--livelog PATH]
                       [--allow-gap] [--reprocess] [--no-open]

  N            our internal cup number ("Petite Cup N"). Omit it: the next one is
               assigned. Community numbers skip the specials, so N is never derived
               from M; M is stored next to it for cross-checking.
  --community  the community PCDJ number (the "#52" in the map names).
  --mapperX    who made map X. A mapper is excluded only if they were in the lobby.
  --exclude    other non-competitors (casters, testers), matched ignoring clan tags.
  --log        an attendee's LogOutput.log. Without --log the local BepInEx logs are
               used. With --log and no --livelog, no livelog is used: the local one
               would be another day's session.
  --allow-gap  skip the community-number and one-week date checks. For hand runs
               only (a skipped week); the submissions poller never passes it.
  --reprocess  redo the LATEST cup: restore the pre-cup xlsx and drop its
               cup_meta.json entry, then run again.

Specials (Troll, Roulette) are not handled here: they stay manual (add_cupN.py
plus a literal entry in petite_ranking.py).

Steps: snapshot (status.py), copy logs, parse, write the xlsx block, write
cup_meta.json, rebuild petite_rankings.json, cross-comp refresh, summary ending in
"PETITE CUP N COMPLETE" (submissions_poll.py keys on that line), localhost:9001.

PETITE_SKIP_EXTERNAL=1 skips the cross-comp refresh (it writes outside this repo)
and the localhost server. Tests and poller rehearsals set it.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda *f: os.path.join(_dir, *f)
sys.path.insert(0, _dir)

import openpyxl
import parse_petite_log as ppl
import petite_ranking as pr

BEPINEX = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx"
LOG_PATH = os.path.join(BEPINEX, 'LogOutput.log')
LIVE_LOG_PATH = os.path.join(BEPINEX, 'LiveLeaderboardLogger.log')
CROSSCOMP_SCRIPT = r"C:\Users\rafa\Desktop\Claude\zeepkist holistic\refresh.py"
PORT = 9001
COLS_PER_CUP = 6
SKIP_EXTERNAL = os.environ.get('PETITE_SKIP_EXTERNAL') == '1'


def fail(msg):
    print(f'ERROR: {msg}')
    sys.exit(1)


def recycle(path):
    """Send a file to the Windows Recycle Bin, never permanently delete."""
    r = subprocess.run([
        'powershell', '-NoProfile', '-Command',
        'Add-Type -AssemblyName Microsoft.VisualBasic; '
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        f"'{path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    ], capture_output=True, text=True)
    return r.returncode == 0


def write_json_atomic(path, data, compact=False):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        if compact:
            json.dump(data, f, separators=(',', ':'))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
    os.replace(tmp, path)


def run(script, *args, fatal=True):
    r = subprocess.run([sys.executable, _p(script), *args], cwd=_dir)
    if r.returncode != 0 and fatal:
        fail(f'{script} failed (returncode {r.returncode})')
    return r.returncode == 0


def xlsx_for(n):
    lo = 5 * ((n - 1) // 5) + 1
    return f'Petite Cups {lo}-{lo + 4}.xlsx', f'Cups {lo}-{lo + 4}', 1 + COLS_PER_CUP * ((n - 1) % 5)


def row2_labels(path):
    if not os.path.exists(path):
        return set()
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    labels = set()
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 1:
            labels = {str(v).strip() for v in row if v}
            break
    wb.close()
    return labels


def same_player(a, b):
    """Clan tags and alias spellings don't matter: '[CSC] redal' is 'redal'."""
    if pr.strip_tag(a).casefold() == pr.strip_tag(b).casefold():
        return True
    return pr.normalize(a) == pr.normalize(b)


def season_for(n):
    """The season whose cup offset is the largest one below n, and its round key."""
    season, offset = max(((s, o) for s, o in pr.SEASON_CUP_OFFSET.items() if o < n),
                         key=lambda x: x[1])
    return season, f'Round {n - offset}', n - offset


def known_cups():
    """{cup number: (season, round, label)} from the merged literal dicts + cup_meta."""
    out = {}
    for season, rounds in pr.FULL_LOBBY_REPLACEMENTS.items():
        for rnd, (_, label) in rounds.items():
            out[pr.cup_number(label)] = (season, rnd, label)
    return out


def maps_label(map1, mapper1, map2, mapper2):
    def one(m, by):
        return f'{m} by {by}' if by else m
    return f'Maps: {one(map1, mapper1)} + {one(map2, mapper2)}'


def parse_args():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument('cup', nargs='?', type=int)
    ap.add_argument('--community', type=int, required=True)
    ap.add_argument('--map1', required=True)
    ap.add_argument('--mapper1', default='')
    ap.add_argument('--map2', required=True)
    ap.add_argument('--mapper2', default='')
    ap.add_argument('--date', required=True)
    ap.add_argument('--exclude', default='')
    ap.add_argument('--log')
    ap.add_argument('--livelog')
    ap.add_argument('--allow-gap', action='store_true')
    ap.add_argument('--reprocess', action='store_true')
    ap.add_argument('--no-open', action='store_true')
    a = ap.parse_args()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a.date):
        fail(f'--date must be YYYY-MM-DD, got {a.date!r}')
    try:
        a.date_obj = datetime.date.fromisoformat(a.date)
    except ValueError:
        fail(f'--date {a.date} is not a real date')
    a.map1, a.map2 = a.map1.strip(), a.map2.strip()
    a.mapper1, a.mapper2 = a.mapper1.strip(), a.mapper2.strip()
    if not a.map1 or not a.map2:
        fail('both map names are required')
    a.exclude = [x.strip() for x in a.exclude.split(',') if x.strip()]
    return a


def undo_cup(n, meta):
    """--reprocess: put the xlsx and cup_meta.json back to how they were before Cup n."""
    label = f'Petite Cup {n}'
    entry = meta[label]
    xlsx = _p(entry['xlsx'])
    backup = _p('backups', f"{entry['xlsx']}.pre_cup_{n}.xlsx")
    os.makedirs(_p('backups'), exist_ok=True)
    keep = _p('backups', f"{entry['xlsx']}.pre_reprocess_{n}.xlsx")
    if os.path.exists(xlsx):
        shutil.copy2(xlsx, keep)
        print(f'  Saved the current book as backups/{os.path.basename(keep)}')
    if os.path.exists(backup):
        shutil.copy2(backup, xlsx)
        print(f'  Restored {entry["xlsx"]} from backups/{os.path.basename(backup)}')
    elif entry.get('created_xlsx'):
        if not recycle(xlsx):
            fail(f'could not move {entry["xlsx"]} to the Recycle Bin')
        print(f'  {entry["xlsx"]} was created for Cup {n}: sent to the Recycle Bin')
    else:
        fail(f'no pre-cup backup backups/{os.path.basename(backup)}; restore the xlsx by hand')
    del meta[label]
    write_json_atomic(pr.CUP_META_PATH, meta)
    pr.FULL_LOBBY_REPLACEMENTS[entry['season']].pop(entry['round'], None)
    pr.EVENT_DATES[entry['season']].pop(entry['round'], None)
    print(f'  Removed {label} from cup_meta.json')


def main():
    a = parse_args()
    meta = pr.load_cup_meta()
    cups = known_cups()

    # ── Which cup is this? ──
    by_community = {m['community']: lbl for lbl, m in meta.items() if 'community' in m}
    if a.reprocess:
        n = a.cup or pr.cup_number(by_community.get(a.community, 'Petite Cup 0'))
        label = f'Petite Cup {n}'
        if label not in meta:
            fail(f'--reprocess: {label} is not in cup_meta.json (only cups processed by new_petite.py can be redone)')
        if n != max(cups):
            fail(f'--reprocess: only the latest cup (Petite Cup {max(cups)}) can be redone')
        if meta[label].get('community') != a.community:
            fail(f'--reprocess: {label} is PCDJ #{meta[label].get("community")}, not #{a.community}')
        print(f'Reprocessing {label}...')
        undo_cup(n, meta)
        cups = known_cups()
    else:
        if a.community in by_community:
            fail(f'PCDJ #{a.community} is already processed (found in cup_meta.json as {by_community[a.community]})')
        n = max(cups) + 1
        if a.cup is not None and a.cup in cups:
            fail(f'Petite Cup {a.cup} is already processed (found in petite_ranking.py / cup_meta.json)')
        if a.cup is not None and a.cup != n:
            fail(f'Petite Cup {a.cup} is not the next cup (that is Petite Cup {n})')
    label = f'Petite Cup {n}'

    xlsx_name, sheet_name, col = xlsx_for(n)
    xlsx_path = _p(xlsx_name)
    if label in row2_labels(xlsx_path):
        fail(f'{label} is already processed (found in {xlsx_name} row 2)')

    season, rnd, round_no = season_for(n)
    if season not in pr.SEASON_TOTAL:
        fail(f'{season} has no SEASON_TOTAL yet; set the calendar in petite_ranking.py first')
    if round_no > pr.SEASON_TOTAL[season]:
        fail(f'{season} has {pr.SEASON_TOTAL[season]} events and {label} would be round {round_no}; '
             f'a new season needs SEASON_CUP_OFFSET / SEASON_TOTAL set up first')
    if rnd in pr.FULL_LOBBY_REPLACEMENTS.get(season, {}):
        fail(f'{season} {rnd} is already taken by {pr.FULL_LOBBY_REPLACEMENTS[season][rnd][1]}')

    # ── Gap guards: an unprocessed special or a skipped week would shift N ──
    prev_n = max(cups)
    prev_season, prev_rnd, prev_label = cups[prev_n]
    prev_date = pr.EVENT_DATES.get(prev_season, {}).get(prev_rnd)
    regular = [m for m in meta.values() if 'community' in m]
    if a.allow_gap:
        print('  --allow-gap: community-number and date checks skipped')
    elif round_no == 1:
        print(f'  {label} opens {season}: gap checks skipped')
    else:
        if regular:
            last_m = max(m['community'] for m in regular)
            if a.community != last_m + 1:
                fail(f'PCDJ #{a.community} does not follow PCDJ #{last_m}, the last processed regular cup. '
                     f'A cup in between is missing; aizpun must process this one by hand')
        if prev_date and prev_season == season:
            gap = (a.date_obj - datetime.date.fromisoformat(prev_date)).days
            if not 6 <= gap <= 8:
                fail(f'{a.date} is {gap} days after {prev_label} ({prev_date}), not one week. '
                     f'A cup in between is missing (an unprocessed special?) or the date is wrong; '
                     f'aizpun must process this one by hand')

    print('=' * 50)
    print(f'{label} = {season} {rnd} = PCDJ #{a.community}, {a.date}')
    print('=' * 50)

    # ── 1. Pre-cup snapshot: status.json = standings after Cup n-1 ──
    status_path = _p('status.json')
    as_of = None
    if os.path.exists(status_path):
        with open(status_path, encoding='utf-8') as f:
            as_of = json.load(f).get('as_of_cup')
    if as_of == n - 1:
        print(f'Snapshot: status.json already holds the standings after Cup {n - 1}, kept')
    else:
        print(f'Snapshot: rebuilding the standings after Cup {n - 1}...')
        run('petite_ranking.py')
        run('status.py')
        with open(status_path, encoding='utf-8') as f:
            snap = json.load(f)
        snap['as_of_cup'] = n - 1
        write_json_atomic(status_path, snap, compact=True)
    print()

    # ── 2. Logs ──
    if a.log:
        src_log, src_live = os.path.abspath(a.log), (os.path.abspath(a.livelog) if a.livelog else None)
    else:
        src_log = LOG_PATH
        src_live = os.path.abspath(a.livelog) if a.livelog else (LIVE_LOG_PATH if os.path.exists(LIVE_LOG_PATH) else None)
    if not os.path.exists(src_log):
        fail(f'log not found: {src_log}')
    if src_live and not os.path.exists(src_live):
        fail(f'livelog not found: {src_live}')
    logs = _p('cup logs')
    os.makedirs(logs, exist_ok=True)
    dst_log = os.path.join(logs, f'petite_{n}.log')
    dst_live = os.path.join(logs, f'petite_{n}_liveleaderboard.log')
    if os.path.abspath(src_log) != os.path.abspath(dst_log):
        shutil.copy2(src_log, dst_log)
    if src_live and os.path.abspath(src_live) != os.path.abspath(dst_live):
        shutil.copy2(src_live, dst_live)
    print(f'Logs: {os.path.basename(dst_log)}' + (f' + {os.path.basename(dst_live)}' if src_live else ' (no livelog)'))

    # ── 3. Parse ──
    try:
        results, overrides = ppl.parse(dst_log, dst_live if src_live else None, cup_date=a.date)
    except ppl.AmbiguousWinnerError as e:
        fail(f'no single winner in the log: {e}. Is it the complete cup?')
    except ValueError as e:
        fail(f'could not parse the log: {e}')
    ppl.write_results(results, os.path.join(logs, f'petite_{n}_reconstructed.json'))

    # ── 4. Exclusions ──
    names = [r['name'] for r in results]
    excluded, notes = [], []
    for i, mapper in ((1, a.mapper1), (2, a.mapper2)):
        if not mapper:
            continue
        hits = [x for x in names if same_player(x, mapper)]
        if hits:
            excluded += [h for h in hits if h not in excluded]
            notes.append(f'mapper {mapper} was in the lobby: excluded ({", ".join(hits)})')
        else:
            notes.append(f'mapper {mapper} was not in the lobby')
    for x in a.exclude:
        hits = [y for y in names if same_player(y, x)]
        if hits:
            excluded += [h for h in hits if h not in excluded]
            notes.append(f'excluded {x} ({", ".join(hits)})')
            # Not a mapper, so nothing else would mention it: surface it as a
            # warning so the player count on the site is explained rather than
            # just being one lower than the lobby.
            print(f'  WARNING: {", ".join(hits)} removed by hand (not a mapper)')
        else:
            print(f'  WARNING: excluded name {x!r} is not in the results; nothing to remove')
    for s in notes:
        print(f'  {s}')

    # Re-rank with ties kept (1, 2, 2, 4), as add_cupN.py did.
    rows, prev_pos, new_pos = [], None, 0
    for seen, e in enumerate((r for r in results if r['name'] not in excluded), start=1):
        if e['pos'] != prev_pos:
            new_pos, prev_pos = seen, e['pos']
        rows.append({**e, 'new_pos': new_pos})
    # A scoring finisher the registry has never seen is usually a known player
    # under a new display name, not a newcomer -- 'Vael' took 3rd at PCDJ #53
    # before anyone noticed he was B_ES. Only the top 10 score, so only warn there.
    try:
        import petite_ranking as _pr
        with open(os.path.join(_pr.elo_dir, 'steam_ids.json'), encoding='utf-8') as _f:
            _known = set(json.load(_f))
        for _r in rows[:10]:
            _c = _pr.normalize(_r['name'])
            if _c not in _known:
                print(f"  WARNING: {_r['name']!r} finished {_r['new_pos']} but is not in "
                      f"the player registry; check it is not a known player renamed")
    except Exception as _e:
        print(f'  WARNING: could not check finishers against the registry ({_e})')

    if not rows or rows[0]['new_pos'] != 1 or sum(r['new_pos'] == 1 for r in rows) != 1:
        fail('the results have no single winner after exclusions')
    winner = rows[0]
    n_rounds = max((r['round'] or 0) for r in rows)
    print(f'  {len(rows)} players, {n_rounds} elimination rounds, winner {winner["name"]}')
    print()

    # ── 5. xlsx block ──
    created = not os.path.exists(xlsx_path)
    if created:
        wb = openpyxl.Workbook()
        wb.active.title = sheet_name
        print(f'xlsx: new book {xlsx_name}')
    else:
        os.makedirs(_p('backups'), exist_ok=True)
        backup = _p('backups', f'{xlsx_name}.pre_cup_{n}.xlsx')
        if not os.path.exists(backup):
            shutil.copy2(xlsx_path, backup)
        wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    label_maps = maps_label(a.map1, a.mapper1, a.map2, a.mapper2)
    ws.cell(row=2, column=col, value=label)
    ws.cell(row=3, column=col, value=label_maps)
    for i, h in enumerate(('Position', 'Name', 'Elim Time', 'Elim Round')):
        ws.cell(row=5, column=col + i, value=h)
    for r in range(6, max(60, ws.max_row + 1)):
        for c in range(col, col + 4):
            ws.cell(row=r, column=c).value = None
    for i, e in enumerate(rows):
        r = 6 + i
        ws.cell(row=r, column=col, value=e['new_pos'])
        ws.cell(row=r, column=col + 1, value=e['name'])
        ws.cell(row=r, column=col + 2, value=round(e['time'], 5) if e['time'] is not None else 'DNF')
        if e['round'] is not None and e.get('note') != 'winner':
            ws.cell(row=r, column=col + 3, value=e['round'])
    wb.save(xlsx_path)
    print(f'xlsx: {label} -> {xlsx_name}, columns {col}-{col + 3}')

    # ── 6. cup_meta.json ──
    meta[label] = {
        'season': season,
        'round': rnd,
        'xlsx': xlsx_name,
        'date': a.date,
        'community': a.community,
        'maps': [{'name': a.map1, 'mapper': a.mapper1}, {'name': a.map2, 'mapper': a.mapper2}],
        'maps_label': label_maps,
        'excluded': excluded,
    }
    if created:
        meta[label]['created_xlsx'] = True
    write_json_atomic(pr.CUP_META_PATH, meta)
    print(f'cup_meta.json: {label} added')
    print()

    # ── 7. Rankings ──
    print('Rebuilding petite_rankings.json...')
    run('petite_ranking.py')
    print()

    # ── 8. Cross-comp ──
    failed = []
    crosscomp_ok = False
    if SKIP_EXTERNAL:
        print('SKIP (PETITE_SKIP_EXTERNAL): cross-comp refresh')
    elif os.path.exists(CROSSCOMP_SCRIPT):
        r = subprocess.run([sys.executable, CROSSCOMP_SCRIPT], cwd=os.path.dirname(CROSSCOMP_SCRIPT))
        if r.returncode == 0:
            crosscomp_ok = True
            print('Cross-comp + SOF data refreshed.')
        else:
            failed.append(f'cross-comp refresh ({CROSSCOMP_SCRIPT})')
            print(f'  WARNING: cross-comp refresh failed (returncode {r.returncode})')
    else:
        failed.append(f'cross-comp refresh: {CROSSCOMP_SCRIPT} not found')
    print()

    # ── 9. Summary ──
    print('=' * 50)
    print(f'PETITE CUP {n} COMPLETE')
    if failed:
        print(f'  !! {len(failed)} non-fatal step(s) FAILED — fix before pushing:')
        for s in failed:
            print(f'     - {s}')
    t = f'{winner["time"]:.3f}' if winner['time'] is not None else 'no time'
    print(f'  {season} {rnd}, PCDJ #{a.community}, {a.date}')
    print(f'  Players: {len(rows)}')
    print(f'  Winner: {winner["name"]} ({t})')
    if overrides:
        print(f'  Livelog DNF overrides: {len(overrides)}')
    print()
    print('Next steps (after verifying on localhost):')
    print(f'  - git commit + push: cup_meta.json, petite_rankings.json, status.json, "{xlsx_name}", cup logs/petite_{n}*')
    if crosscomp_ok:
        print('  - SOF repo: commit + push elo_pool.json and docs/allcompdata.json')
    print('=' * 50)

    # ── 10. Localhost preview ──
    # Not for a scratch copy: a detached server there would keep answering on
    # 9001 and later serve stale pages in place of the real repo.
    if SKIP_EXTERNAL:
        print(f'SKIP (PETITE_SKIP_EXTERNAL): localhost:{PORT} server')
        return
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=0.3):
            serving = True
    except OSError:
        serving = False
    if serving:
        print(f'localhost:{PORT} already serving.')
    else:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, '-m', 'http.server', str(PORT)], cwd=_dir, creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Started http.server on localhost:{PORT} (detached).')
    if a.no_open:
        print(f'--no-open: verify on http://localhost:{PORT}, then push manually.')
    else:
        try:
            os.startfile(f'http://localhost:{PORT}')
        except OSError:
            print(f'Open http://localhost:{PORT} to verify, then push manually.')


if __name__ == '__main__':
    main()

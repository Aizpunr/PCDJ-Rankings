"""
status.py — write status.json (snapshot) from petite_rankings.json

Usage:
  python status.py          → snapshot current standings (run BEFORE adding new cup)
  python status.py 9        → reconstruct Season 3 at round 9 (for retroactive snapshot)

Stores: rank, points, wins, gold, silver, bronze per player.
Only the newest season is snapshotted (finished seasons get no arrows).
PCDJ is always snapshotted directly, along with its trailing-season window.
"""
import json, os, re, sys

sys.stdout.reconfigure(encoding='utf-8')  # player names aren't all cp1252 (e.g. Mμ)

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

with open(_p('petite_rankings.json'), encoding='utf-8') as f:
    data = json.load(f)

target_round = int(sys.argv[1]) if len(sys.argv) > 1 else None

def snap_direct(season_data):
    """Snapshot rankings directly as they are."""
    rankings = season_data.get('rankings', [])
    return {
        p['name']: [p['rank'], p['points'], p.get('wins', 0),
                     p['podiums']['gold'], p['podiums']['silver'], p['podiums']['bronze']]
        for p in rankings if p['points'] > 0
    }

def snap_at_round(season_data, target):
    """Reconstruct season standings up to a target round number."""
    rankings = season_data.get('rankings', [])
    if not rankings:
        return {}
    player_data = {}
    for p in rankings:
        pts = 0
        wins = 0
        gold = silver = bronze = 0
        for h in p.get('history', []):
            m = re.search(r'(\d+)', h['r'])
            if not m:
                continue
            if int(m.group(1)) <= target:
                pts += h['p']
                if h['pos'] == 1: wins += 1; gold += 1
                elif h['pos'] == 2: silver += 1
                elif h['pos'] == 3: bronze += 1
        if pts > 0:
            player_data[p['name']] = (pts, wins, gold, silver, bronze)

    sorted_players = sorted(player_data.items(), key=lambda x: x[1][0], reverse=True)
    return {
        name: [rank + 1, pts, wins, gold, silver, bronze]
        for rank, (name, (pts, wins, gold, silver, bronze)) in enumerate(sorted_players)
    }

# Build snapshot
snap = {}

# Current season: the highest-numbered one present. Finished seasons are skipped
# (no arrows), so this follows the rollover without needing an edit each season.
seasons = [k for k in data if data[k].get('type') == 'season']
current = max(seasons, key=lambda s: int(re.search(r'\d+', s).group()), default=None)
if current:
    key = current.lower().replace(' ', '_')
    if target_round is not None:
        snap[key] = snap_at_round(data[current], target_round)
    else:
        snap[key] = snap_direct(data[current])

# PCDJ: always snapshot directly (drops/best-of too complex to reconstruct).
# Record the trailing window alongside it: when it rolls (S2+S3 -> S3+S4) a whole
# season's points leave at once, and the site uses this to suppress the resulting
# bogus deltas instead of showing everyone collapsing on one cup.
if 'PCDJ Ranking' in data:
    snap['pcdj_ranking'] = snap_direct(data['PCDJ Ranking'])
    snap['pcdj_seasons'] = data['PCDJ Ranking'].get('seasons', [])

# Backup existing status.json
status_path = _p('status.json')
if os.path.exists(status_path):
    import shutil
    backup_dir = _p('old_status')
    os.makedirs(backup_dir, exist_ok=True)
    i = 0
    backup_path = os.path.join(backup_dir, f'status_{target_round or "current"}.json')
    while os.path.exists(backup_path):
        i += 1
        backup_path = os.path.join(backup_dir, f'status_{target_round or "current"}_{i}.json')
    shutil.copy2(status_path, backup_path)
    print(f"Backed up old status -> {os.path.basename(backup_path)}")

with open(status_path, 'w', encoding='utf-8') as f:
    json.dump(snap, f, separators=(',', ':'))

label = f"round {target_round}" if target_round else "current"
print(f"status.json written ({label})")

# Show current season top 10
s3 = snap.get(current.lower().replace(' ', '_'), {}) if current else {}
if s3:
    top = sorted(s3.items(), key=lambda x: x[1][0])[:10]
    print(f"\n{current} top 10:")
    for name, (rank, pts, wins, g, s, b) in top:
        print(f"  #{rank} {name}: {pts} pts, {wins}W, {g}G/{s}S/{b}B")

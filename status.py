"""
status.py — write status.json (snapshot) from petite_rankings.json

Usage:
  python status.py          → snapshot current standings (run BEFORE adding new cup)
  python status.py 9        → reconstruct Season 3 at round 9 (for retroactive snapshot)

Stores: rank, points, wins, gold, silver, bronze per player.
Season 2 is excluded (finished). PCDJ is always snapshotted directly.
"""
import json, os, re, sys

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

# Season 3: reconstruct at target round, or snapshot current
if 'Season 3' in data:
    if target_round is not None:
        snap['season_3'] = snap_at_round(data['Season 3'], target_round)
    else:
        snap['season_3'] = snap_direct(data['Season 3'])

# PCDJ: always snapshot directly (drops/best-of too complex to reconstruct)
if 'PCDJ Ranking' in data:
    snap['pcdj_ranking'] = snap_direct(data['PCDJ Ranking'])

# Season 2: skip (finished)

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

# Show season 3 top 10
s3 = snap.get('season_3', {})
if s3:
    top = sorted(s3.items(), key=lambda x: x[1][0])[:10]
    print(f"\nSeason 3 top 10:")
    for name, (rank, pts, wins, g, s, b) in top:
        print(f"  #{rank} {name}: {pts} pts, {wins}W, {g}G/{s}S/{b}B")

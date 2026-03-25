"""
status.py — write status.json (snapshot) from petite_rankings.json

Usage:
  python status.py          → snapshot = current standings
  python status.py 38       → snapshot = standings as of round 38
"""
import json, os, sys

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

with open(_p('petite_rankings.json'), encoding='utf-8') as f:
    data = json.load(f)

target_round = int(sys.argv[1]) if len(sys.argv) > 1 else None

def build_snap(season_data, target=None):
    """Build snapshot from a season's rankings.
    If target is given, reconstruct standings up to that round number."""
    rankings = season_data.get('rankings', [])
    if not rankings:
        return {}

    if target is None:
        # Use current standings as-is
        return {
            p['name']: [p['rank'], p['points'], p.get('wins', 0), p['podiums']['gold'] + p['podiums']['silver'] + p['podiums']['bronze']]
            for p in rankings
        }

    # Reconstruct standings up to target round
    player_pts = {}
    for p in rankings:
        pts = 0
        for h in p.get('history', []):
            # Extract round number from "Round X" / "Troll X" / "PCDJ X"
            import re
            m = re.search(r'(\d+)', h['r'])
            if not m:
                continue
            rnum = int(m.group(1))
            if rnum <= target:
                pts += h['p']
        if pts > 0:
            pods = 0
            wins = 0
            for h in p.get('history', []):
                m = re.search(r'(\d+)', h['r'])
                if not m:
                    continue
                rnum = int(m.group(1))
                if rnum <= target:
                    if h['pos'] == 1: wins += 1
                    if h['pos'] <= 3: pods += 1
            player_pts[p['name']] = (pts, wins, pods)

    # Sort by points descending
    sorted_players = sorted(player_pts.items(), key=lambda x: x[1][0], reverse=True)
    return {
        name: [rank + 1, pts, wins, pods]
        for rank, (name, (pts, wins, pods)) in enumerate(sorted_players)
    }

snap = {}
for season_name in ['Season 2', 'Season 3', 'PCDJ Ranking']:
    if season_name in data:
        key = season_name.lower().replace(' ', '_')
        snap[key] = build_snap(data[season_name], target_round)

# Backup existing status.json
status_path = _p('status.json')
if os.path.exists(status_path):
    import shutil
    backup_dir = _p('old_status')
    os.makedirs(backup_dir, exist_ok=True)
    with open(status_path, encoding='utf-8') as f:
        old = json.load(f)
    # Find a unique backup name
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
    for name, (rank, pts, wins, pods) in top:
        print(f"  #{rank} {name}: {pts} pts, {wins}W, {pods}P")

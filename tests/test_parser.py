"""parse_petite_log.parse() reproduces every saved cup it should, with and without the livelog."""
import contextlib
import io
import json

import pytest

from conftest import REPO
import parse_petite_log as ppl

LOGS = REPO / 'cup logs'
EXCLUDED = json.loads((REPO / 'tests' / 'fixtures' / 'excluded_cups.json').read_text(encoding='utf-8'))
CUPS = sorted(int(p.name.split('_')[1].split('.')[0]) for p in LOGS.glob('petite_*.log')
              if p.name.count('_') == 1 and (LOGS / f'petite_{p.stem.split("_")[1]}_reconstructed.json').exists())


def saved(n):
    return json.loads((LOGS / f'petite_{n}_reconstructed.json').read_text(encoding='utf-8'))


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


@pytest.mark.parametrize('n', [n for n in CUPS if str(n) not in EXCLUDED])
def test_log_alone_reproduces_saved(n):
    results, overrides = quiet(ppl.parse, LOGS / f'petite_{n}.log')
    assert overrides == []
    assert results == saved(n)


# Excluded from the log-alone test because the livelog corrects them, so they
# still have to reproduce WITH it: exclusion must not mean no coverage.
@pytest.mark.parametrize('n', [43, 57, 58])
def test_livelog_override_reproduces_saved(n):
    results, overrides = quiet(ppl.parse, LOGS / f'petite_{n}.log',
                               LOGS / f'petite_{n}_liveleaderboard.log')
    assert len(overrides) == 1
    assert results == saved(n)


def test_saved_livelogs_hold_one_session_only():
    """The logger's file is cumulative: every copy used to carry months of
    earlier sessions, 113 MB across the repo, and only the last session is
    ever read. That weight is what stopped GitHub Pages deploying, so the
    saved copies start at their own SESSION_START and must stay that way."""
    for lv in sorted(LOGS.glob('*_liveleaderboard.log')):
        data = lv.read_bytes()
        assert data.count(b'SESSION_START') <= 1, (
            f'{lv.name} holds {data.count(b"SESSION_START")} sessions; trim it to the last one')
        assert len(data) < 4 * 1024 * 1024, f'{lv.name} is {len(data)/1048576:.1f} MB; it should be a single session'


def test_stale_livelog_is_ignored():
    # Cup 53's livelog session is 2026-09-30; claiming another date must drop it.
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        results, overrides = ppl.parse(LOGS / 'petite_43.log', LOGS / 'petite_53_liveleaderboard.log',
                                       cup_date='2026-01-01')
    assert 'ignoring the livelog' in out.getvalue()
    assert overrides == []


def test_two_players_standing_is_an_error(tmp_path):
    # Cut the log before the final elimination: two players are left standing.
    lines = (LOGS / 'petite_53.log').read_text(encoding='utf-8', errors='replace').splitlines()
    last = max(i for i, ln in enumerate(lines) if 'Doing eliminations with leaderboard' in ln)
    cut = tmp_path / 'cut.log'
    cut.write_text('\n'.join(lines[:last]), encoding='utf-8')
    rounds, _ = ppl.parse_cotdtracker(cut)
    final_two = set(rounds[-1]['block_players']) - set(rounds[-1]['elim_dnf']) - set(rounds[-1]['elim_time'])
    if len(final_two) < 2:
        pytest.skip('cut point does not leave two players standing')
    with pytest.raises(ppl.AmbiguousWinnerError):
        quiet(ppl.parse, cut)

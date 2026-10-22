"""A log sent for a cup that is already published must be checked against it,
not just counted. These run against real cup logs committed to the repo."""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import submissions_poll as sp


class Ctx:
    repo = REPO


# The submissions as the page recorded them, so the comparison reruns each
# cup with its own mappers rather than a guess.
CUP_55 = {'community': 54, 'date': '2026-10-14',
          'mapper1': 'IronDragon111000', 'mapper2': 'Tommygaming', 'exclude': []}
CUP_56 = {'community': 55, 'date': '2026-10-21',
          'mapper1': '[CSC] PlusMicron', 'mapper2': 'felix', 'exclude': []}


def log_for(cup):
    path = os.path.join(REPO, 'cup logs', f'petite_{cup}.log')
    if not os.path.exists(path):
        pytest.skip(f'petite_{cup}.log is not in this checkout')
    return path


@pytest.mark.parametrize('sub,cup', [(CUP_55, '55'), (CUP_56, '56')])
def test_resend_of_the_same_cup_matches(sub, cup):
    note, review = sp.compare_with_published(Ctx(), sub, log_for(cup), cup)
    assert note == 'matches the published result'
    assert review is False


def test_a_log_from_another_cup_is_flagged():
    note, review = sp.compare_with_published(Ctx(), CUP_55, log_for('55'), '56')
    assert review is True
    assert 'DIFFERS' in note
    assert 'winner' in note


def test_dropping_the_mappers_changes_the_player_count():
    # The mappers played, so a submitter who leaves them out publishes a
    # bigger lobby than the one on the site. That has to be visible.
    sub = dict(CUP_56, mapper1='', mapper2='')
    note, review = sp.compare_with_published(Ctx(), sub, log_for('56'), '56')
    assert review is True
    assert 'players (published 33)' in note


def test_an_unparseable_log_is_flagged_not_swallowed():
    note, review = sp.compare_with_published(Ctx(), CUP_56, __file__, '56')
    assert review is True
    assert 'could not be parsed' in note


def test_published_result_reads_back_the_excluded_lobby():
    have = sp.published_result(Ctx(), '56')
    assert have['winner'] == 'ZOMAN'
    assert have['players'] == 33
    # Excluded mappers must not reappear in the published side either.
    assert '[CSC] PlusMicron' not in have['podium']


# ── re-deriving a stored summary ──────────────────────────────────────
# A summary is frozen when the cup is submitted, so it keeps the names the
# log used and whatever went wrong that night. Neither should outlive the
# facts changing.

def test_resummarize_resolves_merged_aliases():
    # PCDJ #53 was submitted before Vael was known to be B_ES and
    # tatari_lover2008 to be Sterben.
    got = sp.rebuild_summary(Ctx(), '54')
    names = [p['name'] for p in got['podium']]
    assert 'Vael' not in names and 'tatari_lover2008' not in names
    assert names == ['justMaki', 'Sterben', 'B_ES']


def test_resummarize_drops_warnings_that_no_longer_hold():
    # Cup 56's stored summary carries the cross-comp failure from that night
    # and a registry warning for shmoogl, who has since been registered.
    got = sp.rebuild_summary(Ctx(), '56')
    assert got['warnings'] == []
    assert got['winner'] == 'ZOMAN'
    assert got['players'] == 33


def test_an_unregistered_scorer_still_warns(monkeypatch):
    # The warning must only go quiet because someone registered the player,
    # never because the check was loosened.
    import petite_ranking as pr
    monkeypatch.setattr(pr, 'CANONICAL', {})
    monkeypatch.setattr(pr, 'normalize', lambda n: 'nobody-has-ever-seen-this')
    got = sp.rebuild_summary(Ctx(), '56')
    assert got['warnings'], 'an unknown scoring finisher must still be flagged'
    assert 'not in the player registry' in got['warnings'][0]

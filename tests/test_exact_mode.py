"""The bounded exact mode must never lose an optimum: compare with brute force (toy) and with the
unbounded full search (small real instance)."""

import random
from datetime import date

import pytest

from bcplanner.bounds import UpperBound
from bcplanner.search import coverage_problem, search, search_exact
from helpers import fixture_problem
from test_search_small import brute_force, make_problem


@pytest.mark.parametrize("seed", [31, 32, 33, 34, 35, 36])
def test_exact_mode_matches_brute_force_on_toys(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng)
    bf_value, _ = brute_force(problem)
    res = search_exact(problem, beam_first=2)
    assert res.stats.proven_optimal
    assert abs(res.best_value().value - bf_value) < 1e-9


@pytest.mark.parametrize("seed", [37, 38, 39])
def test_exact_mode_matches_brute_force_with_duplicate_values(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng, dupe_values={"supa": 0.1, "uber": 0.3, "legend": 1.0})
    bf_value, _ = brute_force(problem)
    res = search_exact(problem, beam_first=2)
    assert res.stats.proven_optimal
    assert abs(res.best_value().value - bf_value) < 1e-9


def test_bound_is_never_below_a_real_continuation():
    # the relaxed bound at the root must be >= the true optimum found by the unbounded full search
    rng = random.Random(41)
    problem = make_problem(rng.getrandbits(32), rng, tickets=3, cat_food=1500, plats=1, legends=1)
    full = search(problem, beam=None)
    ub = UpperBound(problem)
    assert ub.ub(0, problem.tickets, problem.cf_units, problem.plats, problem.legends, 0) >= full.best_value().value - 1e-9


def test_exact_mode_matches_unbounded_search_on_real_banners():
    prob, _ = fixture_problem(today=date(2026, 9, 13), tickets=6, cat_food=1500, plats=1, legends=1)
    full = search(prob, beam=None)                      # small enough to run unbounded
    ex = search_exact(prob, beam_first=3)
    assert ex.stats.proven_optimal
    assert abs(ex.best_value().value - full.best_value().value) < 1e-9
    # and the frontier agrees at every spend level
    g1, g2 = full.heatmap(), ex.heatmap()
    assert all(abs(a - b) < 1e-9 for r1, r2 in zip(g1, g2) for a, b in zip(r1, r2))


def test_coverage_problem_counts_targets_only():
    prob, _ = fixture_problem(today=date(2026, 9, 13), tickets=4, cat_food=0, plats=0, legends=0)
    cp = coverage_problem(prob)
    targets = set(prob.mask_ids(prob.targets_mask))
    assert set(cp.unit_ids) == targets
    assert all(abs(cp.value_of(c) - 1.0) < 1e-9 for c in targets)

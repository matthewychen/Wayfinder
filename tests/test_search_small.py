"""The exact search must agree with brute-force enumeration on toy instances.

Toy banners are small enough that every legal action sequence can be enumerated;
each prefix is evaluated by the independent replay checker. The search with an
unbounded beam must find the same best value and the same cheapest coverage cost,
and every plan it returns must replay without problems.
"""

import random
from datetime import date

import pytest

from bcplanner.actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE
from bcplanner.model import Banner
from bcplanner.problem import Problem
from bcplanner.replay import replay
from bcplanner.search import search
from bcplanner.sim import Tables

TODAY = date(2026, 9, 13)


def toy_banners(rng: random.Random):
    ubers_all = [900, 901, 902, 903]
    legends_all = [950, 951]
    b1 = Banner("2026-09-11_1", 1, "Toy A", date(2026, 9, 11), date(2026, 9, 18), (7000, 2500, 500, 0),
                {"rare": [10, 11, 12], "supa": [20, 21], "uber": [900, 901]}, guaranteed_rolls=11)
    b2 = Banner("2026-09-11_2", 2, "Toy B", date(2026, 9, 11), date(2026, 9, 14), (6970, 2500, 500, 30),
                {"rare": [10, 13, 14], "supa": [22, 23], "uber": [902, 903], "legend": [950]}, guaranteed_rolls=0)
    b3 = Banner("2026-09-14_3", 3, "Toy C (tomorrow)", date(2026, 9, 14), date(2026, 9, 18), (7000, 2500, 500, 0),
                {"rare": [11, 12, 15], "supa": [21, 24], "uber": [901, 903]}, guaranteed_rolls=11)
    plat = Banner("2026-07-24_8", 8, "Toy platinum", date(2026, 7, 24), date(2030, 1, 1), (0, 0, 10000, 0),
                  {"uber": ubers_all})
    leg = Banner("2026-07-24_9", 9, "Toy legend", date(2026, 7, 24), date(2030, 1, 1), (0, 0, 9500, 500),
                 {"uber": ubers_all, "legend": legends_all})
    return {b.event_id: b for b in (b1, b2, b3, plat, leg)}


def make_problem(seed: int, rng: random.Random, **kw):
    banners = toy_banners(rng)
    tables = Tables(seed, 400)
    owned = frozenset(rng.sample([10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 24, 900, 901, 902, 903, 950, 951], 5))
    return Problem(tables=tables, banners=banners, owned=owned, today=TODAY, last_id=rng.choice([0, 10, 11, 12]),
                   tickets=kw.get("tickets", 2), cat_food=kw.get("cat_food", 1500), plats=kw.get("plats", 1),
                   legends=kw.get("legends", 1), max_clock_changes=2,
                   discount_first_draw=rng.random() < 0.5,
                   dupe_values=kw.get("dupe_values", {"supa": 0.0, "uber": 0.0, "legend": 0.0}),
                   pass_penalties=kw.get("pass_penalties", {"uber": 0.5, "uber_fest": 0.1}))


def all_actions(problem: Problem):
    acts = [(PLAT,), (LEGEND,), (CLOCK, "tomorrow"), (CLOCK, "today")]
    for b in problem.rare_banners:
        acts.append((SINGLE, b.event_id))
        acts.append((ELEVEN, b.event_id))
    return acts


def brute_force(problem: Problem):
    """Enumerate every legal sequence (depth-first); return (best value, cheapest covering cost)."""
    acts = all_actions(problem)
    best_value = 0.0
    best_cover = None
    targets = problem.targets_mask
    max_depth = problem.tickets + problem.cf_units + problem.plats + problem.legends + problem.max_clock_changes + 1

    def gained_mask(rep):
        m = 0
        for cid in rep.gained:
            m |= problem.bit(cid)
        return m

    def visit(prefix):
        nonlocal best_value, best_cover
        rep = replay(problem, prefix)
        hard = [x for x in rep.problems
                if not (x.startswith("plan does not end") or x.startswith("the last legend ticket"))]
        if hard:
            return                      # illegal prefix: no extension can repair it
        if not rep.problems:            # a finished plan (clock back on today)
            if rep.value > best_value + 1e-9:
                best_value = rep.value
            if (gained_mask(rep) & targets) == targets:
                cost = problem.scalar_cost(rep.tickets, rep.cf_units, rep.plats, rep.clock_changes)
                if best_cover is None or cost < best_cover - 1e-9:
                    best_cover = cost
        if len(prefix) >= max_depth:
            return
        for a in acts:
            visit(prefix + [a])

    visit([])
    return best_value, best_cover


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_search_matches_brute_force(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng)
    bf_value, bf_cover = brute_force(problem)
    res = search(problem, beam=None)
    assert not res.stats.truncated
    best = res.best_value()
    assert best is not None
    assert abs(best.value - bf_value) < 1e-9, (best.value, bf_value)
    rep = replay(problem, res.plan_actions(best))
    assert rep.problems == [] and abs(rep.value - best.value) < 1e-9
    cov = res.cheapest_covering()
    if bf_cover is None:
        assert cov is None
    else:
        assert cov is not None and abs(res.cost(cov) - bf_cover) < 1e-9
        rep2 = replay(problem, res.plan_actions(cov))
        assert rep2.problems == []


@pytest.mark.parametrize("seed", [41, 42, 43])
def test_search_matches_brute_force_without_pass_penalties(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng, pass_penalties={})
    bf_value, _ = brute_force(problem)
    res = search(problem, beam=None)
    assert abs(res.best_value().value - bf_value) < 1e-9


def test_passed_slots_are_the_other_track_and_reroll_jumps():
    rng = random.Random(7)
    problem = make_problem(rng.getrandbits(32), rng, tickets=3, cat_food=1500)
    b = problem.rare_banners[0]
    rep = replay(problem, [(SINGLE, b.event_id), (ELEVEN, b.event_id)])
    st1, st2 = rep.steps
    plain = st1.offset_after - st1.offset_before == 2
    expect1 = [st1.offset_before + 1] if plain else [st1.offset_before + 1, st1.offset_before + 2]
    assert [p for p in expect1 if problem.slot_band(p)] == [p for p, _, _ in st1.passed]
    landed = {rv.offset_before for rv in st2.rolls}
    expect2 = [p for p in range(st2.offset_before, st2.offset_after) if p not in landed and problem.slot_band(p)]
    assert expect2 == [p for p, _, _ in st2.passed]
    # the toy problem values repeats at 0, so a passed slot costs the band penalty when an open banner
    # has a new uber there and nothing otherwise
    for s in rep.steps:
        assert abs(s.penalty - sum(problem.pass_penalties.get(band, 0.0) for _, band, kind in s.passed
                                   if kind == "new")) < 1e-9


@pytest.mark.parametrize("seed", [21, 22, 23, 24])
def test_search_matches_brute_force_with_duplicate_values(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng, dupe_values={"supa": 0.1, "uber": 0.3, "legend": 1.0})
    bf_value, _ = brute_force(problem)
    res = search(problem, beam=None)
    best = res.best_value()
    assert abs(best.value - bf_value) < 1e-9, (best.value, bf_value)
    rep = replay(problem, res.plan_actions(best))
    assert rep.problems == [] and abs(rep.value - best.value) < 1e-9
    assert rep.value >= sum(1 for st_ in rep.steps for rv in st_.rolls if rv.rarity == "uber" and not rv.new) * 0.3 - 1e-9


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_every_frontier_plan_replays_cleanly(seed):
    rng = random.Random(seed)
    problem = make_problem(rng.getrandbits(32), rng, tickets=4, cat_food=3000, plats=2, legends=1)
    res = search(problem, beam=4)
    for lab in res.frontier():
        rep = replay(problem, res.plan_actions(lab))
        assert rep.problems == [], rep.problems
        assert abs(rep.value - lab.value) < 1e-9
        assert (rep.tickets, rep.cf_units, rep.plats, rep.legends) == (lab.t, lab.c, lab.p, lab.l)

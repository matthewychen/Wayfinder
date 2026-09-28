"""Value of saving resources for the next banner."""

import random

from bcplanner.future import FutureModel, FutureValue, estimate_p_new
from bcplanner.search import search
from helpers import fixture_problem
from test_search_small import make_problem


def test_flat_mode_is_per_draw_arithmetic():
    prob, _ = fixture_problem(tickets=30, cat_food=3000)
    fv = FutureValue(prob, FutureModel(mode="flat", flat_per_draw=2.0))
    assert abs(fv.value(0, 30, 4, 0, 0) - 2.0 * (30 / 30 + 4 / 2)) < 1e-9
    assert fv.value(0, 0, 0, 0, 0) == 0.0
    assert FutureValue(prob, FutureModel(mode="none")).value(0, 30, 4, 1, 1) == 0.0


def test_seed_mode_scores_known_bands_and_grows_with_resources():
    prob, _ = fixture_problem(tickets=6, cat_food=3000, plats=1, legends=1)
    prob.pass_penalties = {}
    prob.ticket_cost = 0.0
    fv = FutureValue(prob, FutureModel(mode="seed", confidence=1.0, flat_per_draw=0.0,
                                       p_new={"rare": 1.0, "supa": 1.0, "uber": 1.0, "legend": 1.0}))
    # with no pass penalties and no floor, one ticket from position k is worth the band at k (all new)
    for k in range(0, 40):
        assert abs(fv.value(k, 1, 0, 0, 0) - prob.weights.get(fv.band(k), 0.0)) < 1e-9
    # more resources never hurt
    v1, v2, v3 = fv.value(0, 2, 0, 0, 0), fv.value(0, 4, 0, 0, 0), fv.value(0, 4, 2, 0, 0)
    assert v1 <= v2 <= v3
    # an 11-draw with a guaranteed uber is worth the ten landed bands plus one uber
    landed = sum(prob.weights.get(fv.band(2 * i), 0.0) for i in range(10)) + prob.weights["uber"]
    assert abs(fv.value(0, 0, 2, 0, 0) - landed) < 1e-9
    # with pass penalties on, rolls later pay them too, so the value can only drop
    prob.pass_penalties = {"uber": 0.8, "uber_fest": 0.2}
    fv2 = FutureValue(prob, FutureModel(mode="seed", confidence=1.0, flat_per_draw=0.0,
                                        p_new={"rare": 1.0, "supa": 1.0, "uber": 1.0, "legend": 1.0}))
    assert fv2.value(0, 4, 2, 0, 0) <= v3 + 1e-9
    est = estimate_p_new(prob)
    assert all(0.0 <= v <= 1.0 for v in est.values()) and set(est) == {"rare", "supa", "uber", "legend"}


def test_seed_mode_never_prices_kept_resources_below_the_floor():
    prob, _ = fixture_problem(tickets=30, cat_food=3000, plats=1)
    fv = FutureValue(prob, FutureModel(mode="seed", flat_per_draw=2.0, confidence=0.8,
                                       p_new={"supa": 0.0, "uber": 0.3, "legend": 0.5}))
    for t, c in ((30, 4), (10, 0), (0, 2), (3, 2)):
        assert fv.value(300, t, c, 0, 0) >= 2.0 * (t / 30 + c / 2) - 1e-9     # far ahead, where the estimate is small
    # steering value: more tickets kept beside a guaranteed draw means more candidate ubers to pick from
    s1, s2, s3 = fv.selection(1, 2, 0), fv.selection(10, 2, 0), fv.selection(30, 2, 0)
    assert 0 < s1 < s2 < s3
    assert fv.selection(30, 0, 0) == 0.0                                   # nothing to place: no steering value
    assert fv.describe(300, 30, 4, 0, 0)["basis"] in ("floor", "estimate")


def test_best_total_saves_when_the_future_is_worth_more():
    rng = random.Random(5)
    problem = make_problem(rng.getrandbits(32), rng, pass_penalties={})
    res = search(problem, beam=None)
    now = res.best_value()
    huge = FutureValue(problem, FutureModel(mode="flat", flat_per_draw=100.0))
    saved = res.best_total(huge)
    assert saved.t == 0 and saved.c == 0              # keep every ticket and all cat food
    nothing = FutureValue(problem, FutureModel(mode="none"))
    assert abs(res.best_total(nothing).value - now.value) < 1e-9
    total = res.total(saved, huge)
    assert total >= res.total(now, huge) - 1e-9

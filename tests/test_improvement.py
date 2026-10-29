"""The rare planner's improvement factor: plan value against the same spend pulled straight on one banner."""

import random

from bcplanner.actions import ELEVEN, SINGLE
from bcplanner.metrics import compute, straight_value
from bcplanner.replay import replay
from bcplanner.report import plan_text
from bcplanner.sim import Tables, eleven, sequence
from helpers import fixture_problem


def test_straight_value_matches_pulling_straight_on_random_seeds():
    P, _names = fixture_problem(tickets=60, cat_food=4500)
    avg, ev = straight_value(P, 60, 3, 0, 0)
    assert ev and P.live[ev][0]
    b = P.banners[ev]
    rng = random.Random(5)
    total, n = 0.0, 600
    for _ in range(n):
        T = Tables(rng.getrandbits(32), 300)
        rolls, k, last = sequence(T, b, 0, 0, 60)
        got = {r.cat_id for r in rolls}
        for _e in range(3):
            rs, g, k, last = eleven(T, b, k, last, b.guaranteed_rolls)
            got |= {r.cat_id for r in rs} | ({g.cat_id} if g else set())
        total += sum(P.value_of(c) for c in got if c in P.unit_index)
    assert abs(total / n - avg) / avg < 0.02


def test_best_banner_is_the_best_of_the_open_ones():
    P, _names = fixture_problem(tickets=30)
    avg, ev = straight_value(P, 30, 0, 0, 0)
    for b in P.rare_banners:
        if P.live[b.event_id][0]:
            assert straight_value_on(P, b, 30) <= avg + 1e-9
    assert straight_value(P, 0, 0, 0, 0) == (0.0, "")


def straight_value_on(P, b, tickets):
    from bcplanner.metrics import roll_chances
    return sum(P.value_of(c) * (1 - (1 - ch) ** tickets) for c, ch in roll_chances(b).items() if c in P.unit_index)


def test_metrics_and_text_carry_the_factor():
    P, names = fixture_problem(tickets=20, cat_food=1500)
    ev = next(b.event_id for b in P.rare_banners if P.live[b.event_id][0] and b.offers_eleven)
    rep = replay(P, [(SINGLE, ev)] * 20 + [(ELEVEN, ev)])
    m = compute(P, rep)
    assert abs(m.new_value - sum(P.value_of(c) for c in rep.gained)) < 1e-12
    assert m.straight_value > 0 and abs(m.improvement - m.new_value / m.straight_value) < 1e-12
    assert f"Improvement ×{m.improvement:.2f}" in plan_text(P, rep, names, title="Test")
    assert compute(P, replay(P, [])).improvement == 0.0

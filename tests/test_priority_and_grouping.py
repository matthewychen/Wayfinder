import random

from bcplanner.actions import CLOCK, SINGLE
from bcplanner.priority import apply_priorities
from bcplanner.replay import replay
from bcplanner.report import rows_for
from bcplanner.search import search
from bcplanner.sim import single
from helpers import fixture_problem
from test_search_small import make_problem


def test_consecutive_singles_are_one_entry():
    prob, names = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0)
    b = prob.rare_banners[0].event_id
    rep = replay(prob, [(SINGLE, b), (SINGLE, b), (SINGLE, b)])
    rows = rows_for(prob, rep, names)
    actions = [r for r in rows if r.kind == "action"]
    assert len(actions) == 1 and actions[0].action.startswith("3 single draws") and actions[0].step == "1-3"
    assert sum(1 for r in rows if r.kind == "roll") == 3
    assert sum(1 for r in rows if r.kind == "checkpoint") == 1
    # a different banner in between breaks the group
    other = prob.rare_banners[1].event_id
    rep = replay(prob, [(SINGLE, b), (SINGLE, other), (SINGLE, b)])
    assert sum(1 for r in rows_for(prob, rep, names) if r.kind == "action") == 3


def test_priority_reroutes_singles_without_changing_anything_else():
    rng = random.Random(21)
    problem = make_problem(rng.getrandbits(32), rng, tickets=5, cat_food=0, plats=0, legends=0)
    res = search(problem, beam=None)
    best = res.best_value()
    actions = res.plan_actions(best)
    base = replay(problem, actions)
    # want copies of every unit the *other* banners would give at the plan's single offsets
    wanted = set()
    for st in base.steps:
        if st.action[0] != SINGLE:
            continue
        last_before = base.steps[st.index - 2].last_after if st.index > 1 else problem.last_id
        for b in problem.rare_banners:
            if b.event_id != st.action[1] and problem.banner_live(b.event_id, st.day_offset):
                wanted.add(single(problem.tables, b, st.offset_before, last_before).cat_id)
    problem.priority = frozenset(wanted)
    new_actions, changed = apply_priorities(problem, actions)
    rep = replay(problem, new_actions)
    assert rep.problems == []
    assert rep.value >= base.value - 1e-9
    assert set(base.gained) <= set(rep.gained)
    assert (rep.tickets, rep.cf_units, rep.plats, rep.legends) == (base.tickets, base.cf_units, base.plats, base.legends)
    assert rep.end_offset == base.end_offset
    for k in changed:
        st = next(s for s in rep.steps if s.action[0] == SINGLE and s.offset_before == k)
        assert st.rolls[0].cat_id in wanted
    # every other roll is identical
    a = [(rv.source, rv.offset_before, rv.cat_id) for s in base.steps for rv in s.rolls if rv.offset_before not in changed]
    b = [(rv.source, rv.offset_before, rv.cat_id) for s in rep.steps for rv in s.rolls if rv.offset_before not in changed]
    assert a == b
    # the report marks exactly the re-routed rolls as switched
    rows = rows_for(problem, rep, {}, None, changed)
    switched_rolls = [r for r in rows if r.kind == "roll" and r.switched]
    assert len(switched_rolls) == len(changed)
    assert all(r.wanted for r in switched_rolls)


def test_priority_does_nothing_when_empty_and_never_adds_clocks_without_toggle():
    rng = random.Random(22)
    problem = make_problem(rng.getrandbits(32), rng, tickets=4, cat_food=0, plats=0, legends=0)
    res = search(problem, beam=None)
    actions = res.plan_actions(res.best_value())
    assert apply_priorities(problem, actions) == (actions, [])
    problem.priority = frozenset(range(10, 30))
    problem.priority_allow_skip = False
    new_actions, _ = apply_priorities(problem, actions)
    assert sum(1 for a in new_actions if a[0] == CLOCK) == sum(1 for a in actions if a[0] == CLOCK)

"""Replay, metrics and report on the saved live banners."""

from datetime import date

from bcplanner.metrics import compute
from bcplanner.replay import replay
from bcplanner.report import rows_for, to_csv, to_markdown
from bcplanner.search import search
from helpers import fixture_problem


def test_best_plan_replays_and_reports():
    prob, names = fixture_problem(tickets=12, cat_food=3000, plats=2, legends=1)
    res = search(prob, beam=4)
    best = res.best_value()
    actions = res.plan_actions(best)
    rep = replay(prob, actions)
    assert rep.problems == []
    assert abs(rep.value - best.value) < 1e-9
    m = compute(prob, rep)
    assert m.value == rep.value
    assert m.tickets <= 12 and m.cat_food <= 3000 and m.plats <= 2 and m.legends <= 1
    rows = rows_for(prob, rep, names)
    # every roll is listed, rares included
    assert sum(1 for r in rows if r.kind == "roll") == m.rolls
    assert any(r.kind == "roll" and r.rarity == "Rare" for r in rows)
    # highlights carry through to the exports
    md = to_markdown(prob, rep, m, names, "t")
    assert "NEW " in md and "bc.godfat.org/?seed=" in md
    csv_text = to_csv(prob, rep, names)
    assert csv_text.count("\n") >= m.rolls


def test_legend_rule_forces_ticket_on_new_legend_slot():
    # Old rule (legend_substitute_only off): with a legend ticket and nothing owned, the first legend
    # slot on the way must be taken.
    prob, names = fixture_problem(tickets=6, cat_food=0, plats=0, legends=1, legend_substitute_only=False)
    res = search(prob, beam=4)
    best = res.best_value()
    rep = replay(prob, res.plan_actions(best))
    legend_rolls = [rv for st in rep.steps for rv in st.rolls if rv.source == "legend"]
    assert len(legend_rolls) == 1 and legend_rolls[0].rarity == "legend" and legend_rolls[0].new
    m = compute(prob, rep)
    assert m.legend_slots_used == 1 and m.legend_slots_passed == 0
    # Current rule: with nothing owned every legend slot also holds a new uber on the open banners, so the
    # ticket is never allowed and the best plan keeps it; no plan passes an allowed slot either.
    prob2, _ = fixture_problem(tickets=6, cat_food=0, plats=0, legends=1)
    res2 = search(prob2, beam=4)
    rep2 = replay(prob2, res2.plan_actions(res2.best_value()))
    assert not [rv for st in rep2.steps for rv in st.rolls if rv.source == "legend"]
    assert not rep2.problems and compute(prob2, rep2).legend_slots_passed == 0


def test_replay_flags_illegal_plans():
    prob, names = fixture_problem(tickets=1, cat_food=0, plats=0, legends=0)
    rare = next(b for b in prob.rare_banners)
    rep = replay(prob, [("single", rare.event_id), ("single", rare.event_id)])
    assert any("no rare tickets left" in p for p in rep.problems)
    rep = replay(prob, [("clock", "tomorrow")])
    assert any("does not end" in p for p in rep.problems)


def test_plan_text_lists_every_group_and_every_unit():
    from bcplanner.report import plan_text
    from bcplanner.actions import ELEVEN, SINGLE
    prob, names = fixture_problem(tickets=6, cat_food=1500, plats=0, legends=0)
    res = search(prob, beam=4)
    best = max(res.candidates(), key=lambda lab: (lab.c, lab.t))      # a plan with the 11-draw and singles
    rep = replay(prob, res.plan_actions(best))
    text = plan_text(prob, rep, names, title="Test plan")
    lines = text.splitlines()
    assert lines[0].startswith("Test plan:") and lines[-1] == "* = new to you"
    body = [ln for ln in lines[1:-2]]
    assert any(ln.split(". ", 1)[1].startswith("11-draw on") for ln in body)
    singles = sum(1 for st in rep.steps if st.action[0] == SINGLE)
    pulled = sum(int(ln.split("Pull ")[1].split("x")[0]) for ln in body if ". Pull " in ln)
    assert pulled == singles
    for st in rep.steps:
        for rv in st.rolls:
            assert names[rv.cat_id] in text
    assert text.count("*") - 1 == len(rep.gained)                    # one star per new unit, plus the legend line
    assert "(guaranteed)" in text
    assert lines[-2].startswith("Stop at ")

"""Uber priority list: export/import kind and the platinum position table."""

from datetime import date

from bcplanner.options import platinum_positions
from bcplanner.ownedstore import export_text, import_text
from bcplanner.search import search
from bcplanner.session import make_plan
from helpers import fixture_problem


def test_uber_priority_export_round_trips_with_its_own_header():
    names = {35: "Nekoluga", 687: "Goddess of Light Sirius"}
    text = export_text([35, 687], names, "15.6", date(2026, 9, 14), kind="UBERS")
    assert text.startswith("BCPLANNER-UBERS v1")
    res = import_text(text, None, names, "15.6")
    assert res.kind == "UBERS" and res.ids == [35, 687]
    other = import_text(export_text([35], names, "15.6", kind="WANTED"), None, names, "15.6")
    assert other.kind == "WANTED"


def test_platinum_positions_put_priority_and_new_ubers_first():
    prob, names = fixture_problem(tickets=6, cat_food=1500, plats=1, legends=0)
    res = search(prob, beam=4)
    plan = make_plan(prob, res, res.best_value(), "t")
    positions = platinum_positions(prob, plan, priority=set())
    assert positions and positions[0].offset >= 0
    # nothing owned in the fixture problem: every uber is new; ubers the plan gets anyway sink, then position order
    assert all(x.new for x in positions)
    keys = [(x.gained_in_plan, x.offset) for x in positions]
    assert keys == sorted(keys)
    # the position where the plan's first step starts is marked with that step
    first = min(positions, key=lambda x: x.offset)
    assert first.step == 1
    # a priority uber jumps to the top
    want = positions[5].cat_id
    ranked = platinum_positions(prob, plan, priority={want})
    assert ranked[0].cat_id == want and ranked[0].priority
    assert ranked[0].label.endswith(("A", "B"))

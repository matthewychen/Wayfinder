from datetime import date

from bcplanner.actions import ELEVEN, PLAT, SINGLE
from bcplanner.session import make_plan
from bcplanner.search import search
from bcplanner.tracks_view import cell_colours, plan_overlay, render_tracks_html, score_label
from helpers import fixture_problem


def test_score_bands_match_the_site():
    assert score_label(0) == "rare" and score_label(6469) == "rare"
    assert score_label(6470) == "supa_fest" and score_label(6969) == "supa_fest"
    assert score_label(6970) == "supa" and score_label(9069) == "supa"
    assert score_label(9070) == "uber_fest" and score_label(9469) == "uber_fest"
    assert score_label(9470) == "uber" and score_label(9939) == "uber"
    assert score_label(9940) == "legend_fest" and score_label(9970) == "legend"


def test_owned_keeps_original_colour_on_the_left():
    assert cell_colours(5, 9500, owned={5}, found=set(), exclusive=set()) == ("owned", "uber")
    assert cell_colours(5, 9500, owned=set(), found=set(), exclusive=set()) == ("uber", "uber")
    assert cell_colours(5, 100, owned=set(), found={5}, exclusive=set()) == ("found", "found")


def test_overlay_marks_every_consumed_position_and_renders():
    prob, names = fixture_problem(today=date(2026, 9, 13), tickets=6, cat_food=1500, plats=1, legends=0)
    res = search(prob, beam=4)
    plan = make_plan(prob, res, res.best_value(), "t")
    banner = prob.rare_banners[0]
    ov = plan_overlay(plan, banner.event_id, {b.event_id: b.event_id[-4:] for b in prob.rare_banners})
    singles = sum(1 for st in plan.replay.steps if st.action[0] in (SINGLE, PLAT))
    eleven_cells = sum(len(st.rolls) for st in plan.replay.steps if st.action[0] == ELEVEN)
    assert sum(1 for c in ov.cells.values() if c[0] == "picked") == singles
    assert sum(1 for c in ov.cells.values() if c[0] == "picked_consecutively") == eleven_cells
    assert ov.next_label is not None
    html = render_tracks_html(prob.tables, banner, prob.last_id, 30, names, owned=set(), found=set(), exclusive=set(),
                              overlay=ov)
    assert "<table>" in html and "next_position" in html and "picked" in html
    assert html.count("<tr>") == 30 + 1

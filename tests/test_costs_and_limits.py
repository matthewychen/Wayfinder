"""Per-ticket cost, the legend pass band, the no-rush legend value and the exact-mode time limit."""

import random
import time

from bcplanner.actions import SINGLE
from bcplanner.future import FutureModel, FutureValue
from bcplanner.replay import replay
from bcplanner.search import search, search_exact
from helpers import fixture_problem
from test_search_small import make_problem


def test_every_rare_ticket_costs_its_price():
    rng = random.Random(3)
    problem = make_problem(rng.getrandbits(32), rng, tickets=2, cat_food=0, plats=0, legends=0, pass_penalties={})
    problem.ticket_cost = 0.5
    b = problem.rare_banners[0]
    rep = replay(problem, [(SINGLE, b.event_id), (SINGLE, b.event_id)])
    gained = sum(problem.value_of(rv.cat_id) for st in rep.steps for rv in st.rolls if rv.new)
    dupes = sum(problem.dupe_value(rv.rarity) for st in rep.steps for rv in st.rolls
                if not rv.new and (rv.cat_id in problem.owned or rv.rarity in ("uber", "legend")) and rv.cat_id > 0)
    assert abs(rep.value - (gained + dupes - 2 * 0.5)) < 1e-9
    res = search(problem, beam=None)
    assert abs(res.best_value().value - max(0.0, rep.value, *(lab.value for lab in res.labels))) < 1e-9


def test_legend_slots_have_their_own_pass_band():
    prob, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0)
    bands = {prob.slot_band(k) for k in range(0, 400)}
    assert "legend" in bands and "uber" in bands
    prob.pass_penalties = {"uber": 0.0, "uber_fest": 0.0, "legend": 5.0}
    k = next(k for k in range(0, 400) if prob.slot_band(k) == "legend")
    assert prob.pass_penalty(k - 1, k + 1, (k - 1,)) == 5.0        # a roll before it goes past the legend slot


def test_a_legend_that_stays_available_is_worth_the_same_later():
    prob, _ = fixture_problem(tickets=6, cat_food=1500, plats=0, legends=0)
    fv = FutureValue(prob, FutureModel(mode="seed", confidence=1.0, flat_per_draw=0.0,
                                       p_new={"supa": 0.0, "uber": 0.0, "legend": 0.0}))
    legend_slots = [k for k in range(0, 200) if fv.band(k) == "legend"]
    assert legend_slots
    k = legend_slots[0]
    # with a 0% chance of a new legend the typical-banner value is 0; the no-rush rule restores the
    # value of a legend an open, continuing banner holds there
    assert fv.gain(k) == fv.legend_now(k)
    assert fv.legend_now(k) >= 0.0


def test_exact_mode_keeps_the_beam_result_when_the_proof_runs_out_of_time():
    rng = random.Random(9)
    problem = make_problem(rng.getrandbits(32), rng, tickets=4, cat_food=3000, plats=1, legends=1)
    t0 = time.perf_counter()
    res = search_exact(problem, beam_first=2, time_limit=0.0)
    assert time.perf_counter() - t0 < 5.0
    assert res.best_value() is not None
    assert res.stats.timed_out or res.stats.proven_optimal
    done = search_exact(problem, beam_first=30)
    assert done.stats.proven_optimal


def _uber_slot_with_a_new_uber(prob):
    """An uber-band position where an open rare banner gives an unowned uber, with that uber's bit."""
    for k in range(0, 400):
        if prob.slot_band(k) != "uber":
            continue
        for b in prob.rare_banners:
            rarity, _, cid = prob.tables.cat_at(b, k)
            if rarity == "uber" and prob.bit(cid):
                return k, cid
    raise AssertionError("no uber slot with a new uber in the fixtures")


def test_passing_a_slot_costs_the_band_penalty_only_while_the_uber_there_is_new():
    prob, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0,
                              pass_penalties={"uber": 0.8, "uber_fest": 0.2, "legend": 5.0},
                              dupe_values={"supa": 0.05, "uber": 0.2, "legend": 0.0})
    k, cid = _uber_slot_with_a_new_uber(prob)
    assert prob.passed_new_top(k)
    assert prob.pass_cost(k) == 0.8                                  # a new uber sits there on an open banner
    assert prob.pass_penalty(k - 1, k + 1, (k - 1,)) == 0.8
    # once every new uber at that slot has been gained earlier in the plan, only a repeat is lost
    gained = 0
    for b in prob.rare_banners:
        rarity, _, c = prob.tables.cat_at(b, k)
        if rarity == "uber":
            gained |= prob.bit(c)
    assert not prob.passed_new_top(k, gained)
    assert prob.pass_cost(k, gained) == 0.2
    assert prob.pass_penalty(k - 1, k + 1, (k - 1,), gained) == 0.2
    # owning them all from the start gives the same repeat price, and a zero repeat value makes passing free
    ubers = {c for b in prob.rare_banners for c in b.pools.get("uber", [])}
    owned, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0, owned=ubers,
                               pass_penalties={"uber": 0.8, "uber_fest": 0.2, "legend": 5.0},
                               dupe_values={"supa": 0.05, "uber": 0.2, "legend": 0.0})
    assert owned.pass_cost(k) == 0.2
    free, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0, owned=ubers,
                              pass_penalties={"uber": 0.8, "uber_fest": 0.2, "legend": 5.0},
                              dupe_values={"supa": 0.0, "uber": 0.0, "legend": 0.0})
    assert free.pass_cost(k) == 0.0


def test_replay_marks_repeat_slots_and_agrees_with_the_search():
    ubers = set()
    prob0, _ = fixture_problem(tickets=6, cat_food=1500, plats=0, legends=0)
    for b in prob0.rare_banners:
        ubers |= set(b.pools.get("uber", []))
    prob, _ = fixture_problem(tickets=6, cat_food=1500, plats=0, legends=0, owned=ubers,
                              pass_penalties={"uber": 0.8, "uber_fest": 0.2, "legend": 5.0},
                              dupe_values={"supa": 0.05, "uber": 0.2, "legend": 0.0})
    res = search(prob, beam=None)
    for lab in res.candidates():
        rep = replay(prob, res.plan_actions(lab))
        assert abs(rep.value - lab.value) < 1e-9
        for st in rep.steps:
            for _p, band, kind in st.passed:
                assert kind != "new"                  # every uber is owned, so nothing passed is new
                if band == "uber":
                    assert kind == "repeat"


def test_clock_changes_are_folded_into_the_rolls_that_need_them():
    """No label is a bare clock change: a roll on a banner only the other day has carries the change as
    its parent, and the replay still sees the clock actions in the plan."""
    from bcplanner.actions import CLOCK
    rng = random.Random(11)
    problem = make_problem(rng.getrandbits(32), rng, tickets=3, cat_food=1500)
    assert problem.tomorrow_adds_banners
    res = search(problem, beam=None)
    assert all(lab.action is None or lab.action[0] != CLOCK for lab in res.labels)
    switched = [lab for lab in res.candidates() if lab.skips]
    assert switched
    for lab in switched[:20]:
        acts = res.plan_actions(lab)
        assert any(a[0] == CLOCK for a in acts)
        rep = replay(problem, acts)
        assert not rep.problems and abs(rep.value - lab.value) < 1e-9


def test_options_rows_follow_the_cat_food_amounts_plans_spend():
    from bcplanner.options import spending_options
    prob, _ = fixture_problem(tickets=6, cat_food=3750, plats=0, legends=0, discount_first_draw=True)
    res = search(prob, beam=12)
    rows = spending_options(prob, res)
    levels = [o.plan.replay.cf_units for o in rows]
    assert levels == sorted({lab.c for lab in res.candidates()})      # 0, 1, 3, 5 with a discounted first draw
    assert 5 in levels and 2 not in levels
    assert rows[-1].title.startswith("3 11-draws")


def test_a_new_rare_is_worth_a_new_super_and_a_repeat_rare_nothing():
    from bcplanner.future import estimate_p_new
    prob, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0)
    rares = {c for b in prob.rare_banners for c in b.pools.get("rare", [])}
    assert rares and all(prob.value_of(c) == prob.weights["supa"] for c in rares)
    assert all(prob.bit(c) for c in rares)                       # unowned rares are valued units
    assert prob.dupe_value("rare") == 0.0
    cid = next(iter(rares))
    assert prob.gain(cid, "rare", prob.bit(cid)) == (0, 0.0)     # a repeat earns nothing
    p_new = estimate_p_new(prob)
    assert p_new["rare"] == 1.0                                  # nothing owned: every rare is new
    fv = FutureValue(prob, FutureModel(mode="seed", confidence=1.0, flat_per_draw=0.0, p_new=p_new))
    assert abs(fv.expected("rare") - prob.weights["rare"]) < 1e-9
    owned, _ = fixture_problem(tickets=4, cat_food=0, plats=0, legends=0, owned=rares)
    assert all(not owned.bit(c) for c in rares)
    assert estimate_p_new(owned)["rare"] == 0.0


def _legend_case():
    """A toy problem with a legend ticket and a legend slot early on."""
    for seed in range(1, 60):
        rng = random.Random(seed)
        prob = make_problem(rng.getrandbits(32), rng, tickets=6, cat_food=0, plats=0, legends=1)
        prob.owned = frozenset()
        prob.__post_init__()
        slots = [k for k in range(0, 40) if prob.new_legend_at(k, 0)]
        if slots:
            return prob, slots[0]
    raise AssertionError("no toy problem with an early new-legend slot")


def test_legend_ticket_only_where_every_open_banner_repeats_and_the_plan_goes_on():
    from bcplanner.actions import LEGEND
    prob, k = _legend_case()
    # some open banner has a new uber at the slot (nothing is owned): the ticket is not allowed there
    assert not prob.repeats_everywhere(k, 0)
    assert prob.legend_allowed(k, 0) == 0 and prob.legend_mandatory(k, 0, 0) == 0
    res = search(prob, beam=None)
    assert all(a[0] != LEGEND for lab in res.candidates() for a in res.plan_actions(lab))
    # own every uber and legend on the rare banners: the slot now only repeats, so the ticket is allowed
    tops = {c for b in prob.rare_banners for r in ("uber", "legend") for c in b.pools.get(r, [])}
    tops -= set(prob.legend.pools.get("legend", []))            # keep the legend itself new
    rng = random.Random(3)
    owned_prob = make_problem(prob.tables.url_seed, rng, tickets=6, cat_food=0, plats=0, legends=1)
    owned_prob.owned = frozenset(tops)
    owned_prob.__post_init__()
    if owned_prob.legend_allowed(k, 0):
        assert owned_prob.repeats_everywhere(k, 0)
        res2 = search(owned_prob, beam=None)
        used = [lab for lab in res2.candidates() if any(a[0] == LEGEND for a in res2.plan_actions(lab))]
        for lab in used:
            acts = res2.plan_actions(lab)
            assert acts[-1][0] != LEGEND                          # never the last action
            rep = replay(owned_prob, acts)
            assert not rep.problems and abs(rep.value - lab.value) < 1e-9
        # a plan that ends on the legend ticket is rejected by the replay
        for lab in res2.labels:
            if lab.action is not None and lab.action[0] == LEGEND:
                rep = replay(owned_prob, lab.actions())
                assert any("legend ticket" in q for q in rep.problems)
                break
    # switching the rule off restores the old behaviour: a new legend is enough
    prob.legend_substitute_only = False
    assert prob.legend_allowed(k, 0) == prob.new_legend_at(k, 0)


def test_fetch_falls_back_to_a_saved_copy_when_the_site_fails(tmp_path, monkeypatch):
    import os
    import pytest
    from bcplanner import scrape

    def boom(url, attempts=2):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(scrape, "_get", boom)
    f = tmp_path / "details_x.html"
    with pytest.raises(TimeoutError):
        scrape.fetch_cached("https://example.invalid/", f)          # nothing saved: the error surfaces
    f.write_text("saved page", encoding="utf-8")
    old = time.time() - 30 * 24 * 3600
    os.utime(f, (old, old))
    notes = []
    assert scrape.fetch_cached("https://example.invalid/", f, notes=notes) == "saved page"
    assert notes and "did not answer" in notes[0] and "30.0 days" in notes[0]
    monkeypatch.setattr(scrape, "_get", lambda url, attempts=2: "fresh page")
    assert scrape.fetch_cached("https://example.invalid/", f, refresh=True) == "fresh page"
    assert f.read_text(encoding="utf-8") == "fresh page"

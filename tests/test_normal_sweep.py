"""The lucky-ticket sweep: what more lucky tickets add for a fixed number of cat tickets, and how many to want."""

from nsplanner import sweep
from nsplanner.cli import settings_from
from nsplanner.plan import plan

SEED, LAST = 4072625662, "Dark Catseye"


def test_sweep_never_gets_worse_with_more_lucky_tickets_and_settles():
    st = settings_from(60, 0, 5.0, False, 1.0, 0.0)
    pts = sweep.sweep(SEED, LAST, st, workers=1)
    assert [p.lucky for p in pts] == sweep.lucky_counts(60) == [round(r * 60) for r in sweep.RATIOS]
    for a, b in zip(pts, pts[1:]):
        assert b.score >= a.score - 1e-9                     # a plan with fewer lucky tickets is still allowed
        assert a.lucky_used <= a.lucky and a.cat_used <= 60
    st6 = settings_from(60, 6, 5.0, False, 1.0, 0.0)
    now = sweep.from_result(plan(SEED, LAST, st6), st6)
    assert now.lucky == 6 and now.cat == 60
    adv = sweep.advise(pts, now)
    assert adv.best.score == max(p.score for p in pts)
    assert adv.want == adv.best.lucky_used and adv.per_cat == adv.want / 60
    assert adv.extra_orbs == max(0, adv.best.orbs - now.orbs)
    assert abs(adv.over_baseline - (now.orbs - 9 / 19 * now.cat_used)) < 1e-9
    assert abs(now.factor - now.orbs / now.cat_used / (9 / 19)) < 1e-12


def test_sweep_in_processes_matches_one_at_a_time():
    st = settings_from(30, 0, 5.0, False, 1.0, 0.0)
    assert sweep.sweep(SEED, LAST, st, workers=2) == sweep.sweep(SEED, LAST, st, workers=1)


def test_advice_when_lucky_tickets_are_plentiful():
    st = settings_from(40, 0, 5.0, False, 1.0, 0.0)
    pts = sweep.sweep(SEED, LAST, st, workers=1)
    st200 = settings_from(40, 200, 5.0, False, 1.0, 0.0)
    rich = sweep.from_result(plan(SEED, LAST, st200), st200)
    adv = sweep.advise(pts, rich)
    assert adv.extra_orbs == 0 and adv.extra_lucky == 0
    assert rich.lucky > adv.want                             # the extra ones would go unused

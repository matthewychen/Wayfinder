"""The planner against brute force: every pull sequence within small ticket budgets."""

import random

import pytest

from nsplanner.banners import BANNERS, DARK, DARK_BANNER
from nsplanner.plan import Settings, plan, replay
from nsplanner.sim import Seeds, canonical_at


def brute_best(seed, last, st):
    caps = dict(st.tickets)
    best = 0.0

    def go(codes, used):
        nonlocal best
        _rolls, score, *_rest = replay(seed, last, codes, st)
        best = max(best, score)
        for c in st.banners:
            cur = st.currency[c]
            if used.get(cur, 0) < caps.get(cur, 0):
                used[cur] = used.get(cur, 0) + 1
                go(codes + [c], used)
                used[cur] -= 1

    go([], {})
    return best


def seeds_with_early_darks(n, within=14, rng_seed=5):
    rng = random.Random(rng_seed)
    out = []
    while len(out) < n:
        s = rng.getrandbits(32)
        S = Seeds(s)
        if any(canonical_at(S, BANNERS[DARK_BANNER], q)[1] == DARK for q in range(within)):
            out.append(s)
    return out


CASES = [(4072625662, "Dark Catseye")] + [(s, "") for s in seeds_with_early_darks(4)] + \
        [(random.Random(9).getrandbits(32), "10K XP"), (123456789, "Speed Up")]


@pytest.mark.parametrize("seed,last", CASES)
@pytest.mark.parametrize("dark_value", [0.0, 3.0, 20.0])
def test_plan_matches_brute_force(seed, last, dark_value):
    st = Settings(tickets={"cat": 5, "lucky": 3}, dark_value=dark_value)
    res = plan(seed, last, st)
    assert abs(res.score - brute_best(seed, last, st)) < 1e-9
    rolls, score, *_rest = replay(seed, last, [r.code for r in res.rolls], st)
    assert abs(score - res.score) < 1e-9
    assert res.used.get("cat", 0) <= 5 and res.used.get("lucky", 0) <= 3


def test_a_dark_catseye_on_the_next_catseye_pull_is_taken():
    seed = seeds_with_early_darks(1, within=1, rng_seed=3)[0]
    assert canonical_at(Seeds(seed), BANNERS[DARK_BANNER], 0)[1] == DARK
    res = plan(seed, "", Settings(tickets={"cat": 6, "lucky": 2}))
    assert res.rolls[0].code == DARK_BANNER and res.rolls[0].name == DARK
    assert not res.missed


def test_unreachable_dark_catseyes_cost_nothing():
    """A Dark Catseye at 1B can never be reached from 1A (every pull moves at least two steps)."""
    from nsplanner.plan import World
    rng = random.Random(21)
    while True:
        seed = rng.getrandbits(32)
        if canonical_at(Seeds(seed), BANNERS[DARK_BANNER], 1)[1] == DARK:
            break
    w = World(seed, ("np", "lt", "ce"))
    assert not w.reachable(1, 0, w.canon(0, ""))
    res = plan(seed, "", Settings(tickets={"cat": 4, "lucky": 1}, dark_value=1000.0))
    assert res.rolls and "1B" in res.out_of_reach and not res.missed      # no stall, no penalty


def test_reachability_matches_a_forward_search():
    from nsplanner.plan import World
    for seed in seeds_with_early_darks(5, within=30, rng_seed=8):
        w = World(seed, ("np", "lt", "ce"), window=None)
        q = next(x for x in range(30) if w.is_dark(x))
        for p in range(0, q + 1):
            for last in w.lasts(p) | {""}:
                frontier, found, seen = [(p, last)], False, set()
                while frontier:
                    pp, ll = frontier.pop()
                    if pp == q:
                        found = True
                        break
                    if pp > q or (pp, ll) in seen:
                        continue
                    seen.add((pp, ll))
                    for c in w.codes:
                        r = w.roll(c, pp, ll)
                        frontier.append((r.next, w.canon(r.next, r.name)))
                assert w.reachable(q, p, last) == found, (seed, q, p, last)


def test_catfruit_only_when_switched_on():
    st = Settings(tickets={"cat": 6, "lucky": 0})
    res = plan(4072625662, "Dark Catseye", st)
    assert all(r.code in ("np", "ce") for r in res.rolls)
    st2 = Settings(tickets={"cat": 6, "lucky": 0}, banners=("np", "lt", "ce", "cf"),
                   weights={"Blue Catfruit": 1.0})
    res2 = plan(4072625662, "Dark Catseye", st2)
    assert any(r.code == "cf" for r in res2.rolls)


def test_grid_search_matches_the_reference_search():
    from nsplanner.plan import plan_slow
    rng = random.Random(4)
    for _ in range(30):
        seed = rng.getrandbits(32)
        st = Settings(tickets={"cat": rng.randint(0, 40), "lucky": rng.randint(0, 15)},
                      dark_value=rng.choice([0.0, 3.0, 10.0, 50.0]))
        if rng.random() < 0.3:
            st.banners = ("np", "lt", "ce", "cf")
        last = rng.choice(["", "10K XP", "30K XP", "Speed Up", "Cat", "Research", "Dark Catseye"])
        fast, slow = plan(seed, last, st), plan_slow(seed, last, st)
        assert abs(fast.score - slow.score) < 1e-9
        assert fast.used.get("lucky", 0) == slow.used.get("lucky", 0)
        assert len(fast.rolls) == len(slow.rolls)
        assert abs(fast.search_score - fast.score) < 1e-9          # the walk-back reproduces the search's value
        assert fast.used.get("cat", 0) <= st.tickets["cat"] and fast.used.get("lucky", 0) <= st.tickets["lucky"]


def test_large_budgets_stay_fast():
    import time
    t0 = time.perf_counter()
    res = plan(4072625662, "Dark Catseye", Settings(tickets={"cat": 1000, "lucky": 100}, dark_value=10.0))
    assert time.perf_counter() - t0 < 30            # was minutes and gigabytes with the per-state search
    assert res.used["cat"] == 1000 and abs(res.search_score - res.score) < 1e-9


def test_plan_is_optimal_against_an_independent_solver():
    """Same score, same (fewest) lucky tickets and pulls. normal_reference shares only the roll simulation: its own state space, raw last results, and the Dark
    Catseye penalty scored from the end state instead of pull by pull."""
    from normal_reference import score_path, solve
    from nsplanner.cli import settings_from
    rng = random.Random(7)
    cases = [(4072625662, "Dark Catseye", 300, 30, 10.0, False)]      # his run
    for _ in range(12):
        cases.append((rng.getrandbits(32), rng.choice(["", "Cat", "Dark Catseye", "Research", "10K XP"]),
                      rng.choice([10, 25, 60, 120]), rng.choice([0, 3, 10, 20]),
                      rng.choice([0.0, 2.0, 10.0, 50.0]), rng.random() < 0.3))
    for seed, last, cat, lucky, dark, cf in cases:
        st = settings_from(cat, lucky, dark, cf, 1.0, 1.0)
        res = plan(seed, last, st)
        best, spare, pulls = solve(seed, last, cat, lucky, list(st.banners), st.weights, dark)
        assert abs(res.score - best) < 1e-9, (seed, cat, lucky, dark)
        assert res.used.get("lucky", 0) == spare, (seed, cat, lucky, dark)   # fewest lucky tickets among the best
        assert len(res.rolls) == pulls                                   # then fewest pulls
        assert abs(score_path(seed, last, [r.code for r in res.rolls], list(st.banners), st.weights, dark)
                   - res.score) < 1e-9


def test_every_capsule_open_at_once():
    """Six capsules: up to 7 last results x 7 last capsules per position, all within the choice codes."""
    from normal_reference import solve
    from nsplanner.plan import default_weights
    rng = random.Random(9)
    for _ in range(3):
        seed = rng.getrandbits(32)
        st = Settings(tickets={"cat": 60, "lucky": 15}, banners=("n", "np", "cf", "ce", "lt", "ltg"),
                      weights=default_weights(), dark_value=10.0)
        res = plan(seed, "", st)
        assert abs(res.score - solve(seed, "", 60, 15, list(st.banners), st.weights, 10.0)[0]) < 1e-9

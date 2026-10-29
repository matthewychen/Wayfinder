"""The operation list: runs on one capsule become 10x pulls plus singles, in order, covering every roll."""

from nsplanner.cli import parse_url, settings_from
from nsplanner.plan import plan
from nsplanner.report import operations, plan_text, site_url
from nsplanner.sim import Seeds, roll
from nsplanner.banners import BANNERS

URL = ("https://ampuri.github.io/bc-normal-seed-tracking/?seed=4072625662&banners=ce%2Ccf%2Clt%2Cnp"
       "&lastCat=Dark+Catseye&selected=c%2C2704736165%2Cnp")


def test_url_parsing():
    assert parse_url(URL) == (4072625662, "Dark Catseye")


def test_operations_cover_every_roll_in_order():
    seed, last = parse_url(URL)
    st = settings_from(60, 15, 20.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    ops = operations(res.rolls)
    flat = [r for _kind, rs in ops for r in rs]
    assert flat == res.rolls
    for kind, rs in ops:
        assert len({r.code for r in rs}) == 1
        assert (kind == "10x") == (len(rs) == 10)
        assert kind in ("10x", "once")
    # following the operations from the URL's state reproduces every result
    S, p, cur = Seeds(seed), 0, last
    for r in flat:
        again = roll(S, BANNERS[r.code], p, cur)
        assert again.name == r.name and again.next == r.next
        p, cur = again.next, again.name
    text = plan_text(res, st)
    assert text.count("Pull 10x") == sum(1 for k, _ in ops if k == "10x")
    assert site_url(res.end_seed, res.end_last) in text


def test_a_run_of_23_is_two_10x_and_three_singles():
    seed, last = parse_url(URL)
    st = settings_from(23, 0, 0.0, False, 1.0, 1.0)
    st.banners = ("np",)
    res = plan(seed, last, st)
    assert len(res.rolls) == 23
    assert [(k, len(rs)) for k, rs in operations(res.rolls)] == [("10x", 10), ("10x", 10), ("once", 3)]


def test_icon_view_shows_every_pull_once_and_embeds_each_picture_once():
    import re
    from nsplanner.visual import plan_html
    seed, last = parse_url(URL)
    st = settings_from(60, 15, 20.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    h = plan_html(res, st)
    ops = operations(res.rolls)
    assert h.count('class="row"') == len(ops)
    assert h.count('class="it ') == len(res.rolls)                  # one result icon per pull
    counted = sum(1 for r in res.rolls if r.name == "Dark Catseye" or st.weights.get(r.name, 0) > 0)
    assert sum(int(g) for g in re.findall(r'class="gain">\+(\d+)<', h)) == counted
    assert h.count('class="chip"') == 0                             # every item has a picture
    pictures = re.findall(r"\.nsp \.(i-[a-z0-9_]+)\{background-image", h)
    assert len(pictures) == len(set(pictures))
    assert h.count('class="pill ten">10<') == sum(1 for k, _ in ops if k == "10x")


def test_progress_after_any_pull_continues_the_same_plan():
    """Saving progress after pull k: from the saved seed and last result, the rest of the plan comes out the same."""
    from nsplanner.report import progress_after
    seed, last = parse_url(URL)
    st = settings_from(60, 15, 20.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    for k in (0, 5, len(res.rolls) // 2, len(res.rolls) - 2):
        pr = progress_after(seed, res, st, k)
        assert parse_url(pr.url) == (pr.seed, pr.last)
        rest = res.rolls[k + 1:]
        S, p, cur = Seeds(pr.seed), 0, pr.last
        for r in rest:
            again = roll(S, BANNERS[r.code], p, cur)
            assert again.name == r.name and again.rerolls == r.rerolls
            p, cur = again.next, again.name
        used_cat = sum(1 for r in res.rolls[:k + 1] if st.currency[r.code] == "cat")
        assert pr.left["cat"] == 60 - used_cat and pr.left["lucky"] == 15 - (k + 1 - used_cat)


def test_every_pull_is_clickable_and_10x_pulls_stop_at_their_end():
    import re
    from nsplanner.visual import plan_html
    seed, last = parse_url(URL)
    st = settings_from(60, 15, 20.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    h = plan_html(res, st)
    pairs = [(int(a), int(b)) for a, b in re.findall(r'class="it [a-z]+" data-k="(\d+)" data-stop="(\d+)"', h)]
    assert [k for k, _ in pairs] == list(range(len(res.rolls)))          # every pull, in order
    expected, base = [], 0
    for kind, rs in operations(res.rolls):
        expected += [base + len(rs) - 1] * len(rs) if kind == "10x" else list(range(base, base + len(rs)))
        base += len(rs)
    assert [sp for _, sp in pairs] == expected                           # where a click on that pull stops
    assert len(re.findall(r'class="n" data-stop="\d+"', h)) == len(operations(res.rolls))


def test_straight_rate_is_nine_power_ups_out_of_nineteen():
    import random
    from nsplanner.report import straight_orbs, straight_rate
    assert abs(straight_rate("np") - 9 / 19) < 1e-12
    rng = random.Random(3)
    got = sum(straight_orbs(rng.getrandbits(32), "", 500) for _ in range(120))
    assert abs(got / 60000 - 9 / 19) < 0.01          # re-rolls leave the long-run share alone


def test_improvement_factor():
    from nsplanner.report import improvement, straight_orbs
    seed, last = parse_url(URL)
    st = settings_from(60, 5, 10.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    imp = improvement(seed, last, res, st)
    assert imp.tickets == res.used["cat"]
    assert abs(imp.per_ticket - res.orbs / res.used["cat"]) < 1e-12
    assert abs(imp.factor - imp.per_ticket / (9 / 19)) < 1e-12
    assert abs(imp.this_seed - straight_orbs(seed, last, imp.tickets) / imp.tickets) < 1e-12
    assert res.orbs >= straight_orbs(seed, last, imp.tickets)           # pulling straight is one of the plans
    assert imp.line() in plan_text(res, st, imp=imp)
    assert improvement(seed, last, plan(seed, last, settings_from(0, 5, 10.0, False, 1.0, 1.0)),
                       settings_from(0, 5, 10.0, False, 1.0, 1.0)) is None


def test_rare_tickets_from_blue_orbs():
    from nsplanner.report import ORBS_PER_RARE_TICKET, rare_tickets
    from nsplanner.visual import plan_html
    assert ORBS_PER_RARE_TICKET == 5 and rare_tickets(168) == 33.6
    seed, last = parse_url(URL)
    st = settings_from(40, 5, 10.0, False, 1.0, 1.0)
    res = plan(seed, last, st)
    page = plan_html(res, st)
    assert "Rare tickets at 5 blue orbs each" in page and f"{res.orbs // 5}</span>" in page
    assert f"= {res.orbs // 5} rare tickets" in plan_text(res, st)

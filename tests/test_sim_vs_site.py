"""Golden tests: our simulation must reproduce bc.godfat.org's own tables, cell for cell.

Fixtures are saved Details pages. Each is checked for all 100 rows on both tracks:
seeds, scores, slots, cats, dupe rerolls and their landing labels, guaranteed ubers
and their landing labels, including the guaranteed shown for rerolled cats.
"""

import pytest

from bcplanner.scrape import infer_guaranteed_rolls, page_seed_and_last, parse_details, self_test
from conftest import FIXTURES

FIELDS = ("rarity_seed", "slot_seed", "score", "slot", "cat_id", "rerolled_id", "rerolled_next",
          "guaranteed_id", "guaranteed_next", "rerolled_guaranteed_id", "rerolled_guaranteed_next")

CASES = [
    # (fixture file, event id, expected guaranteed rolls)
    ("details_user_3163852999_1076.html", "2026-09-11_1076", 11),   # your page: dupes at 5A and 14B
    ("details_2026-09-11_1076.html", "2026-09-11_1076", 11),
    ("details_2026-09-11_1002.html", "2026-09-11_1002", 11),        # collab, 1 uber
    ("details_2026-09-11_1059.html", "2026-09-11_1059", 11),        # 0.3% legend rate
    ("details_2026-09-14_991.html", "2026-09-14_991", 11),
    ("details_2026-07-24_1063.html", "2026-07-24_1063", 0),         # platinum
    ("details_2026-07-24_1064.html", "2026-07-24_1064", 0),         # legend banner
]


@pytest.mark.parametrize("fixture,event_id,expected_rolls", CASES)
def test_reproduces_site_table(fixture, event_id, expected_rolls):
    page = (FIXTURES / fixture).read_text(encoding="utf-8")
    banner, names = parse_details(page, event_id)
    assert not banner.validate(), banner.validate()
    rolls = infer_guaranteed_rolls(page, banner)
    assert rolls == expected_rolls
    problems = self_test(page, banner, rolls, rows=100)
    assert problems == [], "\n".join(problems[:40])


def test_user_page_specifics():
    page = (FIXTURES / "details_user_3163852999_1076.html").read_text(encoding="utf-8")
    assert page_seed_and_last(page) == (3163852999, 689)
    banner, names = parse_details(page, "2026-09-11_1076")
    assert banner.rates == (7000, 2500, 500, 0)
    assert len(banner.pool("rare")) == 25 and len(banner.pool("supa")) == 23 and len(banner.pool("uber")) == 7
    assert names[banner.pool("supa")[5]] == "Lifeguard Cats"


def test_platinum_and_legend_share_uber_pool():
    p = (FIXTURES / "details_2026-07-24_1063.html").read_text(encoding="utf-8")
    l = (FIXTURES / "details_2026-07-24_1064.html").read_text(encoding="utf-8")
    plat, _ = parse_details(p, "2026-07-24_1063")
    leg, _ = parse_details(l, "2026-07-24_1064")
    assert plat.kind == "platinum" and leg.kind == "legend"
    assert plat.rates == (0, 0, 10000, 0) and leg.rates == (0, 0, 9500, 500)
    assert plat.pool("uber") == leg.pool("uber")
    assert leg.legend_threshold == 9500 and len(leg.pool("legend")) == 13

"""Shared helpers for tests and scratch runs: build a Problem from saved fixture pages."""
from datetime import date
from pathlib import Path

from bcplanner.model import Banner
from bcplanner.problem import Problem
from bcplanner.scrape import infer_guaranteed_rolls, parse_details
from bcplanner.sim import Tables

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIVE_EVENTS = ["2026-09-11_1002", "2026-09-11_1059", "2026-09-11_1076", "2026-09-14_991",
               "2026-07-24_1063", "2026-07-24_1064"]


def fixture_banners(event_ids=LIVE_EVENTS):
    banners, names = {}, {}
    for ev in event_ids:
        page = (FIXTURES / f"details_{ev}.html").read_text(encoding="utf-8")
        b, n = parse_details(page, ev)
        b.guaranteed_rolls = infer_guaranteed_rolls(page, b)
        banners[ev] = b
        names.update(n)
    return banners, names


def fixture_problem(seed=3163852999, last=689, today=date(2026, 9, 13), owned=(), **kw):
    banners, names = fixture_banners()
    horizon = 2 * kw.get("tickets", 0) + 22 * (kw.get("cat_food", 0) // 1500 + 1) + 2 * kw.get("plats", 0) + 2 * kw.get("legends", 0) + 80
    tables = Tables(seed, horizon)
    prob = Problem(tables=tables, banners=banners, owned=frozenset(owned), today=today, last_id=last, **kw)
    return prob, names

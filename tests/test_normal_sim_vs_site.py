"""The simulation against bc-normal-seed-tracking's own code.

tests/fixtures/site_tables.json was produced by running the site's roll and dupe-display code
(src/utils/seed.tsx and src/RollTable.tsx) for six seeds and every banner; site_banners.json is
the site's banner data. Every cell must match: rarity, unit, re-rolled unit, extra steps, and the
cell a shown dupe jumps to.
"""

import json
from pathlib import Path

import pytest

from nsplanner.banners import BANNERS
from nsplanner.sim import Seeds, canonical_at, label, roll

FIX = Path(__file__).parent / "fixtures" / "normal"
CASES = json.loads((FIX / "site_tables.json").read_text(encoding="utf-8"))


def test_banner_data_matches_the_site():
    site = {b["shortName"]: b for b in json.loads((FIX / "site_banners.json").read_text(encoding="utf-8"))}
    assert set(site) == set(BANNERS)
    for code, b in BANNERS.items():
        s = site[code]
        assert b.name == s["name"]
        assert list(b.cum) == s["rateCumSum"]
        assert [(p.rate, list(p.units), p.reroll) for p in b.pools] == \
               [(p["rate"], p["units"], p["reroll"]) for p in s["pools"]]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"seed{c['seed']}")
def test_every_cell_matches_the_site(case):
    S = Seeds(case["seed"])
    checked = 0
    for code, tracks in case["banners"].items():
        b = BANNERS[code]
        for track, rows in tracks.items():
            for i, row in enumerate(rows):
                p = 2 * i + (0 if track == "A" else 1)
                assert label(p) == row["cell"]
                rarity, name, rerolls_pool = canonical_at(S, b, p)
                assert (rarity, name) == (row["rarity"], row["name"]), (code, row["cell"])
                plain = roll(S, b, p, last="")
                assert plain.name == row["name"] and plain.next == p + 2
                if row["rerolls"]:
                    assert rerolls_pool
                    r = roll(S, b, p, last=row["name"])
                    # a missing "dupe" is the site's undefined: its index ran past the list ("?" here)
                    assert (r.name, r.rerolls) == (row.get("dupe") or "?", row["rerolls"]), (code, row["cell"])
                    assert r.next == p + 2 + r.rerolls
                    if row["shown"]:
                        target = row["shown"].rstrip("R")
                        assert target == label(r.next), (code, row["cell"])
                        again = canonical_at(S, b, r.next)[1] == r.name
                        assert row["shown"].endswith("R") == again
                else:
                    assert not rerolls_pool or b.pools[rarity].reroll is False
                checked += 1
    assert checked == sum(len(rows) for tracks in case["banners"].values() for rows in tracks.values())

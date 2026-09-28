"""Banner list hygiene: repeated windows of one gacha are merged, mixed banners get a combined name."""

from datetime import date

from bcplanner.model import Banner
from bcplanner.session import merge_repeats
from bcplanner.wiki import WikiClient, display_name


def banner(ev: str, gid: int, start: date, end: date, ubers=(1, 2), guaranteed=11) -> Banner:
    b = Banner(event_id=ev, gacha_id=gid, name="x", start=start, end=end, rates=(7000, 2500, 500, 0),
               pools={"rare": [10], "supa": [20], "uber": list(ubers)})
    b.guaranteed_rolls = guaranteed
    return b


def test_touching_windows_of_the_same_gacha_become_one_banner():
    banners = {
        "2026-06-08_974": banner("2026-06-08_974", 974, date(2026, 6, 8), date(2026, 6, 11)),
        "2026-06-11_974": banner("2026-06-11_974", 974, date(2026, 6, 11), date(2026, 6, 19)),
        "2026-06-10_946": banner("2026-06-10_946", 946, date(2026, 6, 10), date(2026, 6, 12), ubers=(3, 4)),
    }
    merge_repeats(banners)
    assert set(banners) == {"2026-06-08_974", "2026-06-10_946"}
    assert banners["2026-06-08_974"].end == date(2026, 6, 19)


def test_windows_that_differ_are_kept_apart():
    banners = {
        "2026-06-08_974": banner("2026-06-08_974", 974, date(2026, 6, 8), date(2026, 6, 11), guaranteed=11),
        "2026-06-11_974": banner("2026-06-11_974", 974, date(2026, 6, 11), date(2026, 6, 19), guaranteed=0),
    }
    assert merge_repeats(banners) == [] and len(banners) == 2


class FakeClient(WikiClient):
    """A wiki client whose unit pages are given, not fetched."""

    def __init__(self, events: dict[int, str]):
        self.events = events

    def unit_info(self, cat_id, name, rarity):
        return {"event": self.events.get(cat_id), "status": "ok" if cat_id in self.events else "not found"}


def test_mixed_seasonal_banner_is_named_after_every_set_it_holds():
    b = banner("e", 974, date(2026, 6, 8), date(2026, 6, 19), ubers=(1, 2, 3, 4, 5))
    client = FakeClient({1: "Halloween Capsules", 2: "Halloween Capsules", 3: "Xmas Gals", 4: "Xmas Gals", 5: "Xmas Gals"})
    title, notes = client.banner_title(b, {})
    assert title == "Xmas Gals + Halloween Gals"
    assert display_name(title, "blurb") == title
    pure = FakeClient({1: "Xmas Gals", 2: "Xmas Gals", 3: "Xmas Gals", 4: "Xmas Gals", 5: "Halloween Capsules"})
    assert pure.banner_title(b, {})[0] == "Xmas Gals"

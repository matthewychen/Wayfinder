"""Data model: cats, banners, rates and pools.

Rates are integers per 10000 in the order rare, supa, uber, legend. A score
(a rarity seed modulo 10000) maps to a rarity by cumulative bands, exactly as
gacha.rb#dig_rarity does.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

RARITIES = ("rare", "supa", "uber", "legend")
BASE = 10000

# Value of a newly obtained unit by rarity, before wishlist multipliers.
# a new rare is worth as much as a new super rare (the GUI and CLI tie the two together); a repeat rare is worth 0
DEFAULT_WEIGHTS = {"rare": 0.8, "supa": 0.8, "uber": 1.0, "legend": 8.0}
# value credited for a copy of a unit already owned or already gained in the plan (0 = only new units count)
DEFAULT_DUPE_VALUES = {"supa": 0.05, "uber": 0.2, "legend": 0.0}
# cost of going past an uber slot on the other track without a roll landing on it (opportunity cost):
# "uber" = a score that is an uber on every banner (9470+), "uber_fest" = an uber on Uberfest/Epicfest only
DEFAULT_PASS_PENALTIES = {"uber": 0.8, "uber_fest": 0.2, "legend": 5.0}   # "legend": a legend slot (9970+)
DEFAULT_TICKET_COST = 0.02          # every rare ticket spent costs this much value: spending is never free


@dataclass(frozen=True)
class Cat:
    id: int
    name: str
    rarity: str  # one of RARITIES, or "special" / "normal" for non-gacha units


@dataclass
class Banner:
    event_id: str                      # "2026-09-11_1076"
    gacha_id: int                      # 1076
    name: str
    start: date                        # inclusive
    end: date                          # exclusive
    rates: tuple[int, int, int, int]   # rare, supa, uber, legend per 10000
    pools: dict[str, list[int]]        # rarity -> ordered cat ids (slot order)
    guaranteed_rolls: int = 0          # 0 (none), 11, or 15 (step-up); from the site, user may override
    offers_eleven: bool = True         # banner sells 11-draws at all
    include: bool = True               # user wants this banner considered
    counts_for_coverage: bool = True   # its unowned units are targets for the coverage plan
    provisional: bool = False          # banner has not started on the plan date; pool may still change

    # --- derived -----------------------------------------------------------------
    @property
    def kind(self) -> str:
        rare, supa, uber, legend = self.rates
        if uber == BASE:
            return "platinum"
        if uber + legend == BASE and rare == 0 and supa == 0:
            return "legend"
        return "rare"

    @property
    def legend_threshold(self) -> int | None:
        """Lowest score that yields a legend on this banner, or None if it has no legend rate."""
        return BASE - self.rates[3] if self.rates[3] > 0 else None

    def rarity_for_score(self, score: int) -> str:
        rare, supa, uber, _legend = self.rates
        if score < rare:
            return "rare"
        if score < rare + supa:
            return "supa"
        if score < rare + supa + uber:
            return "uber"
        return "legend"

    def live_on(self, day: date) -> bool:
        return self.start <= day < self.end

    def pool(self, rarity: str) -> list[int]:
        return self.pools.get(rarity, [])

    def with_overrides(self, **kwargs) -> "Banner":
        return replace(self, **kwargs)

    def validate(self) -> list[str]:
        problems = []
        if sum(self.rates) != BASE:
            problems.append(f"{self.event_id}: rates sum to {sum(self.rates)}, expected {BASE}")
        for rarity, rate in zip(RARITIES, self.rates):
            if rate > 0 and not self.pool(rarity):
                problems.append(f"{self.event_id}: {rarity} rate {rate} but empty pool")
        if self.kind == "rare" and not self.pool("rare"):
            problems.append(f"{self.event_id}: rare banner without rare pool")
        if self.start >= self.end:
            problems.append(f"{self.event_id}: start {self.start} is not before end {self.end}")
        return problems


@dataclass
class Catalog:
    """Master unit list plus lookups."""
    cats: dict[int, Cat] = field(default_factory=dict)

    def name(self, cat_id: int) -> str:
        cat = self.cats.get(cat_id)
        return cat.name if cat else f"cat {cat_id}"

    def rarity(self, cat_id: int) -> str:
        cat = self.cats.get(cat_id)
        return cat.rarity if cat else "unknown"

    def find_by_name(self, text: str) -> list[Cat]:
        needle = text.strip().lower()
        exact = [c for c in self.cats.values() if c.name.lower() == needle]
        if exact:
            return exact
        return [c for c in self.cats.values() if needle in c.name.lower()]


def cost_of_eleven(first_draw_of_plan: bool, discount_first_draw: bool) -> int:
    """Cat food price of an 11-draw, in CF. The 750 CF offer applies to the first draw of the plan."""
    if discount_first_draw and first_draw_of_plan:
        return 750
    return 1500

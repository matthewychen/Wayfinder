"""The normal-capsule banners as bc-normal-seed-tracking models them.

These banners never change, so the data lives here instead of being fetched. Rates are per
10000. A pool with `reroll` re-rolls a result equal to the previous result (by name), which
costs extra seed steps and can move the path to the other track.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pool:
    rate: int
    units: tuple[str, ...]
    reroll: bool


@dataclass(frozen=True)
class Banner:
    code: str                 # the site's short name: np, lt, ce, cf, n, ltg
    name: str                 # the site's column title
    title: str                # what the plan calls it
    cum: tuple[int, ...]      # cumulative rates; rarity = first band whose bound exceeds score
    pools: tuple[Pool, ...]

    def rarity(self, score: int) -> int:
        for i, bound in enumerate(self.cum):
            if score < bound:
                return i
        return -1


POWER_UPS = ("Cat Cannon Attack", "Cat Cannon Charge", "Worker Cat Rate", "Worker Cat Wallet", "Base Defense",
             "Research", "Accounting", "Study", "Cat Energy")

_NORMAL_CATS = ("Cat", "Tank Cat", "Axe Cat", "Gross Cat", "Cow Cat", "Bird Cat", "Fish Cat", "Lizard Cat", "Titan Cat")

BANNERS: dict[str, Banner] = {
    "n": Banner("n", "Normal", "Normal Capsule", (10000,), (
        Pool(10000, _NORMAL_CATS + POWER_UPS, True),)),
    "np": Banner("np", "Normal+", "Cat Capsule", (10000,), (
        Pool(10000, _NORMAL_CATS + ("Superfeline",) + POWER_UPS, True),)),
    "cf": Banner("cf", "Catfruit", "Catfruit capsule", (400, 2400, 9400, 10000), (
        Pool(400, ("5K XP",), False),
        Pool(2000, ("Speed Up", "Cat CPU", "10K XP", "30K XP", "50K XP", "Purple Catfruit Seed", "Red Catfruit Seed",
                    "Blue Catfruit Seed", "Green Catfruit Seed", "Yellow Catfruit Seed"), True),
        Pool(7000, ("Rich Cat", "Cat Jobs", "Sniper the Cat", "100K XP", "200K XP", "Purple Catfruit", "Red Catfruit",
                    "Blue Catfruit", "Green Catfruit", "Yellow Catfruit"), False),
        Pool(600, ("Treasure Radar", "500K XP", "Epic Catfruit"), False))),
    "ce": Banner("ce", "Catseye", "Catseye item capsule", (500, 7400, 9400, 9900, 10000), (
        Pool(500, ("5K XP",), False),
        Pool(6900, ("10K XP", "30K XP", "Special Catseye", "Rare Catseye"), True),
        Pool(2000, ("100K XP", "Super Rare Catseye"), False),
        Pool(500, ("Uber Rare Catseye",), False),
        Pool(100, ("Dark Catseye",), False))),
    "lt": Banner("lt", "Lucky Ticket", "Lucky Ticket capsule", (0, 7400, 9500, 10000), (
        Pool(0, (), False),
        Pool(7400, ("Li'l Titan Cat", "Li'l Lizard Cat", "Li'l Fish Cat", "Li'l Bird Cat", "Li'l Cow Cat",
                    "Li'l Gross Cat", "Li'l Axe Cat", "Li'l Tank Cat", "Li'l Cat", "Speed Up", "Speed Up", "Speed Up",
                    "Cat CPU", "Cat CPU", "10K XP", "10K XP", "10K XP", "30K XP", "30K XP", "30K XP"), True),
        Pool(2100, ("Rich Cat", "Cat Jobs", "Sniper the Cat"), False),
        Pool(500, ("Treasure Radar",), False))),
    "ltg": Banner("ltg", "Lucky Ticket G", "Lucky Ticket G capsule", (0, 5100, 8600, 10000), (
        Pool(0, (), False),
        Pool(5100, ("Catamin A", "Catamin A", "Catamin A", "100K XP (β)", "100K XP (β)", "100K XP (β)"), True),
        Pool(3500, ("Catamin B", "Catamin B", "Catamin B", "500K XP"), False),
        Pool(1400, ("Catamin C", "Catamin C", "Catamin C", "1M XP"), False))),
}

# Always open (his rule): Cat Capsule, Lucky Ticket capsule and the Catseye item capsule. Catfruit only sometimes.
ALWAYS_OPEN = ("np", "lt", "ce")

# Which tickets each capsule takes. Editable per run.
DEFAULT_CURRENCY = {"n": "cat", "np": "cat", "ce": "cat", "cf": "cat", "lt": "lucky", "ltg": "lucky"}

DARK = "Dark Catseye"
DARK_BANNER = "ce"

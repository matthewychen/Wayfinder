"""Seed stream and single rolls, matching bc-normal-seed-tracking.

Positions: S[0] is the seed in the site's URL and S[i] the seed after i xorshift steps. A roll at
position p reads its rarity from S[p+1] and its unit from S[p+2] and normally moves to p+2. Even
positions are track A (row p//2 + 1), odd positions track B. When the unit equals the previous
result by name and its pool re-rolls, each re-roll takes one more step (S[p+3], ...), so one
re-roll lands on the other track.
"""

from __future__ import annotations

from dataclasses import dataclass

from .banners import Banner

MASK = 0xFFFFFFFF


def advance(x: int) -> int:
    x ^= (x << 13) & MASK
    x ^= x >> 17
    x ^= (x << 15) & MASK
    return x


class Seeds:
    def __init__(self, seed: int):
        self.s = [seed & MASK]

    def __getitem__(self, i: int) -> int:
        s = self.s
        while len(s) <= i:
            s.append(advance(s[-1]))
        return s[i]


def label(p: int) -> str:
    """The site's cell name for position p, e.g. 0 -> 1A, 1 -> 1B, 5 -> 3B."""
    return f"{p // 2 + 1}{'A' if p % 2 == 0 else 'B'}"


def _pick(seed: int, units: tuple[str, ...], removed: list[int]) -> tuple[int, str | None]:
    """The site's getUnit: with removed indices it shifts the index by the number of removed
    indices at or below it, and reports the unshifted index as the one to remove next."""
    if not removed:
        m = seed % len(units)
        return m, units[m]
    left = len(units) - len(removed)
    if left <= 0:
        return -1, None                     # the site computes x % 0 here and gets nothing
    m = seed % left
    k = m + sum(1 for r in removed if r <= m)
    return m, (units[k] if k < len(units) else None)


@dataclass(frozen=True)
class Roll:
    code: str          # banner
    p: int             # position rolled at
    rarity: int
    canonical: str     # the unit if the previous result was different
    name: str          # what you actually get
    rerolls: int       # extra steps taken (0 = no dupe)
    next: int          # position of the next roll

    @property
    def cell(self) -> str:
        return label(self.p)


def roll(S: Seeds, b: Banner, p: int, last: str) -> Roll:
    r = b.rarity(S[p + 1] % 10000)
    pool = b.pools[r]
    us = S[p + 2]
    idx, name = _pick(us, pool.units, [])
    if not (pool.reroll and name == last):
        return Roll(b.code, p, r, name, name, 0, p + 2)
    removed = [idx]
    seed, got, times = us, name, 0
    while got == name:
        times += 1
        seed = advance(seed)
        m, got = _pick(seed, pool.units, removed)
        removed.append(m)
    return Roll(b.code, p, r, name, got if got is not None else "?", times, p + 2 + times)


def canonical_at(S: Seeds, b: Banner, p: int) -> tuple[int, str, bool]:
    """(rarity, canonical unit, whether that pool re-rolls) at position p."""
    r = b.rarity(S[p + 1] % 10000)
    pool = b.pools[r]
    return r, pool.units[S[p + 2] % len(pool.units)], pool.reroll

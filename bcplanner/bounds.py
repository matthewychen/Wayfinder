"""An upper bound on the value any continuation can still gain (PLAN.md section 5, "Exact" mode).

The bound relaxes the real problem in ways that can only add value:
  * every unowned unit counts each time it is rolled (no duplicate accounting),
  * banners open on either day are available at every step (no clock changes needed),
  * the legend-slot rules are dropped,
  * a single roll may take either its normal outcome or its dupe-reroll outcome.
With those relaxations the future no longer depends on which units were already gained,
so the best continuation is a small exact dynamic programme over
(offset, tickets left, cat-food units left, platinum left, legend tickets left, discount bit).
Anything the real search could still achieve is at most this bound, which lets the exact
search discard partial plans that provably cannot beat a plan already found.
"""

from __future__ import annotations

import math
import sys
import time

from .problem import Problem
from .sim import eleven, single


class UpperBound:
    def __init__(self, problem: Problem, deadline: float | None = None):
        self.P = problem
        self.deadline = deadline          # time.perf_counter() value; past it the bound gives up (returns inf)
        self.timed_out = False
        self.calls = 0
        self.memo: dict[tuple, float] = {}
        P = problem
        self.value: dict[int, float] = {cid: P.value_of(cid) for cid in P.unit_ids}   # unowned, positive value
        self.dupe = dict(P.dupe_values)
        self.banners = [b for b in P.rare_banners]
        self._single_cache: dict[tuple, list[tuple[float, int]]] = {}
        self._eleven_cache: dict[tuple, list[tuple[float, int]]] = {}
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

    def _v(self, cat_id: int, rarity: str) -> float:
        """Most a roll of this cat can be worth: its value as a first copy, or the duplicate value."""
        return max(self.value.get(cat_id, 0.0), self.dupe.get(rarity, 0.0))

    # -- outcome variants ----------------------------------------------------------------------
    def _single_variants(self, b, k: int) -> list[tuple[float, int]]:
        key = (b.event_id, k)
        v = self._single_cache.get(key)
        if v is None:
            r = single(self.P.tables, b, k, 0)
            v = [(self._v(r.cat_id, r.rarity), r.offset_after)]
            if r.rarity == "rare" and r.cat_id > 0:
                rr = single(self.P.tables, b, k, r.cat_id)      # forced dupe: the reroll outcome
                v.append((self._v(rr.cat_id, rr.rarity), rr.offset_after))
            self._single_cache[key] = v
        return v

    def _eleven_variants(self, b, k: int) -> list[tuple[float, int]]:
        key = (b.event_id, k)
        v = self._eleven_cache.get(key)
        if v is None:
            v = []
            lasts = [0]
            r0 = single(self.P.tables, b, k, 0)
            if r0.rarity == "rare" and r0.cat_id > 0:
                lasts.append(r0.cat_id)                        # the first roll may be a dupe of the previous cat
            for last in lasts:
                rolls, g, k2, _ = eleven(self.P.tables, b, k, last, b.guaranteed_rolls)
                total = sum(self._v(r.cat_id, r.rarity) for r in rolls)
                if g is not None:
                    total += self._v(g.cat_id, "uber")
                v.append((total, k2))
            self._eleven_cache[key] = v
        return v

    # -- the bound ------------------------------------------------------------------------------
    def ub(self, k: int, t: int, c: int, p: int, l: int, dmask: int) -> float:
        """Most value any continuation could gain from offset k with these resources left."""
        if t <= 0 and c <= 0 and p <= 0 and l <= 0:
            return 0.0
        if self.deadline is not None:
            self.calls += 1
            if self.timed_out or ((self.calls & 4095) == 0 and time.perf_counter() > self.deadline):
                self.timed_out = True
                return math.inf               # no pruning from here on; the search's own deadline then stops it
        key = (k, t, c, p, l, dmask)
        hit = self.memo.get(key)
        if hit is not None:
            return hit
        P = self.P
        best = 0.0
        if t > 0:
            for b in self.banners:
                for v, k2 in self._single_variants(b, k):
                    cand = v + self.ub(k2, t - 1, c, p, l, dmask)
                    if cand > best:
                        best = cand
        if c > 0:
            for b in self.banners:
                if not b.offers_eleven:
                    continue
                cost = P.eleven_cost_units(b, dmask)
                if c < cost:
                    continue
                d2 = P.dmask_after_eleven(dmask)
                for v, k2 in self._eleven_variants(b, k):
                    cand = v + self.ub(k2, t, c - cost, p, l, d2)
                    if cand > best:
                        best = cand
        if p > 0 and P.plat is not None:
            r = single(P.tables, P.plat, k, 0)
            cand = self._v(r.cat_id, r.rarity) + self.ub(k + 2, t, c, p - 1, l, dmask)
            if cand > best:
                best = cand
        if l > 0 and P.legend is not None and P.tables.is_legend_slot(P.legend, k):
            r = single(P.tables, P.legend, k, 0)
            cand = self._v(r.cat_id, r.rarity) + self.ub(k + 2, t, c, p, l - 1, dmask)
            if cand > best:
                best = cand
        self.memo[key] = best
        return best

"""What resources kept for the next banner are worth (PLAN.md, fifteenth round).

The seed only moves when you roll, so the positions a plan leaves unused are exactly the positions
the next banner will use, and the rarity band of every position is fixed by the seed whatever the
banner. The only unknown is which unit the next banner puts in each slot. Two ways to price that:

* flat: "a future 11-draw is worth about V" (per ticket, V divided by the tickets-per-draw rate);
* seed: every unused position is scored by its known band times the chance that a unit of that
  rarity on a typical next banner is new to you (from your owned list), times the weights, plus the
  repeat value otherwise, minus the same pass penalties the plan pays today; the best way to spend
  the leftover resources on that virtual banner is found by a small dynamic programme; a confidence
  factor scales the whole estimate.

`FutureValue.value(k, tickets, cf_units, plats, legends)` is the expected value of arriving at
position k with those resources unspent. A plan is chosen by value now plus this, so a roll is only
made now when its real gain beats what the position is expected to give later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .problem import Problem

MODES = ("none", "flat", "seed")
NORMAL_BANDS = ((9970, "legend"), (9470, "uber"), (6970, "supa"))     # a typical (non-fest) banner's cut-offs


@dataclass
class FutureModel:
    mode: str = "none"
    flat_per_draw: float = 2.0          # a future 11-draw, or a draw's worth of tickets, is worth at least this
                                        # (the whole value in flat mode, a floor under the estimate in seed mode)
    confidence: float = 0.8             # seed mode: how much of the estimate to trust
    p_new: dict[str, float] = field(default_factory=dict)   # rarity -> chance a future unit is new; empty = estimate
    guaranteed: bool = True             # a future 11-draw ends with a guaranteed uber


def estimate_p_new_from(banners, owned) -> dict[str, float]:
    """Chance that a unit of each rarity on a typical next banner is new to you: the unowned share of
    the shared uber list (platinum pool), of the rares and super rares seen on today's banners, and of
    the legend list. A banner you are saving for on purpose is usually better than typical: raise it."""
    owned = set(owned)
    rare = [b for b in banners.values() if b.kind == "rare"]
    plat = next((b for b in banners.values() if b.kind == "platinum"), None)
    leg = next((b for b in banners.values() if b.kind == "legend"), None)

    def share(ids) -> float:
        ids = list(dict.fromkeys(ids))
        return (sum(1 for c in ids if c not in owned) / len(ids)) if ids else 0.0

    ubers = list(plat.pool("uber")) if plat is not None else [c for b in rare for c in b.pool("uber")]
    rares = [c for b in rare for c in b.pool("rare")]
    supas = [c for b in rare for c in b.pool("supa")]
    legends = list(leg.pool("legend")) if leg is not None else [c for b in rare for c in b.pool("legend")]
    return {"rare": share(rares), "supa": share(supas), "uber": share(ubers), "legend": share(legends)}


def estimate_p_new(problem: Problem) -> dict[str, float]:
    return estimate_p_new_from(problem.banners, problem.owned)


class FutureValue:
    def __init__(self, problem: Problem, model: FutureModel):
        self.P = problem
        self.m = model
        self.p_new = dict(model.p_new) if model.p_new else estimate_p_new(problem)
        self.memo: dict[tuple, float] = {}
        self._gain: dict[int, float] = {}

    # -- per position ---------------------------------------------------------------------
    def band(self, k: int) -> str:
        self.P.tables.ensure(k)
        s = self.P.tables.score[k]
        for cut, name in NORMAL_BANDS:
            if s >= cut:
                return name
        return "rare"

    def expected(self, rarity: str) -> float:
        """Expected value of a unit of this rarity on a typical next banner (rares included: a new rare is
        worth its weight, a repeat rare nothing)."""
        p = self.p_new.get(rarity, 0.0)
        return p * self.P.weights.get(rarity, 0.0) + (1 - p) * self.P.dupe_value(rarity)

    def gain(self, k: int) -> float:
        g = self._gain.get(k)
        if g is None:
            band = self.band(k)
            g = self.expected(band)
            if band == "legend":
                g = max(g, self.legend_now(k))
            self._gain[k] = g
        return g

    def legend_now(self, k: int) -> float:
        """No rush for a legend: a legend slot keeps its unit until the path is past it, so when a banner
        that runs beyond the plan's two days holds a legend you lack at this slot, the slot is worth
        that legend later too. The plan then need not burn uber slots to reach it now; it only must
        never go past it (see the legend pass penalty)."""
        P = self.P
        best = 0.0
        for b in P.rare_banners:
            if b.end <= P.today + timedelta(days=2) or not P.tables.is_legend_slot(b, k):
                continue
            _, _, cid = P.tables.cat_at(b, k)
            if cid > 0 and cid not in P.owned:
                best = max(best, P.value_of(cid))
        return best

    # -- the value of leftovers ---------------------------------------------------------------
    def floor(self, t: int, c: int) -> float:
        """The flat price: a future 11-draw, or a draw's worth of tickets, is worth at least this."""
        return self.m.flat_per_draw * (max(t, 0) / self.P.tickets_per_draw + max(c, 0) / 2)

    def selection(self, t: int, c: int, p: int) -> float:
        """Steering value of kept tickets: on the next banner each ticket rolled before a guaranteed
        11-draw (or a platinum pull) moves its uber slot one position, so with t tickets there are t+1
        candidate ubers to choose from instead of one. The expected gain over taking the first candidate
        blindly is (new value - repeat value) x P(at least one candidate is new) - p, spread over the
        S selectable pulls kept."""
        S = (c // 2 if self.m.guaranteed else 0) + max(p, 0)
        if S <= 0 or t <= 0:
            return 0.0
        pn = self.p_new.get("uber", 0.0)
        per_pull = (self.P.weights.get("uber", 0.0) - self.P.dupe_value("uber")) * (1 - pn) * (1 - (1 - pn) ** (t / S))
        return max(0.0, S * per_pull)

    def estimate(self, k: int, t: int, c: int, p: int, l: int) -> float:
        """Seed mode before the floor: the virtual-banner programme plus the steering value."""
        t, c, p, l = max(t, 0), max(c, 0), max(p, 0), max(l, 0)
        return self.m.confidence * (self._f(k, t, c, p, l) + self.selection(t, c, p))

    def value(self, k: int, t: int, c: int, p: int, l: int) -> float:
        if self.m.mode == "none" or (t <= 0 and c <= 0 and p <= 0 and l <= 0):
            return 0.0
        if self.m.mode == "flat":
            return self.floor(t, c)
        return max(self.estimate(k, t, c, p, l), self.floor(t, c))

    def _f(self, k: int, t: int, c: int, p: int, l: int) -> float:
        """Best expected value of spending (t, c, p, l) on the virtual next banner from position k."""
        if t <= 0 and c <= 0 and p <= 0 and l <= 0:
            return 0.0
        key = (k, t, c, p, l)
        hit = self.memo.get(key)
        if hit is not None:
            return hit
        best = 0.0
        if t > 0:
            best = max(best, self.gain(k) - self.passed(k, k + 2, (k,)) - self.P.ticket_cost
                       + self._f(k + 2, t - 1, c, p, l))
        if c >= 2:
            if self.m.guaranteed:
                landed = [k + 2 * i for i in range(10)]
                g = sum(self.gain(x) for x in landed) + self.expected("uber")
                k2 = k + 21
                landed.append(k + 20)
            else:
                landed = [k + 2 * i for i in range(11)]
                g = sum(self.gain(x) for x in landed)
                k2 = k + 22
            best = max(best, g - self.passed(k, k2, set(landed)) + self._f(k2, t, c - 2, p, l))
        if p > 0:
            best = max(best, self.expected("uber") - self.passed(k, k + 2, (k,)) + self._f(k + 2, t, c, p - 1, l))
        if l > 0 and self.band(k) == "legend":
            best = max(best, self.expected("legend") - self.passed(k, k + 2, (k,)) + self._f(k + 2, t, c, p, l - 1))
        self.memo[key] = best
        return best

    def passed(self, k0: int, k1: int, landed) -> float:
        """Rolls on the next banner pay for the slots gone past on the other track like rolls today: the
        bands are known from the seed, and whether the uber there would be new is the same chance as for
        any next-banner uber, so a slot costs the band penalty with that chance and a repeat's value otherwise."""
        P = self.P
        if not P.pass_penalties:
            return 0.0
        total = 0.0
        for p in range(k0, k1):
            if p in landed:
                continue
            band = P.slot_band(p)
            if not band:
                continue
            r = "legend" if band == "legend" else "uber"
            pn = self.p_new.get(r, 0.0)
            total += pn * P.pass_penalties.get(band, 0.0) + (1 - pn) * P.dupe_value(r)
        return total

    def describe(self, k: int, t: int, c: int, p: int, l: int) -> dict:
        """What the leftovers could reach: the value and the slots ahead on the current track."""
        reach = 2 * t + 21 * (c // 2) + 2 * p + 2 * l
        counts = {"legend": 0, "uber": 0, "supa": 0}
        for x in range(k, k + reach, 2):
            b = self.band(x)
            if b in counts:
                counts[b] += 1
        est = self.estimate(k, t, c, p, l) if self.m.mode == "seed" else 0.0
        fl = self.floor(t, c) if self.m.mode in ("seed", "flat") else 0.0
        return {"value": self.value(k, t, c, p, l), "slots": counts, "p_new": dict(self.p_new),
                "positions": reach // 2, "mode": self.m.mode, "estimate": est, "floor": fl,
                "basis": "floor" if self.m.mode == "flat" or fl >= est else "estimate"}

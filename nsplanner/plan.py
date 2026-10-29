"""Exact planner: which capsule to pull at every position.

Every item's value is additive (you own every unit, so nothing is "new"), so the best plan is a
longest path over states (position, last result, tickets used of each kind). A state's last result
is kept only while it can still cause a re-roll at that position, which keeps the state count small.
Every state is a possible end of the plan.

Score = sum of item weights (each blue orb 1, each Li'l Axe Cat 1 by default)
        - dark_value for every Dark Catseye the plan gives up.

A Dark Catseye at position q is "given up" by the pull that turns it from reachable into
unreachable without taking it. Reachable means some sequence of pulls on the open capsules, with
any number of tickets, lands on q (where a Catseye pull takes it). So:
  * rolling another capsule on q, or switching away from its track for good, gives it up;
  * two Dark Catseyes so close on opposite tracks that only one can be taken cost one penalty;
  * a Dark Catseye that was never reachable costs nothing;
  * one that is still ahead and reachable when the plan ends is not given up: it stays on the seed.
A plan therefore only gives a Dark Catseye up when that buys more than `dark_value` blue orbs.

Among plans with the same score the one with the fewest lucky tickets wins (they are the scarce ticket:
a lucky pull is only made where the score needs it), then the fewest pulls, then the fewest capsule
changes.
"""

from __future__ import annotations

import bisect
import heapq
from functools import lru_cache
from dataclasses import dataclass, field

from .banners import ALWAYS_OPEN, BANNERS, DARK, DARK_BANNER, DEFAULT_CURRENCY, POWER_UPS
from .sim import Roll, Seeds, canonical_at, label, roll


def default_weights() -> dict[str, float]:
    w = {name: 1.0 for name in POWER_UPS}        # the blue cells on the site: power-ups from the Cat Capsule
    w["Li'l Axe Cat"] = 1.0
    return w


@dataclass
class Settings:
    tickets: dict[str, int] = field(default_factory=lambda: {"cat": 0, "lucky": 0})
    banners: tuple[str, ...] = ALWAYS_OPEN
    currency: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CURRENCY))
    weights: dict[str, float] = field(default_factory=default_weights)
    dark_value: float = 20.0          # blue orbs you would give up rather than lose one Dark Catseye


@dataclass
class Result:
    rolls: list[Roll]
    score: float
    orbs: int                  # power-ups
    weighted: dict[str, int]   # every item with a weight, and how many
    darks: list[str]           # cells where a Dark Catseye is taken
    missed: list[str]          # Dark Catseyes given up (they were still reachable)
    out_of_reach: list[str]    # Dark Catseyes passed that no sequence of pulls could have reached by then
    used: dict[str, int]
    end: int                   # position after the last roll
    end_seed: int              # the seed to put in the site's URL afterwards
    end_last: str              # the last result, for the site's lastCat
    darks_ahead: list[str]     # the next Dark Catseyes after the end, for the record
    search_score: float = 0.0  # the score the search itself computed (equals `score` unless its window misled it)


class World:
    """Rolls, canonical last results, Dark Catseye positions and their reachability for one seed and
    one set of open capsules. `window` bounds how far back reachability is worked out exactly;
    further back every Dark Catseye counts as reachable (60 pulls always offer a track switch in
    practice, and the replay, which uses no window, checks it)."""

    def __init__(self, seed: int, codes, window: int | None = 160):
        self.S = Seeds(seed)
        self.codes = list(codes)
        self.window = window
        self._dark: dict[int, bool] = {}
        self._darks: list[int] = []
        self._darks_to = 0
        self._rel: dict[int, frozenset] = {}
        self._roll: dict[tuple, Roll] = {}
        self._reach: dict[int, tuple[int, dict]] = {}
        self.dark_on = DARK_BANNER in self.codes

    # -- basics --------------------------------------------------------------------------------
    def is_dark(self, q: int) -> bool:
        hit = self._dark.get(q)
        if hit is None:
            hit = canonical_at(self.S, BANNERS[DARK_BANNER], q)[1] == DARK
            self._dark[q] = hit
        return hit

    def darks_between(self, lo: int, hi: int) -> list[int]:
        """Dark Catseye positions q with lo <= q < hi."""
        while self._darks_to < hi:
            if self.is_dark(self._darks_to):
                self._darks.append(self._darks_to)
            self._darks_to += 1
        i = bisect.bisect_left(self._darks, lo)
        j = bisect.bisect_left(self._darks, hi)
        return self._darks[i:j]

    def lasts(self, p: int) -> frozenset:
        """Units that some open capsule's re-rolling pool shows at p: the only last results that matter there."""
        rel = self._rel.get(p)
        if rel is None:
            names = set()
            for c in self.codes:
                _r, name, rerolls = canonical_at(self.S, BANNERS[c], p)
                if rerolls:
                    names.add(name)
            rel = frozenset(names)
            self._rel[p] = rel
        return rel

    def canon(self, p: int, last: str) -> str:
        return last if last in self.lasts(p) else ""

    def roll(self, code: str, p: int, last: str) -> Roll:
        key = (code, p, last)
        r = self._roll.get(key)
        if r is None:
            r = roll(self.S, BANNERS[code], p, last)
            self._roll[key] = r
        return r

    # -- Dark Catseye reachability -------------------------------------------------------------
    def reachable(self, q: int, p: int, last: str) -> bool:
        """Can some sequence of pulls from (p, last) land on q? `last` must be canonical at p."""
        if p > q:
            return False
        if p == q:
            return True
        lo, table = self._reach_table(q)
        if p < lo:
            return True
        return table[p][last]

    def _reach_table(self, q: int):
        hit = self._reach.get(q)
        if hit is not None:
            return hit
        lo = 0 if self.window is None else max(0, q - self.window)
        table: dict[int, dict[str, bool]] = {q: None}
        for p in range(q - 1, lo - 1, -1):
            row = {}
            for last in self.lasts(p) | {""}:
                ok = False
                for c in self.codes:
                    r = self.roll(c, p, last)
                    if r.next == q or (r.next < q and table[r.next][self.canon(r.next, r.name)]):
                        ok = True
                        break
                row[last] = ok
            table[p] = row
        self._reach[q] = (lo, table)
        return lo, table

    def given_up(self, p: int, last: str, r: Roll, nlast: str) -> tuple[int, int]:
        """(Dark Catseyes this pull gives up, Dark Catseyes it passes that were already out of reach)."""
        if not self.dark_on:
            return 0, 0
        hi = p + (self.window if self.window is not None else 10 ** 9)
        lost = gone = 0
        for q in self.darks_between(p, max(hi, r.next)):
            if q == p and r.code == DARK_BANNER:
                continue                           # taken
            before = self.reachable(q, p, last)
            after = self.reachable(q, r.next, nlast)
            if before and not after:
                lost += 1
            elif not before and q < r.next:
                gone += 1
        return lost, gone


@lru_cache(maxsize=32)
def world(seed: int, codes: tuple[str, ...], window: int | None = 160) -> World:
    """One World per seed and capsule set, so its rolls and reachability tables are built once."""
    return World(seed, codes, window)


NEG = -1e18
SWITCH = 1e-7       # tie-break cost of changing capsule between two pulls (a 5000-pull plan stays under 0.001)
SPARE = "lucky"     # the ticket a tie is broken on first: fewest of these
KEYS = 64           # key slots per position in a choice code; a step is at most 22 (20 re-rolls), so codes fit int16


def plan(seed: int, last: str, st: Settings) -> Result:
    """The best plan within the tickets: highest score, then fewest lucky tickets, then fewest tickets, then
    fewest capsule switches.

    States at a position are grids: rows = pulls made so far (n), columns = tickets of the smaller
    currency used (e); the other currency's count is n - e. A pull from (position, last result) moves
    every cell of the grid the same way, to the same next position and last result, with the same
    gain, so each transition is one array operation. `choice` grids remember where each cell came
    from, for walking the plan back. A state also remembers the capsule of the last pull, and every
    switch of capsule costs SWITCH (far below any real difference in value), so among equally good
    plans the one with the fewest switches, i.e. the fewest operations to follow, wins."""
    import numpy as np

    codes = [c for c in st.banners if c in BANNERS]
    w = world(seed, tuple(codes))
    currs = sorted({st.currency[c] for c in codes})
    if len(currs) > 2:
        raise ValueError("the planner handles at most two kinds of tickets")
    caps = {cur: int(st.tickets.get(cur, 0)) for cur in currs}
    if len(currs) == 1:
        implied, explicit = currs[0], None
    else:
        implied, explicit = sorted(currs, key=lambda cur: (-caps[cur], cur))[:2]
    cap_i = caps[implied]
    cap_e = caps[explicit] if explicit else 0
    E = cap_e + 1
    weights, dv = st.weights, st.dark_value

    # per position: (last result, last capsule) -> [n0, values grid]; choice grids are kept for every position
    k0 = (w.canon(0, last), -1)
    frontier: dict[int, dict[tuple, list]] = {0: {k0: [0, np.full((1, E), NEG)]}}
    frontier[0][k0][1][0, 0] = 0.0
    choices: dict[tuple, list] = {}      # (p, key) -> [n0, int16 grid: ((step * 64 + key index) * 8 + capsule)]
    order: dict[int, list[tuple]] = {0: [k0]}
    heap, seen = [0], {0}
    best = (0.0, 0, 0, 0.0, 0, k0, 0, 0)  # (score to 3 places, -lucky, -tickets, exact score, p, key, n, e)
    trans: dict[tuple, tuple] = {}
    e_idx = np.arange(E)

    while heap:
        p = heapq.heappop(heap)
        for skey, (n0, A) in frontier.pop(p).items():
            lc, pc = skey
            # best end state here: highest value, then fewest lucky tickets, then fewest pulls, then fewest switches
            vmax = float(A.max())
            if vmax > NEG / 2:
                top = round(vmax, 3)
                if top >= best[0]:
                    ii, ee = np.nonzero(np.round(A, 3) >= top)
                    nn = n0 + ii
                    spare = ee if explicit == SPARE else (nn - ee if implied == SPARE else np.zeros_like(ee))
                    j = int(np.lexsort((-A[ii, ee], nn, spare))[0])
                    rank = (top, -int(spare[j]), -int(nn[j]), float(A[ii[j], ee[j]]))
                    if rank > best[:4]:
                        best = (*rank, p, skey, int(nn[j]), int(ee[j]))
            key_index = order[p].index(skey)
            if key_index >= KEYS:
                raise RuntimeError(f"more than {KEYS} states at one position")   # at most 7 x 7 with all six capsules
            W = A.shape[0]
            n_col = (n0 + np.arange(W))[:, None]
            for ci_, code in enumerate(codes):
                key = (p, lc, code)
                t = trans.get(key)
                if t is None:
                    r = w.roll(code, p, lc)
                    nlast = w.canon(r.next, r.name)
                    lost = w.given_up(p, lc, r, nlast)[0] if dv else 0
                    t = (r.next, nlast, weights.get(r.name, 0.0) - dv * lost)
                    trans[key] = t
                nxt, nlast, gain = t
                if pc >= 0 and pc != ci_:
                    gain -= SWITCH
                tkey = (nlast, ci_)
                if st.currency[code] == implied:
                    ok = (n_col - e_idx[None, :]) < cap_i          # the implied currency still has a ticket
                    S = np.where(ok & (A > NEG / 2), A + gain, NEG)
                else:
                    S = np.full_like(A, NEG)
                    if E > 1:
                        S[:, 1:] = np.where(A[:, :-1] > NEG / 2, A[:, :-1] + gain, NEG)
                if not (S > NEG / 2).any():
                    continue
                # target grid at (nxt, tkey) covering rows n0+1 .. n0+W
                bucket = frontier.setdefault(nxt, {})
                if tkey not in bucket:
                    bucket[tkey] = [n0 + 1, np.full((W, E), NEG)]
                    choices[(nxt, tkey)] = [n0 + 1, np.full((W, E), -1, dtype=np.int16)]
                    order.setdefault(nxt, []).append(tkey)
                tn0, T = bucket[tkey]
                cn0, C = choices[(nxt, tkey)]
                lo, hi = min(tn0, n0 + 1), max(tn0 + T.shape[0], n0 + 1 + W)
                if lo != tn0 or hi != tn0 + T.shape[0]:
                    T2 = np.full((hi - lo, E), NEG)
                    T2[tn0 - lo: tn0 - lo + T.shape[0]] = T
                    C2 = np.full((hi - lo, E), -1, dtype=np.int16)
                    C2[tn0 - lo: tn0 - lo + C.shape[0]] = C
                    T, C, tn0 = T2, C2, lo
                    bucket[tkey] = [tn0, T]
                    choices[(nxt, tkey)] = [tn0, C]
                a = n0 + 1 - tn0
                block, cblock = T[a:a + W], C[a:a + W]
                better = S > block + 1e-12
                block[better] = S[better]
                cblock[better] = ((nxt - p) * KEYS + key_index) * 8 + ci_
                if nxt not in seen:
                    seen.add(nxt)
                    heapq.heappush(heap, nxt)
        order.get(p)        # positions behind us keep only their choice grids

    # walk back from the best end state
    _top, _negl, _negt, exact, p, skey, n, e = best
    rolls: list[Roll] = []
    while n > 0:
        cn0, C = choices[(p, skey)]
        code_v = int(C[n - cn0, e])
        ci_ = code_v % 8
        key_index = (code_v // 8) % KEYS
        dp = code_v // (8 * KEYS)
        code = codes[ci_]
        sp = p - dp
        skey = order[sp][key_index]
        rolls.append(w.roll(code, sp, skey[0]))
        if explicit and st.currency[code] == explicit:
            e -= 1
        n -= 1
        p = sp
    rolls.reverse()
    res = summarise(seed, last, [r.code for r in rolls], st)
    switches = sum(1 for a, b in zip(rolls, rolls[1:]) if a.code != b.code)
    res.search_score = round(exact + SWITCH * switches, 6)
    return res


def plan_slow(seed: int, last: str, st: Settings) -> Result:
    """Reference version of `plan`, one Python step per state (slow, kept for the tests)."""
    codes = [c for c in st.banners if c in BANNERS]
    w = world(seed, tuple(codes))
    currs = sorted({st.currency[c] for c in codes})
    ci = {c: currs.index(st.currency[c]) for c in codes}
    caps = tuple(int(st.tickets.get(cur, 0)) for cur in currs)
    spare = currs.index(SPARE) if SPARE in currs else None
    weights, dv = st.weights, st.dark_value
    start_key = (w.canon(0, last), (0,) * len(currs))
    # entry: (score, -changes, prev_code, parent (p, key) or None, roll or None)
    table: dict[int, dict[tuple, tuple]] = {0: {start_key: (0.0, 0, None, None, None)}}
    heap, seen = [0], {0}
    best_rank, best_at = (0.0, 0, 0, 0), (0, start_key)   # rank = (score, -lucky, -tickets, -changes)
    while heap:
        p = heapq.heappop(heap)
        for key, (score, negch, prev_code, _parent, _r) in table[p].items():
            last_c, used = key
            rank = (round(score, 6), -(used[spare] if spare is not None else 0), -sum(used), negch)
            if rank > best_rank:
                best_rank, best_at = rank, (p, key)
            for code in codes:
                i = ci[code]
                if used[i] >= caps[i]:
                    continue
                r = w.roll(code, p, last_c)
                nlast = w.canon(r.next, r.name)
                lost = w.given_up(p, last_c, r, nlast)[0] if dv else 0
                nscore = score + weights.get(r.name, 0.0) - dv * lost
                nneg = negch - (1 if prev_code is not None and code != prev_code else 0)
                nkey = (nlast, used[:i] + (used[i] + 1,) + used[i + 1:])
                bucket = table.get(r.next)
                if bucket is None:
                    bucket = table[r.next] = {}
                old = bucket.get(nkey)
                if old is None or nscore > old[0] + 1e-9 or (abs(nscore - old[0]) <= 1e-9 and nneg > old[1]):
                    bucket[nkey] = (nscore, nneg, code, (p, key), r)
                    if r.next not in seen:
                        seen.add(r.next)
                        heapq.heappush(heap, r.next)
    rolls: list[Roll] = []
    p, key = best_at
    while True:
        entry = table[p][key]
        if entry[3] is None:
            break
        rolls.append(entry[4])
        p, key = entry[3]
    rolls.reverse()
    res = summarise(seed, last, [r.code for r in rolls], st)
    res.search_score = table[best_at[0]][best_at[1]][0]
    return res


def replay(seed: int, last: str, codes: list[str], st: Settings):
    """Independent check of a plan, with exact reachability (no window): (rolls, score, Dark Catseyes
    taken, given up, passed out of reach)."""
    open_codes = [c for c in st.banners if c in BANNERS]
    w = world(seed, tuple(open_codes), None)
    p, cur = 0, w.canon(0, last)
    rolls, score, taken, missed, gone = [], 0.0, [], [], []
    for code in codes:
        r = roll(w.S, BANNERS[code], p, cur)
        rolls.append(r)
        score += st.weights.get(r.name, 0.0)
        if r.name == DARK:
            taken.append(r.cell)
        nlast = w.canon(r.next, r.name)
        if w.dark_on and st.dark_value:
            for q in w.darks_between(p, r.next + 400):     # far beyond that, reachability never changes
                if q == p and code == DARK_BANNER:
                    continue
                before, after = w.reachable(q, p, cur), w.reachable(q, r.next, nlast)
                if before and not after:
                    missed.append(label(q))
                    score -= st.dark_value
                elif not before and q < r.next and label(q) not in missed:
                    gone.append(label(q))           # never reachable from this path: no penalty
        p, cur = r.next, nlast
    return rolls, score, taken, missed, gone


def summarise(seed: int, last: str, codes: list[str], st: Settings) -> Result:
    rolls, score, taken, missed, gone = replay(seed, last, codes, st)
    S = Seeds(seed)
    end = rolls[-1].next if rolls else 0
    used: dict[str, int] = {}
    for r in rolls:
        cur = st.currency[r.code]
        used[cur] = used.get(cur, 0) + 1
    weighted: dict[str, int] = {}
    for r in rolls:
        if st.weights.get(r.name, 0.0):
            weighted[r.name] = weighted.get(r.name, 0) + 1
    ahead = []
    if DARK_BANNER in st.banners:
        q = end
        while len(ahead) < 3 and q < end + 3000:
            if canonical_at(S, BANNERS[DARK_BANNER], q)[1] == DARK:
                ahead.append(label(q))
            q += 1
    return Result(rolls=rolls, score=score, orbs=sum(1 for r in rolls if r.name in POWER_UPS), weighted=weighted,
                  darks=taken, missed=missed, out_of_reach=gone, used=used, end=end, end_seed=S[end],
                  end_last=rolls[-1].name if rolls else last, darks_ahead=ahead)

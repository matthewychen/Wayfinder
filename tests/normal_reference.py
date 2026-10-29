"""Independent exact optimum for the normal planner (a test reference), sharing only sim.roll / Seeds /
the banner data with it.

No World, no canonical last results, no reachability window inside the search, no grids, no recursion.
Score of a path:
  sum of weights + dark_value * (Dark Catseyes taken)
  - dark_value * |{Dark q reachable from the start, not taken, not reachable from the end state}|
which is the planner's per-pull "given up" penalty telescoped (a Dark leaves the reachable set once).
Darks H or more positions past the end count as reachable (the planner's replay also looks 400 ahead).
"""
from nsplanner.banners import BANNERS, DARK, DEFAULT_CURRENCY
from nsplanner.sim import Seeds, roll

H = 400


class Space:
    """All states (position, raw last result) reachable from the start, with their successors."""

    def __init__(self, S, codes, start, limit):
        self.S, self.codes = S, codes
        self.succ = {}
        todo = [start]
        while todo:
            s = todo.pop()
            if s in self.succ:
                continue
            p, l = s
            out = []
            for c in codes:
                r = roll(S, BANNERS[c], p, l)
                t = (r.next, r.name)
                out.append((c, r, t))
                if r.next < limit and t not in self.succ:
                    todo.append(t)
            self.succ[s] = out
        self.by_p = sorted(self.succ, key=lambda s: -s[0])

    def reach_table(self, q):
        """state -> can some pull sequence from it land on q (states from q-H to q)."""
        ok = {}
        for s in self.by_p:            # decreasing position: successors are decided first
            p = s[0]
            if p >= q:
                ok[s] = p == q
                continue
            if p < q - H:
                break
            ok[s] = any(t[0] == q or (t[0] < q and ok.get(t, False)) for _c, _r, t in self.succ[s])
        return ok


def is_dark(S, q):
    ce = BANNERS["ce"]
    pool = ce.pools[ce.rarity(S[q + 1] % 10000)]
    return pool.units[S[q + 2] % len(pool.units)] == DARK


def solve(seed, last, cat, lucky, codes, weights, dv):
    S = Seeds(seed)
    cur = {c: DEFAULT_CURRENCY[c] for c in codes}
    memo = {}

    def R(c, p, l):
        k = (c, p, l)
        r = memo.get(k)
        if r is None:
            r = memo[k] = roll(S, BANNERS[c], p, l)
        return r

    # 1. every reachable state with tickets left: best (weights + dv * darks taken), layer by layer;
    #    per end state the best (value, fewest lucky tickets, fewest pulls)
    ends = {(0, last): (0.0, 0, 0)}  # (p, last) -> (best value, lucky tickets, pulls)
    layer = {(0, last, 0): 0.0}      # (p, last, lucky used) -> best value
    for n in range(1, cat + lucky + 1):
        nxt = {}
        for (p, l, e), v in layer.items():
            for c in codes:
                if cur[c] == "lucky":
                    if e >= lucky:
                        continue
                    ne = e + 1
                elif n - 1 - e >= cat:
                    continue
                else:
                    ne = e
                r = R(c, p, l)
                nv = v + weights.get(r.name, 0.0) + (dv if r.name == DARK else 0.0)
                k = (r.next, r.name, ne)
                if nv > nxt.get(k, -1e18):
                    nxt[k] = nv
        if not nxt:
            break
        for (p, l, e), v in nxt.items():
            old = ends.get((p, l))
            if old is None or (round(v, 6), -e, -n) > (round(old[0], 6), -old[1], -old[2]):
                ends[(p, l)] = (v, e, n)
        layer = nxt

    # 2. the Dark Catseye penalty at each end state
    if not dv or "ce" not in codes:
        v, e, n = max(ends.values(), key=lambda t: (round(t[0], 6), -t[1], -t[2]))
        return v, e, n
    maxp = max(p for p, _l in ends)
    space = Space(S, codes, (0, last), maxp + H + 30)
    reach_pos = {s[0] for s in space.succ}
    dstart = [q for q in range(maxp + H) if q in reach_pos and is_dark(S, q)]
    tables = {q: space.reach_table(q) for q in dstart}
    best = (-1e18, 0, 0)
    for (p, l), (v, e, n) in ends.items():
        lost = sum(1 for q in dstart if q < p) + sum(1 for q in dstart if p <= q < p + H and not tables[q][(p, l)])
        s = v - dv * lost
        if (round(s, 6), -e, -n) > (round(best[0], 6), -best[1], -best[2]):
            best = (s, e, n)
    return best


def score_path(seed, last, path, codes, weights, dv):
    """This file's own score for a given list of capsules, to check the planner's replay score."""
    S = Seeds(seed)
    p, l, v, taken = 0, last, 0.0, set()
    for c in path:
        r = roll(S, BANNERS[c], p, l)
        v += weights.get(r.name, 0.0)
        if r.name == DARK:
            taken.add(p)
        p, l = r.next, r.name
    if not dv or "ce" not in codes:
        return v
    space = Space(S, codes, (0, last), p + H + 30)
    reach_pos = {s[0] for s in space.succ}
    lost = 0
    for q in range(p + H):
        if q in taken or q not in reach_pos or not is_dark(S, q):
            continue
        if q < p:
            lost += 1
        else:
            t = space.reach_table(q)
            if not t[(p, l)]:
                lost += 1
    return v - dv * lost

"""Exact label-setting search over (offset, last rare, clock, discount bits).

See PLAN.md section 5. Labels at a node form a Pareto frontier over the resources
spent and the clock changes made, with an exact value-aware dominance rule:

    A dominates B  iff  resources(A) <= resources(B)  and
                        value(A) - value(B) >= value( W_B & gained(A) & ~gained(B) )

where W_B is the set of units any action could still yield inside the window of
offsets B's remaining resources can reach. Any future path feasible for B is
feasible for A and adds the same units to both; A can only lose out on units it
already holds that B lacks and that reappear, and its value lead covers them.
Every label anywhere is a candidate plan because you may stop at any time.

A clock change is never a label of its own: a roll on a banner that only the other day has is
generated with the change folded in (the change becomes the roll's parent), so the search never
walks through date changes that no roll needs, and the day-change count only enters the beam as
"can this plan still change the date or not".
"""


from __future__ import annotations

import time
from dataclasses import dataclass, field

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE, TODAY, TOMORROW
from .problem import Problem
from .sim import eleven, next_last_rare, single

BEAM_SKIPS = "none"      # how the per-node beam groups labels by clock changes: "full" | "flag" | "none"


class Label:
    __slots__ = ("k", "last", "clock", "dmask", "t", "c", "p", "l", "skips",
                 "gained", "value", "parent", "action", "alive", "window", "pending")

    def __init__(self, k, last, clock, dmask, t, c, p, l, skips, gained, value, parent, action, pending=False):
        self.k = k; self.last = last; self.clock = clock; self.dmask = dmask
        self.t = t; self.c = c; self.p = p; self.l = l; self.skips = skips
        self.gained = gained; self.value = value
        self.parent = parent; self.action = action
        self.alive = True
        self.window = 0
        self.pending = pending    # a legend ticket was used and no later roll has gained anything new yet

    def node(self):
        return (self.last, self.clock, self.dmask)

    def resources_le(self, o: "Label") -> bool:
        return (self.t <= o.t and self.c <= o.c and self.p <= o.p and self.l <= o.l
                and self.skips <= o.skips and self.pending <= o.pending)

    def actions(self) -> list[tuple]:
        out = []
        lab = self
        while lab.parent is not None:
            out.append(lab.action)
            lab = lab.parent
        out.reverse()
        return out


@dataclass
class SearchStats:
    labels_created: int = 0
    labels_dominated: int = 0
    nodes_expanded: int = 0
    seconds: float = 0.0
    max_offset: int = 0
    truncated: bool = False          # a per-node cap dropped labels: result is heuristic
    pruned_by_bound: int = 0         # labels discarded because they provably cannot beat the incumbent
    proven_optimal: bool = False     # set by search_exact when the bounded full run completed
    improved_over_beam: bool = False
    timed_out: bool = False          # a deadline stopped the run: result is heuristic
    max_labels_at_a_node: int = 0
    per_offset: list = field(default_factory=list)   # (k, nodes, live labels) when tracing


class SearchResult:
    def __init__(self, problem: Problem, labels: list[Label], stats: SearchStats):
        self.problem = problem
        self.labels = labels          # every surviving label, any node
        self.stats = stats

    # ----- readings ----------------------------------------------------------------------
    def finishable(self, lab: Label) -> bool:
        """A label ends a valid plan if the clock is on today, or can be returned within the cap, and its
        last legend ticket has been followed by a roll that gained something new."""
        return not lab.pending and (lab.clock == TODAY or lab.skips < self.problem.max_clock_changes)

    def plan_actions(self, lab: Label) -> list[tuple]:
        acts = lab.actions()
        if lab.clock == TOMORROW:
            acts.append((CLOCK, "today"))
        return acts

    def cost(self, lab: Label) -> float:
        skips = lab.skips + (1 if lab.clock == TOMORROW else 0)
        return self.problem.scalar_cost(lab.t, lab.c, lab.p, skips)

    def candidates(self, tickets=None, cf_units=None, plats=None, legends=None) -> list[Label]:
        P = self.problem
        tickets = P.tickets if tickets is None else tickets
        cf_units = P.cf_units if cf_units is None else cf_units
        plats = P.plats if plats is None else plats
        legends = P.legends if legends is None else legends
        return [lab for lab in self.labels
                if lab.t <= tickets and lab.c <= cf_units and lab.p <= plats and lab.l <= legends
                and self.finishable(lab)]

    def best_value(self, **caps) -> Label | None:
        cands = self.candidates(**caps)
        if not cands:
            return None
        return min(cands, key=lambda lab: (-lab.value, self.cost(lab), lab.skips, lab.k))

    def total(self, lab: Label, future) -> float:
        """Value now plus what the resources this plan leaves unspent are worth on the next banner."""
        P = self.problem
        return lab.value + future.value(lab.k, P.tickets - lab.t, P.cf_units - lab.c, P.plats - lab.p, P.legends - lab.l)

    def best_total(self, future, **caps) -> Label | None:
        """The plan with the most value now plus expected value later (see future.py). Every prefix of
        every explored plan is a candidate, so stopping early is always on the table."""
        cands = self.candidates(**caps)
        if not cands:
            return None
        return min(cands, key=lambda lab: (-self.total(lab, future), self.cost(lab), lab.skips, lab.k))

    def cheapest_covering(self, targets_mask: int | None = None, **caps) -> Label | None:
        targets = self.problem.targets_mask if targets_mask is None else targets_mask
        cands = [lab for lab in self.candidates(**caps) if (lab.gained & targets) == targets]
        if not cands:
            return None
        return min(cands, key=lambda lab: (self.cost(lab), -lab.value, lab.skips, lab.k))

    def near_misses(self, max_missing: int = 3, targets_mask: int | None = None, **caps) -> list[tuple[int, Label]]:
        """For 1..max_missing targets left out, the cheapest label. Returns (missing count, label)."""
        targets = self.problem.targets_mask if targets_mask is None else targets_mask
        out = []
        cands = self.candidates(**caps)
        for m in range(1, max_missing + 1):
            best = None
            for lab in cands:
                if bin(targets & ~lab.gained).count("1") == m:
                    if best is None or (self.cost(lab), -lab.value) < (self.cost(best), -best.value):
                        best = lab
            if best is not None:
                out.append((m, best))
        return out

    def frontier(self, **caps) -> list[Label]:
        """Global Pareto frontier of finished plans over (tickets, cf units, plats, legends, clock changes, value)."""
        cands = sorted(self.candidates(**caps), key=lambda lab: (lab.t, lab.c, lab.p, lab.l, lab.skips, -lab.value))
        kept: list[Label] = []
        for lab in cands:
            if any(o.resources_le(lab) and o.value >= lab.value - 1e-9 for o in kept):
                continue
            kept = [o for o in kept if not (lab.resources_le(o) and lab.value >= o.value - 1e-9)]
            kept.append(lab)
        return kept

    def heatmap(self, max_tickets: int | None = None, max_cf_units: int | None = None):
        """best[t][c] = highest value using at most t tickets and c cat-food units (750 CF each)."""
        P = self.problem
        T = P.tickets if max_tickets is None else max_tickets
        C = P.cf_units if max_cf_units is None else max_cf_units
        best = [[0.0] * (C + 1) for _ in range(T + 1)]
        for lab in self.candidates(tickets=T, cf_units=C):
            if lab.value > best[lab.t][lab.c]:
                best[lab.t][lab.c] = lab.value
        for t in range(T + 1):
            for c in range(C + 1):
                v = best[t][c]
                if t > 0 and best[t - 1][c] > v:
                    v = best[t - 1][c]
                if c > 0 and best[t][c - 1] > v:
                    v = best[t][c - 1]
                best[t][c] = v
        return best

    def envelope(self, **caps) -> list[Label]:
        """Value-versus-cost upper envelope: labels where value strictly increases with cost."""
        cands = sorted(self.candidates(**caps), key=lambda lab: (self.cost(lab), -lab.value))
        out = []
        best = -1.0
        for lab in cands:
            if lab.value > best + 1e-9:
                out.append(lab)
                best = lab.value
        return out

    def knees(self, min_marginal: float = 0.5, **caps) -> list[Label]:
        """Envelope points after which the next gain per draw-equivalent falls below the threshold."""
        env = self.envelope(**caps)
        knees = []
        for i in range(len(env) - 1):
            a, b = env[i], env[i + 1]
            dc = self.cost(b) - self.cost(a)
            dv = b.value - a.value
            if dc > 0 and dv / dc < min_marginal:
                knees.append(a)
        if env and (not knees or knees[-1] is not env[-1]):
            knees.append(env[-1])
        return knees

    def with_unit(self, cat_id: int, **caps) -> list[Label]:
        bit = self.problem.bit(cat_id)
        return [lab for lab in self.candidates(**caps) if lab.gained & bit]


def _value_granularity(values) -> float:
    """Smallest positive difference between two sums of unit values (their common step), or 1e-9.

    Values are scaled to integers in 1e-6 units and the gcd is taken; with the default weights
    0.8 / 1.0 / 5.0 this gives 0.2, so any real improvement over an incumbent is at least 0.2."""
    from math import gcd

    ints = [int(round(v * 1_000_000)) for v in values if v > 0]
    if not ints:
        return 1e-9
    g = 0
    for x in ints:
        g = gcd(g, x)
    return max(g / 1_000_000, 1e-9)


def search(problem: Problem, horizon: int | None = None, progress=None,
           beam: int | None = 12, trace: bool = False, bound=None, incumbent=None,
           deadline: float | None = None) -> SearchResult:
    """Run the search. `beam` caps the labels kept per (node, resource vector) after exact
    dominance; None keeps everything (exact, can be slow). When the cap drops a label the
    result is marked heuristic in stats.truncated. Among equal-value labels the cap keeps
    the ones whose gained units are least likely to reappear later in the stream.
    With `bound` (an UpperBound) and `incumbent` (a best[t][c] grid from an earlier run) a label is
    discarded when its value plus the most it could still gain cannot exceed the incumbent at its
    own spend; that never removes a plan that could improve the value frontier, so beam=None with a
    bound is an exact search whose result is proven optimal."""
    P = problem
    tables = P.tables
    if horizon is None:
        horizon = 2 * P.tickets + 22 * (P.cf_units // 2 + 1) + 2 * P.plats + 2 * P.legends
        horizon = int(horizon * 1.1) + 8
    tables.ensure(horizon + 80)
    P.unit_masks_per_offset(horizon)
    mask_value = P.mask_value
    window_mask = P.window_mask
    reach = P.reach

    stats = SearchStats()
    t0 = time.perf_counter()
    buckets: dict[int, dict[tuple, list[Label]]] = {}
    all_labels: list[Label] = []
    single_cache: dict[tuple, object] = {}
    eleven_cache: dict[tuple, object] = {}
    current = {"k": -1, "nodes": None}

    def covers(a: Label, b: Label) -> bool:
        """The value part of dominance, for labels whose resources are already known to compare."""
        if a.value + 1e-9 < b.value:
            return False
        diff = a.gained & ~b.gained & b.window
        if not diff:
            return True
        return a.value - b.value >= mask_value(diff) - 1e-9

    def insert(lab: Label) -> bool:
        """Labels at a node are kept in groups by resource vector (tickets, cat food, platinum, legend
        tickets, clock changes), so a dominance check only visits the groups whose resources compare."""
        lab.window = window_mask(lab.k, lab.k + reach(lab.t, lab.c, lab.p, lab.l))
        if bound is not None and incumbent is not None and not bound_allows(lab):
            stats.pruned_by_bound += 1
            return False
        if lab.k == current["k"]:
            nodes = current["nodes"]
        else:
            nodes = buckets.setdefault(lab.k, {})
        groups = nodes.setdefault(lab.node(), {})
        t, c, p, l, sk, pd = lab.t, lab.c, lab.p, lab.l, lab.skips, lab.pending
        for rv, ls in groups.items():
            if rv[0] <= t and rv[1] <= c and rv[2] <= p and rv[3] <= l and rv[4] <= sk and rv[5] <= pd:
                for o in ls:
                    if covers(o, lab):
                        stats.labels_dominated += 1
                        return False
        for rv, ls in groups.items():
            if t <= rv[0] and c <= rv[1] and p <= rv[2] and l <= rv[3] and sk <= rv[4] and pd <= rv[5]:
                kept = []
                for o in ls:
                    if covers(lab, o):
                        o.alive = False
                        stats.labels_dominated += 1
                    else:
                        kept.append(o)
                if len(kept) != len(ls):
                    groups[rv] = kept
        groups.setdefault((t, c, p, l, sk, pd), []).append(lab)
        if beam is not None:
            bk = beam_key(lab)
            group = [o for rv, ls in groups.items() if beam_key_of(rv) == bk for o in ls]
            if len(group) > beam:
                group.sort(key=lambda x: (-x.value, x.skips, mask_value(x.gained & x.window)))
                touched = set()
                for o in group[beam:]:
                    o.alive = False
                    if o.value > 0:
                        stats.truncated = True
                    touched.add((o.t, o.c, o.p, o.l, o.skips, o.pending))
                for rv in touched:
                    groups[rv] = [o for o in groups[rv] if o.alive]
                if not lab.alive:
                    stats.labels_dominated += 1
                    return False
        n = sum(len(ls) for ls in groups.values())
        if n > stats.max_labels_at_a_node:
            stats.max_labels_at_a_node = n
        all_labels.append(lab)
        stats.labels_created += 1
        return True

    value_step = _value_granularity(list(P.unit_value) + [v for v in P.dupe_values.values() if v > 0]
                                    + [v for v in P.pass_penalties.values() if v > 0]
                                    + ([P.ticket_cost] if P.ticket_cost > 0 else []))
    dupe_max = max([0.0] + [v for v in P.dupe_values.values()])

    def bound_allows(lab: Label) -> bool:
        """Could some continuation of this label beat the incumbent at any spend level it can end at?

        Two caps are combined: the relaxed dynamic-programme bound for exactly the extra resources
        that would be spent, and the total value of units not yet gained that can still appear in the
        label's window (each unit counts once). If neither leaves room above the incumbent for every
        possible final spend (t', c'), no continuation can improve the value frontier."""
        room_units = mask_value(lab.window & ~lab.gained)
        pl, ll = P.plats - lab.p, P.legends - lab.l
        need = value_step - 1e-9      # an improvement must be at least the smallest step between values
        for t2 in range(lab.t, P.tickets + 1):
            for c2 in range(lab.c, P.cf_units + 1):
                # with duplicate values every remaining roll may add dupe_max on top of the new units
                room = room_units + dupe_max * ((t2 - lab.t) + 11 * (c2 - lab.c) + pl + ll)
                cap = lab.value + min(bound.ub(lab.k, t2 - lab.t, c2 - lab.c, pl, ll, lab.dmask), room)
                if cap >= incumbent[t2][c2] + need:
                    return True
        return False

    cap = P.max_clock_changes

    def beam_key_of(rv: tuple):
        """Labels that compete for the same beam slots: same spend, and (by default) the same answer to
        "can this plan still change the date", so plans that kept that freedom are not crowded out by
        plans that have used it up. `rv` is a resource vector (t, c, p, l, skips)."""
        if BEAM_SKIPS == "full":
            return rv
        if BEAM_SKIPS == "none":
            return rv[:4]
        return (rv[0], rv[1], rv[2], rv[3], rv[4] + 1 >= cap)

    def beam_key(lab: Label):
        return beam_key_of((lab.t, lab.c, lab.p, lab.l, lab.skips))

    def other_day(lab: Label):
        """The label after a clock change, when one is allowed: the date may go forward only while
        the plan can still come back within the cap, and only when tomorrow has banners today lacks.
        The result is the parent of the roll that follows, never a candidate of its own."""
        if lab.clock == TODAY:
            if not P.tomorrow_adds_banners or lab.skips + 2 > cap:
                return None
            return Label(lab.k, lab.last, TOMORROW, lab.dmask, lab.t, lab.c, lab.p, lab.l, lab.skips + 1,
                         lab.gained, lab.value, lab, (CLOCK, "tomorrow"))
        if lab.skips + 1 > cap:
            return None
        return Label(lab.k, lab.last, TODAY, lab.dmask, lab.t, lab.c, lab.p, lab.l, lab.skips + 1,
                     lab.gained, lab.value, lab, (CLOCK, "today"))

    def cached_single(b, k, last):
        key = (b.event_id, k, last)
        r = single_cache.get(key)
        if r is None:
            r = single(tables, b, k, last)
            single_cache[key] = r
        return r

    def cached_eleven(b, k, last):
        key = (b.event_id, k, last)
        r = eleven_cache.get(key)
        if r is None:
            r = eleven(tables, b, k, last, b.guaranteed_rolls)
            eleven_cache[key] = r
        return r

    def expand(lab: Label, worklist: list):
        k, gained = lab.k, lab.gained
        stats.nodes_expanded += 1

        # Mandatory legend ticket: the only roll allowed here.
        must = P.legend_mandatory(k, gained, lab.l)
        if must:
            r = cached_single(P.legend, k, 0)
            bit, dv = P.gain(r.cat_id, r.rarity, gained)
            v = lab.value + dv - P.pass_penalty(k, r.offset_after, (k,), gained | bit)
            insert(Label(r.offset_after, 0, lab.clock, lab.dmask, lab.t, lab.c, lab.p, lab.l + 1,
                         lab.skips, gained | bit, v, lab, (LEGEND,), P.legend_substitute_only))
            return

        # Single rolls and 11-draws on rare banners; a banner only the other day has is rolled
        # through a clock change made right before it (its label is the roll's parent)
        flipped = None
        for b in P.rare_banners:
            if P.banner_live(b.event_id, lab.clock):
                src = lab
            else:
                if flipped is None:
                    flipped = other_day(lab) or False
                if flipped is False or not P.banner_live(b.event_id, flipped.clock):
                    continue
                src = flipped
            if lab.t < P.tickets:
                r = cached_single(b, k, lab.last)
                bit, dv = P.gain(r.cat_id, r.rarity, gained)
                v = lab.value + dv - P.pass_penalty(k, r.offset_after, (k,), gained | bit) - P.ticket_cost
                insert(Label(r.offset_after, P.canonical_last(r.offset_after, next_last_rare(r)),
                             src.clock, lab.dmask, lab.t + 1, lab.c, lab.p, lab.l, src.skips,
                             gained | bit, v, src, (SINGLE, b.event_id), lab.pending and not bit))
            if b.offers_eleven:
                cost = P.eleven_cost_units(b, lab.dmask)
                if lab.c + cost <= P.cf_units:
                    rolls, g, k2, last2 = cached_eleven(b, k, lab.last)
                    if P.forbid_eleven_over_legend_slot and P.legend is not None and lab.l < P.legends:
                        blocked = False
                        for r in rolls:
                            if P.legend_allowed(r.offset_before, gained):
                                blocked = True
                                break
                        if not blocked and g is not None and P.legend_allowed(g.offset_before, gained):
                            blocked = True
                        if blocked:
                            continue
                    g2 = gained
                    v = lab.value
                    for r in rolls:
                        bit, dv = P.gain(r.cat_id, r.rarity, g2)
                        g2 |= bit
                        v += dv
                    if g is not None:
                        bit, dv = P.gain(g.cat_id, "uber", g2)
                        g2 |= bit
                        v += dv
                    v -= P.pass_penalty(k, k2, {r.offset_before for r in rolls} | ({g.offset_before} if g is not None else set()), g2)
                    dmask = P.dmask_after_eleven(lab.dmask)
                    insert(Label(k2, P.canonical_last(k2, last2), src.clock, dmask, lab.t, lab.c + cost,
                                 lab.p, lab.l, src.skips, g2, v, src, (ELEVEN, b.event_id),
                                 lab.pending and g2 == gained))

        # Platinum ticket
        if P.plat is not None and lab.p < P.plats:
            r = cached_single(P.plat, k, 0)
            bit, dv = P.gain(r.cat_id, r.rarity, gained)
            v = lab.value + dv - P.pass_penalty(k, r.offset_after, (k,), gained | bit)
            insert(Label(r.offset_after, 0, lab.clock, lab.dmask, lab.t, lab.c, lab.p + 1, lab.l,
                         lab.skips, gained | bit, v, lab, (PLAT,), lab.pending and not bit))

    start = Label(0, P.canonical_last(0, P.last_id), TODAY, 0, 0, 0, 0, 0, 0, 0, 0.0, None, None)
    insert(start)

    limit = horizon + 40
    while buckets:
        k = min(buckets)
        if k > limit:
            break
        if deadline is not None and time.perf_counter() > deadline:
            stats.truncated = True
            stats.timed_out = True
            break
        nodes = buckets.pop(k)
        current["k"], current["nodes"] = k, nodes
        worklist = [lab for groups in nodes.values() for ls in groups.values() for lab in ls if lab.alive]
        while worklist:
            lab = worklist.pop()
            if not lab.alive:
                continue
            expand(lab, worklist)
        current["k"], current["nodes"] = -1, None
        stats.max_offset = k
        if trace:
            stats.per_offset.append((k, len(nodes), sum(1 for groups in nodes.values() for ls in groups.values()
                                                       for x in ls if x.alive)))
        if progress is not None:
            progress(k, horizon)

    stats.seconds = time.perf_counter() - t0
    survivors = [lab for lab in all_labels if lab.alive]
    return SearchResult(problem, survivors, stats)


# ---------------------------------------------------------------------------------------
# Exact mode: beam first, then a bounded full search that can only find improvements
# ---------------------------------------------------------------------------------------

def search_exact(problem: Problem, beam_first: int = 30, progress=None, horizon: int | None = None,
                 time_limit: float | None = None):
    """Provably optimal value frontier.

    1. A wide beam run produces strong incumbents best[t][c].
    2. A full run with no beam uses the relaxed upper bound (bounds.UpperBound) to discard every
       partial plan that cannot beat the incumbent at any spend it could end at. That pruning is
       sound, so whatever survives plus the incumbents is the true frontier. The two label sets are
       merged; `stats.proven_optimal` is True when the full run was not truncated.
    """
    from .bounds import UpperBound

    first = search(problem, beam=beam_first, progress=progress, horizon=horizon)
    if not first.stats.truncated:
        first.stats.proven_optimal = True      # the beam never dropped a label: the run was already exact
        return first
    grid = first.heatmap()
    deadline = time.perf_counter() + time_limit if time_limit else None
    bound = UpperBound(problem, deadline=deadline)
    full = search(problem, beam=None, bound=bound, incumbent=grid, progress=progress, horizon=horizon,
                  deadline=deadline)
    if bound.timed_out:
        full.stats.timed_out = True
    if full.stats.timed_out:
        first.stats.timed_out = True           # keep the beam result; the proof did not finish in time
        return first
    merged = SearchResult(problem, first.labels + full.labels, full.stats)
    merged.stats.seconds += first.stats.seconds
    merged.stats.labels_created += first.stats.labels_created
    merged.stats.truncated = first.stats.truncated and full.stats.truncated   # the full run is exact
    merged.stats.proven_optimal = not full.stats.truncated
    merged.stats.improved_over_beam = (full.best_value() is not None and first.best_value() is not None
                                       and full.best_value().value > first.best_value().value + 1e-9)
    return merged


def coverage_problem(problem: Problem) -> Problem:
    """A copy of the problem whose only valued units are today's coverage targets, one point each,
    so the max-value frontier of this problem is the max-targets frontier of the original."""
    from dataclasses import replace

    targets = set(problem.mask_ids(problem.targets_mask))
    zero = {cid: 0.0 for cid in problem.unit_rarity if cid not in targets}
    weights = {"rare": 1.0, "supa": 1.0, "uber": 1.0, "legend": 1.0}
    cp = replace(problem, weights=weights, multipliers=zero, dupe_values={}, pass_penalties={}, ticket_cost=0.0)
    cp.tables = problem.tables          # share the seed stream and its caches
    return cp

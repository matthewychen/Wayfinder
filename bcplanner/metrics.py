"""Per-plan metrics computed from an independent replay (PLAN.md section 5.7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE
from .model import BASE, RARITIES, Banner
from .problem import Problem
from .replay import ReplayResult
from .sim import single


@dataclass
class Metrics:
    value: float = 0.0
    new_by_rarity: dict[str, int] = field(default_factory=dict)
    new_units: list[int] = field(default_factory=list)
    tickets: int = 0
    cat_food: int = 0
    plats: int = 0
    legends: int = 0
    clock_changes: int = 0
    banner_switches: int = 0
    cost_draw_equivalents: float = 0.0
    value_per_draw_equivalent: float = 0.0
    dupe_ubers: int = 0               # uber-or-legend results that were already owned or already gained
    uber_slots_passed: int = 0        # single tickets rolled where another open banner had a new uber/legend
    eleven_rolls_new_elsewhere: int = 0  # rolls inside an 11-draw where another open banner had a new uber/legend
    legend_slots_used: int = 0        # positions where the plan obtained a legend (ticket or banner roll)
    legend_slots_passed: int = 0      # legend-ticket slots with an unowned legend that the plan spent on something else
    rolls: int = 0
    uber_slots_skipped: int = 0       # uber slots (every banner) on the other track the path went past
    fest_slots_skipped: int = 0       # Uberfest-only uber slots on the other track the path went past
    legend_slots_skipped: int = 0     # legend slots on the other track the path went past
    pass_penalty: float = 0.0         # opportunity cost charged for them (already inside `value`)
    new_value: float = 0.0            # value of the new units alone (no repeats, penalties or ticket costs)
    straight_value: float = 0.0       # the same spend pulled straight on one banner: new-unit value on average
    straight_banner: str = ""         # the banner open today that does best pulled straight
    improvement: float = 0.0          # new_value / straight_value (0 when there is nothing to compare)


def compute(problem: Problem, rep: ReplayResult) -> Metrics:
    P = problem
    m = Metrics()
    m.value = rep.value
    m.new_units = list(rep.gained)
    for cid in rep.gained:
        r = P.unit_rarity.get(cid, "rare")
        m.new_by_rarity[r] = m.new_by_rarity.get(r, 0) + 1
    m.tickets, m.plats, m.legends, m.clock_changes = rep.tickets, rep.plats, rep.legends, rep.clock_changes
    m.cat_food = rep.cf_units * 750
    m.cost_draw_equivalents = rep.tickets / P.tickets_per_draw + rep.cf_units / 2
    m.value_per_draw_equivalent = rep.value / m.cost_draw_equivalents if m.cost_draw_equivalents > 0 else 0.0
    m.new_value = sum(P.value_of(cid) for cid in rep.gained)
    elevens = sum(1 for s in rep.steps if s.action[0] == ELEVEN)
    m.straight_value, m.straight_banner = straight_value(P, rep.tickets, elevens, rep.plats, rep.legends)
    if m.straight_value > 1e-9:
        m.improvement = m.new_value / m.straight_value

    gained_so_far: set[int] = set()
    last_banner = None
    plats_left, legends_left = P.plats, P.legends
    for step in rep.steps:
        for _p, band, _kind in step.passed:
            if band == "uber":
                m.uber_slots_skipped += 1
            elif band == "uber_fest":
                m.fest_slots_skipped += 1
            elif band == "legend":
                m.legend_slots_skipped += 1
        m.pass_penalty += step.penalty
        kind = step.action[0]
        if kind == CLOCK:
            continue
        banner_id = step.action[1] if kind in (SINGLE, ELEVEN) else kind
        if last_banner is not None and banner_id != last_banner:
            m.banner_switches += 1
        last_banner = banner_id
        for rv in step.rolls:
            m.rolls += 1
            is_top = rv.rarity in ("uber", "legend")
            if is_top and not rv.new:
                m.dupe_ubers += 1
            # would another open banner have given a new uber or legend at this very position?
            k = rv.offset_before
            if not rv.new and rv.source == "roll" and _other_banner_new_top(P, k, step.day_offset, gained_so_far, rv):
                if kind == SINGLE:
                    m.uber_slots_passed += 1          # a single ticket could have been rolled there instead
                else:
                    m.eleven_rolls_new_elsewhere += 1  # inside an 11-draw: no per-roll choice
            if rv.rarity == "legend" and rv.source in ("legend", "roll"):
                m.legend_slots_used += 1
            elif P.legend is not None and _new_legend(P, k, gained_so_far):
                m.legend_slots_passed += 1        # a legend ticket here would have given a new legend
            if rv.new:
                gained_so_far.add(rv.cat_id)
        if kind == PLAT:
            plats_left -= 1
        elif kind == LEGEND:
            legends_left -= 1
    return m


def roll_chances(b: Banner) -> dict[int, float]:
    """cat id -> chance that one roll on banner b gives it (the banner's rates, every slot of a pool equally likely)."""
    out: dict[int, float] = {}
    for i, rarity in enumerate(RARITIES):
        pool = b.pool(rarity)
        if pool and b.rates[i]:
            for cid in pool:
                out[cid] = out.get(cid, 0.0) + b.rates[i] / BASE / len(pool)
    return out


def straight_value(P: Problem, tickets: int, elevens: int, plats: int, legends: int) -> tuple[float, str]:
    """(new-unit value on average, banner) for a spend pulled with no planning: every rare ticket and 11-draw
    straight on one banner open today, the best one for it, and platinum and legend tickets as they come.

    A unit counts once, so its share is value x chance of at least one copy; a guaranteed draw gives one
    uber from the banner's uber pool after its ordinary rolls, as in the game."""
    if not (tickets or elevens or plats or legends):
        return 0.0, ""
    base: dict[int, float] = {}          # cat id -> chance of no copy from the platinum and legend tickets
    for b, n in ((P.plat, plats), (P.legend, legends)):
        if b is not None and n:
            for cid, ch in roll_chances(b).items():
                base[cid] = base.get(cid, 1.0) * (1.0 - ch) ** n

    def value(miss: dict[int, float]) -> float:
        return sum(P.unit_value[P.unit_index[cid]] * (1.0 - q) for cid, q in miss.items() if cid in P.unit_index)

    best = (value(base), "")
    if not (tickets or elevens):
        return best
    for b in P.rare_banners:
        if not P.live[b.event_id][0]:
            continue
        g = b.guaranteed_rolls if b.guaranteed_rolls in (11, 15) else 0
        rolls = tickets + elevens * (g - 1 if g else 11)
        miss = dict(base)
        for cid, ch in roll_chances(b).items():
            miss[cid] = miss.get(cid, 1.0) * (1.0 - ch) ** rolls
        ubers = b.pool("uber")
        if g and elevens and ubers:
            for cid in ubers:
                miss[cid] = miss.get(cid, 1.0) * (1.0 - 1.0 / len(ubers)) ** elevens
        v = value(miss)
        if v > best[0] + 1e-12:
            best = (v, b.event_id)
    return best


def _new_legend(P: Problem, k: int, gained: set[int]) -> int:
    """The legend a legend ticket was allowed to take at k under the plan's rule, or 0."""
    if P.legend is None:
        return 0
    mask = 0
    for cid in gained:
        mask |= P.bit(cid)
    return P.legend_allowed(k, mask)


def _other_banner_new_top(P: Problem, k: int, clock: int, gained: set[int], actual) -> bool:
    """True when another rare banner open at this moment would have given a new uber or legend for a
    roll at this position. Platinum and legend tickets are deliberately not counted: a ticket can be
    used once, so "a platinum ticket here would have been an uber" is true at nearly every position
    and says nothing about the plan (the Options tab lists where a platinum ticket could go)."""
    for b in P.rare_banners:
        if not P.banner_live(b.event_id, clock) or b.event_id == actual.banner:
            continue
        rarity, _, cid = P.tables.cat_at(b, k)
        if rarity in ("uber", "legend") and cid >= 0 and cid not in P.owned and cid not in gained and P.value_of(cid) > 0:
            return True
    return False

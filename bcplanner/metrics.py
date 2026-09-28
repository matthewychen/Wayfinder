"""Per-plan metrics computed from an independent replay (PLAN.md section 5.7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE
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

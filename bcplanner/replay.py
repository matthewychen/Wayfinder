"""Independent replay of an action list: results, resources, legality, metrics inputs.

Shares only the roll primitives (sim.py) and the rule helpers (problem.py) with
the search. Anything the search claims must be reproduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE, TODAY, TOMORROW
from .problem import Problem
from .sim import eleven, next_last_rare, single


@dataclass
class RollView:
    source: str            # "roll" | "guaranteed" | "plat" | "legend"
    banner: str
    offset_before: int
    label: str             # site position, e.g. 7B (with G for a guaranteed)
    cat_id: int
    rarity: str
    new: bool
    rerolled: bool = False
    duped_cat_id: int = 0


@dataclass
class Step:
    index: int
    action: tuple
    day_offset: int        # 0 = today, 1 = tomorrow
    offset_before: int
    offset_after: int
    rolls: list[RollView] = field(default_factory=list)
    tickets_after: int = 0
    cf_units_after: int = 0
    plats_after: int = 0
    legends_after: int = 0
    value_after: float = 0.0
    seed_after: int = 0    # S[offset_after], the seed to paste into bc.godfat.org for this state
    last_after: int = 0
    passed: list[tuple[int, str, str]] = field(default_factory=list)   # (offset, band, "new" | "repeat" | "") of uber slots gone past
    penalty: float = 0.0   # opportunity cost charged for them


@dataclass
class ReplayResult:
    steps: list[Step]
    gained: list[int]
    value: float
    tickets: int
    cf_units: int
    plats: int
    legends: int
    clock_changes: int
    problems: list[str]
    end_offset: int
    end_last: int


def replay(problem: Problem, actions: list[tuple]) -> ReplayResult:
    P = problem
    tables = P.tables
    k, last, clock, dmask = 0, P.last_id, TODAY, 0
    t = c = p = l = skips = 0
    pending = False          # a legend ticket was used and nothing new has been gained since
    gained: list[int] = []
    gained_set: set[int] = set()
    value = 0.0
    steps: list[Step] = []
    problems: list[str] = []

    def take(cat_id: int, rarity: str = "") -> tuple[bool, float]:
        """Record a unit; returns (is_new, value added): a repeat earns the duplicate value of its rarity."""
        nonlocal pending
        if cat_id < 0:
            return False, 0.0
        if cat_id in P.owned or cat_id in gained_set:
            return False, P.dupe_value(rarity)
        v = P.value_of(cat_id)
        if v <= 0:
            return False, 0.0
        gained_set.add(cat_id)
        gained.append(cat_id)
        pending = False
        return True, v

    def gained_mask() -> int:
        m = 0
        for cid in gained_set:
            m |= P.bit(cid)
        return m

    def passed_slots(step: Step, k0: int, k1: int, landed) -> None:
        """Charge the uber slots the step went past without landing on them (the other track)."""
        nonlocal value
        gm = gained_mask()
        for p in P.passed(k0, k1, landed):
            band = P.slot_band(p)
            if band:
                kind = "new" if P.passed_new_top(p, gm) else ("repeat" if P.pass_cost(p, gm) > 0 else "")
                step.passed.append((p, band, kind))
        step.penalty = P.pass_penalty(k0, k1, landed, gm)
        value -= step.penalty

    for i, action in enumerate(actions, start=1):
        kind = action[0]
        step = Step(index=i, action=action, day_offset=clock, offset_before=k, offset_after=k)
        if kind == CLOCK:
            target = TOMORROW if action[1] == "tomorrow" else TODAY
            if target == clock:
                problems.append(f"step {i}: clock already on {'tomorrow' if clock else 'today'}")
            elif skips >= P.max_clock_changes:
                problems.append(f"step {i}: exceeds the clock-change cap of {P.max_clock_changes}")
            clock = target
            skips += 1
        elif kind in (SINGLE, ELEVEN):
            b = P.banners.get(action[1])
            if b is None or not b.include or b.kind != "rare":
                problems.append(f"step {i}: banner {action[1]} is not an included rare banner")
                continue
            if not P.banner_live(b.event_id, clock):
                problems.append(f"step {i}: {b.name} is not open on {'tomorrow' if clock else 'today'}")
            must = P.legend_mandatory(k, gained_mask(), l)
            if must:
                problems.append(f"step {i}: legend slot at {tables and k} with a new legend ({must}) skipped")
            if kind == SINGLE:
                if t >= P.tickets:
                    problems.append(f"step {i}: no rare tickets left")
                t += 1
                value -= P.ticket_cost
                r = single(tables, b, k, last)
                new, v = take(r.cat_id, r.rarity)
                value += v
                step.rolls.append(RollView("roll", b.event_id, r.offset_before, r.label, r.cat_id, r.rarity, new,
                                           r.rerolled, r.duped_cat_id))
                k, last = r.offset_after, next_last_rare(r)
                passed_slots(step, step.offset_before, k, (step.offset_before,))
            else:
                if not b.offers_eleven:
                    problems.append(f"step {i}: {b.name} offers no 11-draw")
                cost = P.eleven_cost_units(b, dmask)
                if c + cost > P.cf_units:
                    problems.append(f"step {i}: not enough cat food ({(P.cf_units - c) * 750} CF left)")
                c += cost
                dmask = P.dmask_after_eleven(dmask)
                rolls, g, k2, last2 = eleven(tables, b, k, last, b.guaranteed_rolls)
                if P.forbid_eleven_over_legend_slot and P.legend is not None and l < P.legends:
                    offsets = [r.offset_before for r in rolls] + ([g.offset_before] if g else [])
                    gm = gained_mask()
                    hit = [o for o in offsets if P.legend_allowed(o, gm)]
                    if hit:
                        problems.append(f"step {i}: 11-draw rolls over a legend slot at offset {hit[0]}")
                for r in rolls:
                    new, v = take(r.cat_id, r.rarity)
                    value += v
                    step.rolls.append(RollView("roll", b.event_id, r.offset_before, r.label, r.cat_id, r.rarity, new,
                                               r.rerolled, r.duped_cat_id))
                if g is not None:
                    new, v = take(g.cat_id, "uber")
                    value += v
                    step.rolls.append(RollView("guaranteed", b.event_id, g.offset_before, g.label, g.cat_id, "uber", new))
                k, last = k2, last2
                passed_slots(step, step.offset_before, k2,
                             {r.offset_before for r in rolls} | ({g.offset_before} if g is not None else set()))
        elif kind == PLAT:
            if P.plat is None:
                problems.append(f"step {i}: no platinum banner loaded")
                continue
            if p >= P.plats:
                problems.append(f"step {i}: no platinum tickets left")
            must = P.legend_mandatory(k, gained_mask(), l)
            if must:
                problems.append(f"step {i}: legend slot with a new legend ({must}) skipped for a platinum pull")
            p += 1
            r = single(tables, P.plat, k, 0)
            new, v = take(r.cat_id, r.rarity)
            value += v
            step.rolls.append(RollView("plat", P.plat.event_id, r.offset_before, r.label, r.cat_id, r.rarity, new))
            k, last = r.offset_after, 0
            passed_slots(step, step.offset_before, k, (step.offset_before,))
        elif kind == LEGEND:
            if P.legend is None:
                problems.append(f"step {i}: no legend banner loaded")
                continue
            if l >= P.legends:
                problems.append(f"step {i}: no legend tickets left")
            if not P.legend_allowed(k, gained_mask()):
                problems.append(f"step {i}: legend ticket used where the rule does not allow it (a new legend, "
                                f"and a repeat uber there on every open banner)")
            l += 1
            r = single(tables, P.legend, k, 0)
            new, v = take(r.cat_id, r.rarity)
            value += v
            pending = P.legend_substitute_only
            step.rolls.append(RollView("legend", P.legend.event_id, r.offset_before, r.label, r.cat_id, r.rarity, new))
            k, last = r.offset_after, 0
            passed_slots(step, step.offset_before, k, (step.offset_before,))
        else:
            problems.append(f"step {i}: unknown action {action!r}")
            continue
        tables.ensure(k)
        step.offset_after = k
        step.tickets_after, step.cf_units_after, step.plats_after, step.legends_after = t, c, p, l
        step.value_after = value
        step.seed_after = tables.S[k]
        step.last_after = last
        steps.append(step)

    if clock != TODAY:
        problems.append("plan does not end with the device date set back to today")
    if pending:
        problems.append("the last legend ticket is not followed by a roll that gains something new: a legend "
                        "ticket only replaces a rare ticket on the way to something better")
    return ReplayResult(steps=steps, gained=gained, value=value, tickets=t, cf_units=c, plats=p, legends=l,
                        clock_changes=skips, problems=problems, end_offset=k, end_last=last)


def day_for(problem: Problem, day_offset: int):
    return problem.today + timedelta(days=day_offset)

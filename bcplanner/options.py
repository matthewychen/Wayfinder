"""A few readable spending options instead of a heatmap (PLAN.md section 5.6, revised).

Rows answer: "what do I get for nothing, for one 11-draw, for two, ... and do my platinum
tickets add anything?" Each row is a full plan (replayed and checked) so it can be followed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .prng import site_label
from .actions import ELEVEN
from .problem import Problem
from .search import Label, SearchResult
from .session import Plan, make_plan
from .sim import single


@dataclass
class Option:
    title: str
    plan: Plan
    tickets: int
    cat_food: int
    plats: int
    legends: int
    value: float
    new_top: list[int]          # new ubers and legends, ids
    new_supa: int
    delta_value: float          # versus the row above
    note: str = ""
    later: float = 0.0          # expected value of what this row leaves unspent, on the next banner
    total: float = 0.0          # value + later
    alt: "Option | None" = None  # the plan with the most new ubers/legends at this spend, when it gets more than this row
    new_rare: int = 0           # new rares gained (worth a new super each)


def _summarise(problem: Problem, res: SearchResult, lab: Label, title: str, prev_value: float, note: str = "",
               future=None) -> Option:
    plan = make_plan(problem, res, lab, title, future)
    top = [cid for cid in plan.replay.gained if problem.unit_rarity.get(cid) in ("uber", "legend")]
    supa = sum(1 for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "supa")
    rare = sum(1 for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "rare")
    later = res.total(lab, future) - lab.value if future is not None else 0.0
    return Option(title=title, plan=plan, tickets=lab.t, cat_food=lab.c * 750, plats=lab.p, legends=lab.l,
                  value=lab.value, new_top=top, new_supa=supa, new_rare=rare, delta_value=lab.value - prev_value,
                  note=note, later=later, total=lab.value + later)


def top_mask_of(problem: Problem) -> int:
    mask = 0
    for cid in problem.unit_ids:
        if problem.unit_rarity.get(cid) in ("uber", "legend"):
            mask |= problem.bit(cid)
    return mask


def most_new_tops(res: SearchResult, top_mask: int, **caps) -> Label | None:
    """The candidate plan that collects the most new ubers and legends (value breaks ties)."""
    cands = res.candidates(**caps)
    if not cands:
        return None
    return max(cands, key=lambda lab: (bin(lab.gained & top_mask).count("1"), lab.value, -lab.t))


def spending_options(problem: Problem, res: SearchResult, future=None) -> list[Option]:
    """One row per cat-food level (0, 1 draw, 2 draws, ...): the best plan that spends exactly that much
    cat food, by value now plus what is kept (when the next banner is weighed), so the rows answer
    "what does one draw get me, what do two" even when keeping everything scores highest. Each row also
    carries, as `alt`, the plan with the most new ubers at that level when it beats the row's count, so
    "there was a way to get one more" is always visible together with what it would cost."""
    P = problem
    out: list[Option] = []
    prev = 0.0
    tops = top_mask_of(P)
    weigh = future is not None and future.m.mode != "none"
    all_cands = res.candidates()
    levels = sorted({lab.c for lab in all_cands})   # every amount some plan spends: 0, 2, 4 ... or 0, 1, 3, 5 ... with a discounted first draw
    for units in levels:
        cands = [lab for lab in all_cands if lab.c == units]
        score = (lambda lab: res.total(lab, future)) if weigh else (lambda lab: lab.value)
        lab = min(cands, key=lambda lab: (-score(lab), res.cost(lab), lab.skips, lab.k))
        n = sum(1 for a in lab.actions() if a[0] == ELEVEN)
        if units == 0:
            title = "Tickets only (no cat food)"
        elif n == 1:
            title = f"One 11-draw ({units * 750} CF)"
        else:
            title = f"{n} 11-draws ({units * 750} CF)"
        row = _summarise(P, res, lab, title, prev, future=future)
        more = max(cands, key=lambda lab: (bin(lab.gained & tops).count("1"), lab.value, -lab.t))
        if bin(more.gained & tops).count("1") > len(row.new_top):
            row.alt = _summarise(P, res, more, "most new ubers", lab.value, future=future)
        out.append(row)
        prev = lab.value
    return out


@dataclass
class PlatPosition:
    offset: int
    label: str                  # site position, e.g. 12B
    cat_id: int
    new: bool                   # not owned before the plan
    gained_in_plan: bool        # the shown plan already obtains it elsewhere, so it would repeat
    priority: bool              # on the uber priority list
    step: int | None            # the plan step that starts at this position (a plat could go in before it)


def platinum_positions(problem: Problem, plan: Plan | None, priority: set[int], extra: int = 30) -> list[PlatPosition]:
    """Every position a platinum ticket could be used at, from the start to a little past the plan's
    end: the uber it gives, whether that uber is new, whether it is on the uber priority list, and
    which step of the plan starts there. Sorted with priority ubers first, then other new ubers, then
    by position, so the best places to spend a platinum ticket are at the top."""
    P = problem
    if P.plat is None:
        return []
    end = (plan.replay.end_offset if plan is not None else 0) + extra
    P.tables.ensure(end + 4)
    step_at = {st.offset_before: st.index for st in plan.replay.steps} if plan is not None else {}
    gained = set(plan.replay.gained) if plan is not None else set()
    out = []
    for k in range(0, end + 1):
        r = single(P.tables, P.plat, k, 0)
        if r.cat_id <= 0:
            continue
        out.append(PlatPosition(k, site_label(k), r.cat_id, r.cat_id not in P.owned, r.cat_id in gained,
                                r.cat_id in priority, step_at.get(k)))
    out.sort(key=lambda x: (not x.priority, not x.new, x.gained_in_plan, x.offset))
    return out


def platinum_options(problem: Problem, res: SearchResult) -> list[Option]:
    """What the platinum tickets add: best plan with none versus with all of them."""
    P = problem
    if P.plats <= 0:
        return []
    without = res.best_value(plats=0)
    with_all = res.best_value()
    out = []
    if without is not None:
        out.append(_summarise(P, res, without, "Without platinum tickets", 0.0))
    if with_all is not None:
        prev = without.value if without is not None else 0.0
        note = "" if with_all.p > 0 else "the best plan does not need them"
        out.append(_summarise(P, res, with_all, f"Using up to {P.plats} platinum ticket{'s' if P.plats > 1 else ''}", prev, note))
    return out

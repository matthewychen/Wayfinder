"""Priority units: steer which banner a single ticket is rolled on, and nothing else.

After the search has chosen a plan, every single-ticket roll is re-examined. If another
banner open at that moment would give a unit from the priority list at the same offset,
and switching to it changes nothing else in the plan (every later result identical,
resources identical, no unit lost), the banner is swapped. With `priority_allow_skip`
a one-day clock change may be inserted around the roll to reach a banner open on the
other day. Plans are re-run through the independent replay after every swap.
"""

from __future__ import annotations

from .actions import CLOCK, SINGLE, TODAY, TOMORROW
from .problem import Problem
from .replay import ReplayResult, replay
from .sim import single


def _collapse_clocks(actions: list[tuple]) -> list[tuple]:
    """Drop adjacent clock changes that cancel out, e.g. ('clock','today'),('clock','tomorrow')."""
    out: list[tuple] = []
    for a in actions:
        if out and a[0] == CLOCK and out[-1][0] == CLOCK and out[-1][1] != a[1]:
            out.pop()
            continue
        out.append(a)
    return out


def _rolls(rep: ReplayResult) -> list[tuple]:
    return [(rv.source, rv.offset_before, rv.cat_id) for st in rep.steps for rv in st.rolls]


def _same_except(base: ReplayResult, cand: ReplayResult, swapped_offset: int) -> bool:
    """True if the candidate plan matches the base plan everywhere except the swapped single."""
    a, b = _rolls(base), _rolls(cand)
    if len(a) != len(b):
        return False
    for (sa, oa, ca), (sb, ob, cb) in zip(a, b):
        if sa != sb or oa != ob:
            return False
        if ca != cb and not (sa == "roll" and oa == swapped_offset):
            return False
    if (cand.tickets, cand.cf_units, cand.plats, cand.legends) != (base.tickets, base.cf_units, base.plats, base.legends):
        return False
    if cand.end_offset != base.end_offset or cand.end_last != base.end_last:
        return False
    if not set(base.gained) <= set(cand.gained):
        return False
    return cand.value >= base.value - 1e-9


def apply_priorities(problem: Problem, actions: list[tuple]) -> tuple[list[tuple], list[int]]:
    """Return (possibly re-routed actions, offsets of the singles that were re-routed)."""
    P = problem
    if not P.priority or not actions:
        return actions, []
    base = replay(P, actions)
    if base.problems:
        return actions, []
    changed: list[int] = []
    i = 0
    while i < len(actions):
        act = actions[i]
        if act[0] != SINGLE:
            i += 1
            continue
        step = base.steps[i]
        roll = step.rolls[0]
        if roll.cat_id in P.priority:
            i += 1
            continue
        k = step.offset_before
        last_before = base.steps[i - 1].last_after if i > 0 else P.last_id
        clock = step.day_offset
        swapped = False
        for b in P.rare_banners:
            if b.event_id == act[1]:
                continue
            r = single(P.tables, b, k, last_before)
            if r.cat_id not in P.priority:
                continue
            if P.banner_live(b.event_id, clock):
                candidate = actions[:i] + [(SINGLE, b.event_id)] + actions[i + 1:]
            elif P.priority_allow_skip:
                other = "tomorrow" if clock == TODAY else "today"
                back = "today" if clock == TODAY else "tomorrow"
                if not P.banner_live(b.event_id, TOMORROW if other == "tomorrow" else TODAY):
                    continue
                candidate = _collapse_clocks(actions[:i] + [(CLOCK, other), (SINGLE, b.event_id), (CLOCK, back)] + actions[i + 1:])
            else:
                continue
            rep = replay(P, candidate)
            if rep.problems or not _same_except(base, rep, k):
                continue
            actions, base = candidate, rep
            changed.append(k)
            swapped = True
            break
        if swapped:
            # the action list may have shifted by inserted clock changes; find the single at offset k
            i = next(j for j, st in enumerate(base.steps) if st.action[0] == SINGLE and st.offset_before == k) + 1
        else:
            i += 1
    return actions, changed

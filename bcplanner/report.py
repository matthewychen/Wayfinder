"""Turn a replayed plan into a step-by-step table, with every unit listed.

Rows are produced for every roll (rares included) so that results can be ticked
off one by one in the game. Ubers, legends and new units carry flags the GUI and
the Markdown export highlight.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import timedelta

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE, describe
from .metrics import Metrics
from .prng import site_label
from .problem import Problem
from .replay import ReplayResult
from .scrape import BASE_URL


def passed_note(steps) -> str:
    """'passes uber slot 7B' for the uber slots a step (or group of steps) went past on the other track."""
    marks = {"uber": "", "uber_fest": "\u2020", "legend": " (legend)"}
    labels = [site_label(p) + marks.get(band, "") + (" (repeat)" if kind == "repeat" else "")
              for st in steps for p, band, kind in st.passed]
    if not labels:
        return ""
    note = "passes uber slot" + ("s " if len(labels) > 1 else " ") + ", ".join(labels)
    if any(lab.endswith("\u2020") for lab in labels):
        note += " (\u2020 Uberfest-only)"
    return note

RARITY_LABEL = {"rare": "Rare", "supa": "Super Rare", "uber": "Uber Rare", "legend": "Legend Rare",
                "special": "Special", "normal": "Normal"}


@dataclass
class Row:
    step: int
    date: str
    kind: str            # "action" | "roll" | "clock" | "checkpoint"
    action: str
    banner: str
    position: str        # site label such as 7B, or 7BG for a guaranteed
    result: str
    rarity: str
    new: bool
    top: bool            # uber or legend
    note: str
    wanted: bool = False # a priority unit (extra copy wanted)
    switched: bool = False  # this single was moved to another banner only for a wanted copy
    tickets_left: int | None = None
    cat_food_left: int | None = None
    plats_left: int | None = None
    legends_left: int | None = None
    value_after: float | None = None
    link: str = ""


def site_link(problem: Problem, seed: int, last: int, event_id: str) -> str:
    q = f"seed={seed}&event={event_id}&lang=en"
    if last:
        q += f"&last={last}"
    return f"{BASE_URL}/?{q}"


_BLURB_NOISE = ("collab capsules", "capsules", "tap banner for info", "tap the banner for info", "tap for details",
                "check banner for details", "tap for info")


def short_banner_name(name: str, limit: int = 34) -> str:
    """Fallback display name from the site's news blurb when the wiki has no official title.

    'Survive! Mola Mola! Collab Capsules! ★ Tap the banner for info!' -> 'Survive! Mola Mola!'
    'Limited Summer capsules with a new hero! Tap banner for info!'   -> 'Limited Summer capsules with a new hero'
    """
    text = name.split("★", 1)[0]
    segments = [s.strip(" :-") for s in text.replace("!", "!\n").split("\n")]
    keep = []
    for seg in segments:
        core = seg.rstrip("!").strip()
        if not core or any(noise in core.lower() for noise in _BLURB_NOISE):
            continue
        keep.append(seg)
        if sum(len(k) for k in keep) >= 12:
            break
    out = " ".join(keep).strip()
    if not out:
        out = text.strip(" :!-")
    if not out.endswith("!"):
        out = out.rstrip("!")
    if len(out) > limit:
        out = out[:limit - 1].rstrip() + "…"
    return out or name[:limit]


def banner_short_names(problem: Problem) -> dict[str, str]:
    return {ev: short_banner_name(b.name) for ev, b in problem.banners.items()}


GROUPABLE = {SINGLE, PLAT, LEGEND}


def _grouped_steps(steps):
    """Consecutive single tickets on one banner (or platinum / legend tickets) become one entry."""
    groups: list[tuple[tuple, list]] = []
    for step in steps:
        kind = step.action[0]
        key = (kind, step.action[1] if kind == SINGLE else None, step.day_offset)
        if groups and kind in GROUPABLE and groups[-1][0] == key:
            groups[-1][1].append(step)
        else:
            groups.append((key, [step]))
    return groups


def group_label(kind: str, n: int, banner: str) -> str:
    if kind == SINGLE:
        return f"{n} single draws (rare tickets) on {banner}" if n > 1 else f"Single (rare ticket) on {banner}"
    if kind == PLAT:
        return f"{n} platinum tickets" if n > 1 else "Platinum ticket"
    if kind == LEGEND:
        return f"{n} legend tickets" if n > 1 else "Legend ticket"
    return ""


def rows_for(problem: Problem, rep: ReplayResult, names: dict[int, str],
             banner_names: dict[str, str] | None = None, rerouted=()) -> list[Row]:
    """`rerouted` holds the offsets of single tickets moved to another banner for a wanted copy."""
    P = problem
    rerouted = set(rerouted)
    bn = banner_names or banner_short_names(P)
    rows: list[Row] = []
    for (kind, _b, _d), steps in _grouped_steps(rep.steps):
        first, last = steps[0], steps[-1]
        day = (P.today + timedelta(days=first.day_offset)).isoformat()
        step_label = f"{first.index}" if first is last else f"{first.index}-{last.index}"
        if kind == CLOCK:
            target = (P.today + timedelta(days=1 if first.action[1] == "tomorrow" else 0)).isoformat()
            rows.append(Row(step_label, day, "clock", f"Set device date to {target}", "", "", "", "", False, False, ""))
            continue
        if kind in (SINGLE, ELEVEN):
            banner_id = first.action[1]
        elif kind == PLAT:
            banner_id = P.plat.event_id
        else:
            banner_id = P.legend.event_id
        banner_label = bn.get(banner_id, banner_id)
        action_text = describe(first.action, bn) if kind == ELEVEN else group_label(kind, len(steps), banner_label)
        n_rolls = sum(len(st.rolls) for st in steps)
        group_switched = kind == SINGLE and any(st.offset_before in rerouted for st in steps)
        group_note = f"{n_rolls} result(s)" + ("; switched banner for a wanted copy" if group_switched else "")
        if kind == ELEVEN and passed_note(steps):
            group_note += "; " + passed_note(steps)
        rows.append(Row(step_label, day, "action", action_text, banner_label, "", "", "", False, False,
                        group_note, switched=group_switched))
        for st in steps:
            for rv in st.rolls:
                note = ""
                if rv.rerolled:
                    note = f"dupe of {names.get(rv.duped_cat_id, rv.duped_cat_id)} rerolled, track switches"
                elif rv.source == "guaranteed":
                    note = "guaranteed uber, track switches"
                elif rv.source == "plat":
                    note = "platinum ticket"
                elif rv.source == "legend":
                    note = "legend ticket"
                if rv.source in ("roll", "plat") and P.legend is not None \
                        and P.tables.is_legend_slot(P.legend, rv.offset_before):
                    _, _, leg = P.tables.cat_at(P.legend, rv.offset_before)
                    if leg > 0 and leg not in P.owned:
                        note = (note + "; " if note else "") + f"legend slot: a legend ticket here gives {names.get(leg, leg)}"
                wanted = rv.cat_id in P.priority
                if wanted:
                    note = (note + "; " if note else "") + "wanted copy"
                if kind != ELEVEN and passed_note([st]):
                    note = (note + "; " if note else "") + passed_note([st])
                switched = rv.source == "roll" and rv.offset_before in rerouted
                rows.append(Row(step_label, day, "roll", "", bn.get(rv.banner, rv.banner), rv.label,
                                names.get(rv.cat_id, f"cat {rv.cat_id}"), RARITY_LABEL.get(rv.rarity, rv.rarity),
                                rv.new, rv.rarity in ("uber", "legend"), note, wanted, switched))
        link = site_link(P, last.seed_after, last.last_after, banner_id)
        rows.append(Row(step_label, day, "checkpoint", "after this step", "", "", "", "", False, False,
                        "paste into bc.godfat.org to cross-check",
                        tickets_left=P.tickets - last.tickets_after, cat_food_left=P.cat_food - last.cf_units_after * 750,
                        plats_left=P.plats - last.plats_after, legends_left=P.legends - last.legends_after,
                        value_after=last.value_after, link=link))
    return rows


def to_markdown(problem: Problem, rep: ReplayResult, metrics: Metrics, names: dict[int, str],
                title: str = "Plan", banner_names: dict[str, str] | None = None, rerouted=()) -> str:
    out = io.StringIO()
    out.write(f"## {title}\n\n")
    out.write(f"Value {metrics.value:.2f} | new: " + ", ".join(f"{v} {RARITY_LABEL.get(k, k)}" for k, v in sorted(metrics.new_by_rarity.items())) + "\n\n")
    out.write(f"Spend: {metrics.tickets} rare tickets, {metrics.cat_food} CF, {metrics.plats} platinum, {metrics.legends} legend tickets, "
              f"{metrics.clock_changes} clock changes = {metrics.cost_draw_equivalents:.2f} draw-equivalents "
              f"({metrics.value_per_draw_equivalent:.2f} value per draw-equivalent)\n\n")
    out.write(f"Dupe ubers: {metrics.dupe_ubers} | singles that could have hit a new uber elsewhere: {metrics.uber_slots_passed} | "
              f"11-draw rolls with a new uber elsewhere: {metrics.eleven_rolls_new_elsewhere} | "
              f"legend slots used/passed: {metrics.legend_slots_used}/{metrics.legend_slots_passed} | banner changes (free): {metrics.banner_switches} | "
              f"other-track uber slots gone past: {metrics.uber_slots_skipped} (+{metrics.fest_slots_skipped} Uberfest-only, "
              f"-{metrics.pass_penalty:.2f} value)\n\n")
    if rep.problems:
        out.write("**Replay problems:** " + "; ".join(rep.problems) + "\n\n")
    out.write("| Step | Date | Action / result | Banner | Pos | Rarity | Note |\n|---|---|---|---|---|---|---|\n")
    for r in rows_for(problem, rep, names, banner_names, rerouted):
        if r.kind == "clock":
            out.write(f"| {r.step} | {r.date} | **{r.action}** | | | | |\n")
        elif r.kind == "action":
            out.write(f"| {r.step} | {r.date} | **{r.action}**{' 🔀' if r.switched else ''} | {r.banner} | | | {r.note} |\n")
        elif r.kind == "roll":
            name = r.result
            if r.top:
                name = f"**{name}**"
            if r.new:
                name = f"NEW {name}"
            if r.wanted:
                name = f"{name} (wanted copy)"
            if r.switched:
                name = f"🔀 {name}"
            out.write(f"| | | {name} | {r.banner} | {r.position} | {r.rarity} | {r.note} |\n")
        else:
            out.write(f"| | | left: {r.tickets_left} tickets, {r.cat_food_left} CF, {r.plats_left} plat, {r.legends_left} legend | | | | [check]({r.link}) |\n")
    out.write("\n**If a result differs from the table, stop rolling, refresh the banner data, re-enter your position from the site and re-plan.**\n")
    return out.getvalue()


def to_csv(problem: Problem, rep: ReplayResult, names: dict[int, str],
           banner_names: dict[str, str] | None = None, rerouted=()) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["step", "date", "kind", "action", "banner", "position", "result", "rarity", "new", "top", "wanted", "switched", "note",
                "tickets_left", "cat_food_left", "plats_left", "legends_left", "value_after", "link"])
    for r in rows_for(problem, rep, names, banner_names, rerouted):
        w.writerow([r.step, r.date, r.kind, r.action, r.banner, r.position, r.result, r.rarity, int(r.new), int(r.top),
                    int(r.wanted), int(r.switched), r.note, r.tickets_left, r.cat_food_left, r.plats_left, r.legends_left,
                    "" if r.value_after is None else f"{r.value_after:.2f}", r.link])
    return out.getvalue()


def plan_text(problem: Problem, rep: ReplayResult, names: dict[int, str],
              banner_names: dict[str, str] | None = None, title: str = "", keep: dict | None = None) -> str:
    """The plan as plain text to copy: one line per action group, with the units received in order.

        11-draw on Summer Gals [4A-14BG]. Receives Rocker Cat, ..., Jungle Gourmet Tomoe* (guaranteed).
        Pull 8x on Survive! Mola Mola! collab [15A-22A]. Receives Psychocat, ..., Mola King.

    A star marks a unit new to you. Clock changes and platinum / legend tickets get their own lines."""
    P = problem
    bn = banner_names or banner_short_names(P)
    lines: list[str] = []
    if title:
        spend = [f"{rep.tickets} tickets", f"{rep.cf_units * 750} CF"]
        if rep.plats:
            spend.append(f"{rep.plats} platinum")
        if rep.legends:
            spend.append(f"{rep.legends} legend ticket{'s' if rep.legends > 1 else ''}")
        lines.append(f"{title}: {', '.join(spend)}. Value {rep.value:.1f}.")

    def unit(rv) -> str:
        return names.get(rv.cat_id, str(rv.cat_id)) + ("*" if rv.new else "")

    n = 0
    for (kind, ev, _day), steps in _grouped_steps(rep.steps):
        n += 1
        rolls = [rv for st in steps for rv in st.rolls]
        span = ""
        if rolls:
            span = f" [{rolls[0].label}" + (f"-{rolls[-1].label}]" if len(rolls) > 1 else "]")
        if kind == CLOCK:
            lines.append(f"{n}. Set the device date " + ("one day forward." if steps[0].action[1] == "tomorrow"
                                                          else "back to today."))
            continue
        if kind == SINGLE:
            what = f"Pull {len(steps)}x on {bn.get(ev, ev)}"
        elif kind == ELEVEN:
            what = f"11-draw on {bn.get(steps[0].action[1], steps[0].action[1])}"
        elif kind == PLAT:
            what = "Platinum ticket" if len(steps) == 1 else f"{len(steps)} platinum tickets"
        elif kind == LEGEND:
            what = "Legend ticket" if len(steps) == 1 else f"{len(steps)} legend tickets"
        else:
            what = describe(steps[0].action, bn)
        got = ", ".join(unit(rv) + (" (guaranteed)" if rv.source == "guaranteed" else "") for rv in rolls)
        lines.append(f"{n}. {what}{span}. Receives {got}.")
    tail = f"Stop at {site_label(rep.end_offset)}."
    left = [f"{P.tickets - rep.tickets} tickets", f"{(P.cf_units - rep.cf_units) * 750} CF"]
    if P.plats:
        left.append(f"{P.plats - rep.plats} platinum")
    if P.legends:
        left.append(f"{P.legends - rep.legends} legend ticket{'s' if P.legends - rep.legends != 1 else ''}")
    tail += f" Left: {', '.join(left)}."
    if keep and keep.get("value"):
        tail += f" Kept for the next banner: about +{keep['value']:.1f}."
    lines.append(tail)
    lines.append("* = new to you")
    return "\n".join(lines)

"""The normal-capsule planner's screen inside the Wayfinder app (sidebar inputs, Pulls and Tracks tabs).

Widget keys start with "n_" so they never collide with the rare planner's; inputs are saved to
data_cache/normal_settings.json unless the app runs stateless.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from .banners import BANNERS, DARK, POWER_UPS
from .cli import parse_url, settings_from
from .plan import plan
from . import sweep
from .report import ORBS_PER_RARE_TICKET, improvement, progress_after, rare_tickets, site_url
from .sim import Seeds, canonical_at, label
from .visual import img, plan_html

DEFAULTS = {"url": "", "cat": 100, "lucky": 30, "dark": 20.0, "catfruit": False, "orb": 1.0, "axe": 1.0}

# The pull list as a clickable component: it returns {"k": pull index, "t": click time} for the pull you click.
_pull_list = components.declare_component("nsp_pull_list", path=str(Path(__file__).parent / "frontend"))


def _load(path: Path, stateless: bool) -> None:
    ss = st.session_state
    if ss.get("n_init"):
        return
    saved = {}
    if not stateless:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    for k, v in DEFAULTS.items():
        ss["n_" + k] = saved.get(k, v)
    ss.n_result = None
    ss.n_plan_id = 0
    ss.n_init = True


def keep_inputs() -> None:
    """Call at the start of every run, whichever planner is shown: Streamlit forgets the value of a widget
    that a run does not draw, so without this the inputs come back empty after a visit to the rare planner."""
    ss = st.session_state
    for k in DEFAULTS:
        if "n_" + k in ss:
            ss["n_" + k] = ss["n_" + k]


def _save(path: Path, stateless: bool) -> None:
    if stateless:
        return
    ss = st.session_state
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: ss["n_" + k] for k in DEFAULTS}, indent=1), encoding="utf-8")


def render(settings_path: Path, stateless: bool = False) -> None:
    """Draw the normal planner. Call it inside the app after the sidebar's title and planner switch."""
    ss = st.session_state
    _load(settings_path, stateless)

    with st.sidebar:
        st.text_input("Tracker URL (bc-normal-seed-tracking)", key="n_url",
                      help="Copy it from the tracker after your last pull: it gives the seed and lastCat.")
        c1, c2 = st.columns(2)
        c1.number_input("Cat tickets", 0, 5000, step=1, key="n_cat")
        c2.number_input("Lucky tickets", 0, 5000, step=1, key="n_lucky")
        st.number_input("Blue orbs worth one Dark Catseye", 0.0, 1000.0, step=1.0, key="n_dark",
                        help="The most blue orbs a plan gives up rather than lose a Dark Catseye it could still reach.")
        st.toggle("Catfruit capsule open", key="n_catfruit")
        with st.expander("Values"):
            st.number_input("Blue orb", 0.0, 10.0, step=0.1, key="n_orb", help="Each power-up from the Cat Capsule.")
            st.number_input("Li'l Axe Cat", 0.0, 10.0, step=0.1, key="n_axe")
        go = st.button("Plan", type="primary", width="stretch", key="n_plan")

    st.title("Wayfinder")
    if go or ss.pop("n_replan", False):
        _save(settings_path, stateless)
        try:
            seed, last = parse_url(ss.n_url)
        except SystemExit as exc:
            st.error(str(exc))
            return
        settings = settings_from(int(ss.n_cat), int(ss.n_lucky), float(ss.n_dark), bool(ss.n_catfruit),
                                 float(ss.n_orb), float(ss.n_axe))
        with st.spinner("Searching every pull sequence…"):
            ss.n_result = (seed, last, settings, plan(seed, last, settings))
        ss.n_plan_id = ss.get("n_plan_id", 0) + 1

    if ss.n_result is None:
        st.info("Paste your bc-normal-seed-tracking URL, enter your cat and lucky tickets and press **Plan**.")
        return

    seed, last, settings, res = ss.n_result
    if res.missed:
        st.warning(f"Gives up a Dark Catseye at {', '.join(res.missed)} (worth less than the orbs it would cost here, "
                   f"or a Dark Catseye on the other track is taken instead).")

    imp = improvement(seed, last, res, settings)
    if imp is not None:
        st.markdown(f"**Improvement ×{imp.factor:.2f}** · {imp.per_ticket:.3f} blue orbs per cat ticket, against "
                    f"{imp.average:.3f} pulling straight on the Cat Capsule on average "
                    f"({imp.this_seed:.3f} straight from this seed) · **{imp.over:+.0f}** "
                    f"{img('Cat Cannon Attack', 20, 'blue orbs')} = {img('Rare Ticket', 20)} **{rare_tickets(imp.over):+.1f}**",
                    unsafe_allow_html=True,
                    help=f"Blue orbs ÷ the {imp.tickets} cat tickets the plan spends, Catseye pulls included. "
                         "Straight = pressing pull on the Cat Capsule every time, no track switching on purpose. "
                         f"Rare tickets at {ORBS_PER_RARE_TICKET} blue orbs each.")
    tab_ops, tab_lucky, tab_tracks = st.tabs(["Pulls", "Lucky tickets", "Tracks"])
    with tab_ops:
        st.caption("Stopping early? Click the last pull you made (or a row number): the sidebar shows the seed "
                   "there and can save it as your new start.")
        clicked = _pull_list(html=plan_html(res, settings, ",".join(settings.banners)), selected=None,
                             key=f"n_pulls_{ss.n_plan_id}", default=None)
        st.caption("Bright = counted (blue orb, Li'l Axe Cat, Dark Catseye), faded = everything else. "
                   "⇄ = a dupe that switches track. Hover an icon for its name and cell.")
    with tab_lucky:
        _lucky_tab(seed, last, settings, res)
    with tab_tracks:
        _tracks(seed, last, settings, res)
    if clicked and res.rolls:
        k = max(0, min(int(clicked.get("k", 0)), len(res.rolls) - 1))
        _stop_panel(seed, settings, res, k, settings_path, stateless)


def _stop_panel(seed, settings, res, k: int, settings_path: Path, stateless: bool) -> None:
    """Sidebar box for a chosen stop point: the seed and tracker link there, and Save progress."""
    pr = progress_after(seed, res, settings, k, ",".join(settings.banners))
    with st.sidebar:
        st.divider()
        st.subheader(f"Stopped after pull {k + 1} of {len(res.rolls)}")
        st.markdown(f"Last pull at **{pr.cell}** ({pr.last}); next pull at **{pr.next_cell}**.")
        st.markdown(f"Got so far: {pr.orbs} blue orbs (= {img('Rare Ticket', 18)} {pr.orbs // ORBS_PER_RARE_TICKET}), "
                    f"{pr.axe} Li'l Axe Cat, {pr.darks} Dark Catseye.", unsafe_allow_html=True)
        st.markdown(f"Tickets left: {pr.left.get('cat', 0)} cat, {pr.left.get('lucky', 0)} lucky. Seed here:")
        st.code(str(pr.seed), language=None)
        st.markdown(f"[Open this point on the tracker]({pr.url})")
        st.button("Save progress here", type="primary", width="stretch", key="n_save_progress",
                  on_click=_save_progress, args=(pr.url, pr.left.get("cat", 0), pr.left.get("lucky", 0),
                                                 settings_path, stateless),
                  help="Makes this point your new start: the tracker URL and your ticket counts are updated, "
                       "and the plan is redone from here.")


AUTO_SWEEP_CAT = 600     # up to this many cat tickets the lucky-ticket chart is worked out without asking (seconds)


def _lucky_tab(seed, last, settings, res) -> None:
    """What more (or fewer) lucky tickets would do for this many cat tickets, and how many to aim for."""
    ss = st.session_state
    cat = int(settings.tickets.get(settings.currency.get("np", "cat"), 0))
    if cat <= 0:
        st.info("Plan with some cat tickets first.")
        return
    key = (seed, last, cat, tuple(settings.banners), settings.dark_value, tuple(sorted(settings.weights.items())))
    data = ss.get("n_sweep")
    if not data or data[0] != key:
        auto = cat <= AUTO_SWEEP_CAT
        if not auto:
            st.caption(f"Plans your {cat} cat tickets again with 0 to {round(sweep.RATIOS[-1] * cat)} lucky tickets "
                       f"({len(sweep.lucky_counts(cat))} plans, about a minute for 1,000 cat tickets) to show what "
                       "lucky tickets add and how many are worth having.")
        if not (auto or st.button("Work it out", type="primary", key="n_sweep_go")):
            return
        bar = st.progress(0.0, text="Working out what lucky tickets add…")
        pts = sweep.sweep(seed, last, settings,
                          progress=lambda d, n: bar.progress(d / n, text=f"Working out what lucky tickets add… {d} of {n}"))
        bar.empty()
        ss.n_sweep = data = (key, pts)
    pts = data[1]
    now = sweep.from_result(res, settings)
    adv = sweep.advise(pts, now)
    best = adv.best
    base = sweep.straight_rate()
    orb, tix, lucky = img("Cat Cannon Attack", 22, "blue orbs"), img("Rare Ticket", 22), img("lt", 22, "lucky tickets")

    def card(head: str, big: str, lines: list[str]) -> str:
        return ("<div style='flex:1 1 200px;border:1px solid rgba(128,128,128,.35);border-radius:10px;padding:10px 14px'>"
                f"<div style='font-size:13px;opacity:.7'>{head}</div>"
                f"<div style='font-size:28px;font-weight:600;line-height:1.3'>{big}</div>"
                + "".join(f"<div style='font-size:14px;margin-top:2px'>{x}</div>" for x in lines) + "</div>")

    per = now.orbs / now.cat_used if now.cat_used else 0.0
    now_card = card(f"Now: {lucky} {now.lucky} lucky · {now.ratio:.2f} per cat ticket", f"×{now.factor:.2f}",
                    [f"{per:.3f} {orb} per cat ticket (straight: {base:.3f})",
                     f"{adv.over_baseline:+.0f} {orb} over pulling straight = {tix} {rare_tickets(adv.over_baseline):+.1f}"])
    if adv.extra_orbs > 0:
        more = card(f"With {lucky} {adv.want} lucky", f"×{best.factor:.2f}",
                    [f"+{adv.extra_orbs} more {orb} than your plan = {tix} +{rare_tickets(adv.extra_orbs):.1f}",
                     f"{adv.extra_lucky} more lucky tickets, about {adv.extra_orbs / max(1, adv.extra_lucky):.2f} {orb} each"])
    else:
        more = card("More lucky tickets", f"×{best.factor:.2f}", ["add nothing: you already have enough"])
    if adv.still_rising:
        rec_big, rec_lines = f"{sweep.RATIOS[-1]:.1f}+", ["lucky tickets per cat ticket: still rising at the end of the range"]
    else:
        rec_big = f"{adv.per_cat:.2f}"
        rec_lines = [f"lucky tickets per cat ticket: {lucky} {adv.want} for your {cat}"]
        if now.lucky > adv.want:
            rec_lines.append(f"{now.lucky - adv.want} of yours go unused")
    rec = card("Aim for", rec_big, rec_lines)
    st.html(f"<div style='display:flex;flex-wrap:wrap;gap:12px;margin:4px 0 8px'>{now_card}{more}{rec}</div>")

    # the sidebar's inputs, when they differ from the plan shown (before Plan is pressed again)
    in_cat, in_lucky = int(ss.get("n_cat", cat)), int(ss.get("n_lucky", now.lucky))
    inputs = in_lucky if in_cat == cat and in_lucky != now.lucky else None
    if in_cat != cat:
        st.caption(f"Your inputs now say {in_cat} cat tickets: press **Plan** to redo this chart for them.")
    _lucky_chart(pts, now, adv, inputs)
    st.caption(f"Each point is a full plan for {cat} cat tickets with that many lucky tickets, at your current values "
               f"(Dark Catseye worth {settings.dark_value:g} blue orbs). ×1 = {base:.3f} blue orbs per cat ticket, "
               f"pulling the Cat Capsule straight; ×{1 / base:.2f} = every cat ticket a blue orb. "
               f"Rare tickets at {ORBS_PER_RARE_TICKET} blue orbs each.")


def _lucky_chart(pts, now, adv, inputs: int | None = None) -> None:
    import altair as alt
    import numpy as np
    import pandas as pd

    blue, you_c, ref_c, axis_c = "#2a78d6", "#eb6834", "#a8a69c", "#b4b2a9"
    base = sweep.straight_rate()
    cat = now.cat or 1
    xmax = max(sweep.RATIOS[-1], now.ratio * 1.05, (inputs or 0) / cat * 1.05)
    df = pd.DataFrame([{"ratio": p.ratio, "lucky": p.lucky, "used": p.lucky_used, "orbs": p.orbs,
                        "per": p.orbs / p.cat_used if p.cat_used else 0.0,
                        "tickets": p.orbs // ORBS_PER_RARE_TICKET, "factor": p.factor} for p in pts])
    axis = dict(domain=True, domainColor=axis_c, domainWidth=2, ticks=True, tickColor=axis_c, tickWidth=2, tickSize=7,
                labelFontSize=13, labelColor=axis_c, titleFontSize=14, titleFontWeight="bold", titleColor=axis_c,
                gridOpacity=0.25, labelPadding=4)
    x = alt.X("ratio:Q", title="Lucky tickets per cat ticket", scale=alt.Scale(domain=[0, xmax], nice=False),
              axis=alt.Axis(grid=False, values=[i / 5 for i in range(int(xmax * 5) + 1)], format=".1f", **axis))
    y = alt.Y("factor:Q", title="Improvement factor",
              scale=alt.Scale(domain=[0, 2.5]),
              axis=alt.Axis(values=[0, 0.5, 1, 1.5, 2, 2.5], labelExpr="'×' + format(datum.value, '.1f')", **axis))
    tip = [alt.Tooltip("lucky:Q", title="lucky tickets"), alt.Tooltip("used:Q", title="lucky used"),
           alt.Tooltip("orbs:Q", title="blue orbs"), alt.Tooltip("per:Q", title="blue orbs per cat ticket", format=".3f"),
           alt.Tooltip("tickets:Q", title="rare tickets"), alt.Tooltip("factor:Q", title="improvement", format=".2f")]
    low = pd.DataFrame([{"y": 1.0, "label": f"×1 = {base:.3f} blue orbs per cat ticket (pulling straight)"}])
    high = pd.DataFrame([{"y": 1 / base, "label": f"×{1 / base:.2f} = every cat ticket a blue orb"}])
    rules = alt.Chart(pd.concat([low, high])).mark_rule(color=ref_c, strokeWidth=2).encode(y="y:Q")
    text = dict(color=ref_c, fontSize=12, fontWeight="bold")
    rule_text = (alt.Chart(low).mark_text(align="right", baseline="top", dx=-6, dy=5, **text).encode(
                     x=alt.value("width"), y="y:Q", text="label:N")          # under the line, right: the curve is far above
                 + alt.Chart(high).mark_text(align="left", baseline="bottom", dx=6, dy=-5, **text).encode(
                     x=alt.value(0), y="y:Q", text="label:N"))               # over the line, left: the curve is far below
    line = alt.Chart(df).mark_line(color=blue, strokeWidth=2.5).encode(x=x, y=y)
    dots = alt.Chart(df).mark_circle(color=blue, size=50, opacity=1).encode(x=x, y=y, tooltip=tip)
    layers = [rules, rule_text, line, dots]
    per = now.orbs / now.cat_used if now.cat_used else 0.0
    marks = [(now.ratio, now.factor, f"you: {now.lucky} lucky · {per:.2f} orbs/ticket", you_c, 14, True)]
    if adv.extra_orbs > 0 and not adv.still_rising:
        marks.append((adv.want / adv.best.cat, adv.best.factor, f"enough: {adv.want} lucky", blue, 14, True))
    if inputs is not None:
        xr = inputs / cat
        marks.append((xr, float(np.interp(xr, df["ratio"], df["factor"])),
                      f"inputs: {inputs} lucky (press Plan)", you_c, 14, False))
    for mx, my, text, colour, dy, filled in marks:
        one = pd.DataFrame([{"ratio": mx, "factor": my, "label": text}])
        layers.append(alt.Chart(one).mark_point(filled=filled, size=170, shape="diamond", color=colour,
                                                stroke=colour if not filled else "white", strokeWidth=2).encode(x=x, y=y))
        # to the right of the marker and a little below: the curve rises to the right, so that corner is clear
        layers.append(alt.Chart(one).mark_text(fontSize=12, fontWeight="bold", color=colour, align="left",
                                               dx=10, dy=dy).encode(
            x=x, y=y, text="label:N"))
    st.altair_chart(alt.layer(*layers).properties(height=360), width="stretch")


def _save_progress(url: str, cat: int, lucky: int, settings_path: Path, stateless: bool) -> None:
    ss = st.session_state
    ss.n_url, ss.n_cat, ss.n_lucky = url, max(0, int(cat)), max(0, int(lucky))
    _save(settings_path, stateless)
    ss.n_replan = True


def _tracks(seed, last, settings, res) -> None:
    S = Seeds(seed)
    codes = list(settings.banners)
    rolled = {r.p: r for r in res.rolls}
    rows = min(400, res.end // 2 + 8)
    blue = set(POWER_UPS)

    def cell(p: int, code: str) -> str:
        r = rolled.get(p)
        _rar, name, _rr = canonical_at(S, BANNERS[code], p)
        text, style = name, ""
        if name in blue:
            style = "background:#c9e4ff;color:#111;"
        elif name == DARK:
            style = "background:aqua;color:#111;"
        elif name == "Li'l Axe Cat":
            style = "background:gold;color:#111;"
        if r is not None and r.code == code:
            if r.rerolls:
                text = f"{name} → {r.name}"
            style += "outline:3px solid #ff8c00;outline-offset:-3px;font-weight:700;"
        return f"<td style='{style}'>{html.escape(text)}</td>"

    head = "".join(f"<th>{html.escape(BANNERS[c].title)}</th>" for c in codes)
    out = ["<div style='overflow-x:auto'><table style='border-collapse:collapse;font-size:13px' border='1' cellpadding='3'>",
           f"<tr><th>#</th>{head}<th>#</th>{head}</tr>"]
    for i in range(rows):
        a, b = 2 * i, 2 * i + 1
        out.append(f"<tr><td>{label(a)}</td>{''.join(cell(a, c) for c in codes)}"
                   f"<td>{label(b)}</td>{''.join(cell(b, c) for c in codes)}</tr>")
    out.append("</table></div>")
    st.caption("Orange outline = the pull the plan makes there. Blue = blue orb, aqua = Dark Catseye, "
               "gold = Li'l Axe Cat. Left half track A, right half track B.")
    st.html("".join(out))
    st.markdown(f"[Open the start on the tracker]({site_url(seed, last, ','.join(codes))})")

"""The two-track table as bc.godfat.org draws it, plus an overlay of a plan's path.

Colours and cell rules copy the site's stylesheet (tacit.css and lib/battle-cats-rolls/cat.rb):
cells are coloured by the score band of their position and an owned cat is light cyan with a 10%
stripe of the original colour on the left. Differences from the site, on request: guaranteed cells
are white (they are always ubers), the plan's path is shaded green instead of grey, and the colour
key sits below the table.

"Follow the plan's banners" mode: positions the plan spends on another banner show that banner's
unit instead of the displayed banner's, with a small tag, and a margin column notes where the plan
changes banner and where it changes track (dupe reroll or guaranteed uber).
"""

from __future__ import annotations

import html as html_mod
from dataclasses import dataclass, field

from .actions import CLOCK, ELEVEN, LEGEND, PLAT, SINGLE
from .model import Banner
from .prng import site_label
from .sim import Tables, site_table

COLORS = {
    "rare": "white", "supa_fest": "yellow", "supa": "gold", "uber_fest": "salmon", "uber": "red",
    "legend_fest": "mediumslateblue", "legend": "darkviolet",
    "found": "lime", "owned": "lightcyan", "exclusive": "aqua",
}
DARK_BACKGROUNDS = {"uber", "legend", "legend_fest"}
LEGEND_TEXT = "#d8a56f"      # the site's link colour on legend cells

KEY_ROWS = [
    ("supa", "Super", "cats"), ("supa_fest", "Super", "in Uberfest or Epicfest only"),
    ("uber", "Uber", "cats"), ("uber_fest", "Uber", "in Uberfest or Epicfest only"),
    ("legend", "Legendary", "cats"), ("legend_fest", "Legendary", "cats in Royalfest or double legend chances only"),
    ("owned", "Owned", "cats (original colour on the left)"), ("exclusive", "Exclusive", "single-banner cats"),
]


def score_label(score: int | None) -> str:
    """cat.rb#score_rarity_label: which rarity band a position's score falls in."""
    if score is None or score < 6470:
        return "rare"
    if score < 6970:
        return "supa_fest"
    if score < 9070:
        return "supa"
    if score < 9470:
        return "uber_fest"
    if score < 9940:
        return "uber"
    if score < 9970:
        return "legend_fest"
    return "legend"


def cell_colours(cat_id: int, score: int | None, owned: set[int], found: set[int], exclusive: set[int],
                 rarity_override: str | None = None) -> tuple[str, str]:
    """(major, minor) colour labels, following view.rb#highlight_basic."""
    band = rarity_override or score_label(score)
    special = "owned" if cat_id in owned else ("found" if cat_id in found else ("exclusive" if cat_id in exclusive else None))
    major = special or band
    if special == "owned":
        minor = "found" if cat_id in found else ("exclusive" if cat_id in exclusive else band)
    else:
        minor = major
    return major, minor


@dataclass
class Overlay:
    cells: dict[str, tuple[str, str, str]] = field(default_factory=dict)      # cell key -> (css class, badge, title)
    overrides: dict[str, tuple[int, str, str]] = field(default_factory=dict)  # cell key -> (cat id, rarity, banner tag)
    margins: dict[tuple[int, str], list[str]] = field(default_factory=dict)  # (row, 'A'|'B') -> notes on that side
    next_label: str | None = None
    follow: bool = False


def _row_of(label: str) -> int:
    return int(label.rstrip("ABGR"))


def _side_of(offset: int) -> str:
    """Which side of the table an offset sits on: even offsets are track A, odd are track B."""
    return "A" if offset % 2 == 0 else "B"


def plan_overlay(plan, this_banner: str, banner_names: dict[str, str], follow: bool = False) -> Overlay:
    """Which cells a plan touches. Keys are the site labels ('7B'); guaranteed cells add 'G'.

    With `follow`, rolls made on other banners override the cell's unit and margin notes mark
    banner changes and track changes."""
    ov = Overlay(follow=follow)
    prev_banner = None
    for step in plan.replay.steps:
        kind = step.action[0]
        if kind == CLOCK:
            continue
        n = str(step.index)
        banner_id = step.action[1] if kind in (SINGLE, ELEVEN) else None
        bname = banner_names.get(banner_id, banner_id) if banner_id else ("Platinum" if kind == PLAT else "Legend")
        elsewhere = banner_id != this_banner if banner_id else True
        row = _row_of(site_label(step.offset_before))
        # banner change notes (rolls only), on the side of the track the roll is on
        if follow and kind in (SINGLE, ELEVEN) and prev_banner is not None and banner_id != prev_banner:
            ov.margins.setdefault((row, _side_of(step.offset_before)), []).append(f"⇄ {bname}")
        if kind in (SINGLE, ELEVEN):
            prev_banner = banner_id
        if kind == SINGLE:
            rv = step.rolls[0]
            note = f"step {n}: single on {bname}" + (" (dupe rerolled, switches track)" if rv.rerolled else "")
            ov.cells[rv.label] = ("picked", n + ("*" if elsewhere else ""), note)
            if follow and elsewhere:
                ov.overrides[rv.label] = (rv.cat_id, rv.rarity, bname)
            if follow and rv.rerolled:
                ov.margins.setdefault((_row_of(site_label(step.offset_after)), _side_of(step.offset_after)), []).append(
                    f"↕ track {_side_of(step.offset_after)} (dupe reroll)")
        elif kind == ELEVEN:
            start = site_label(step.offset_before)
            for rv in step.rolls:
                if rv.source == "roll":
                    ov.cells[rv.label] = ("picked_consecutively", n + ("*" if elsewhere else ""), f"step {n}: 11-draw on {bname}")
                    if follow and elsewhere:
                        ov.overrides[rv.label] = (rv.cat_id, rv.rarity, bname)
                else:
                    ov.cells[start + "G"] = ("picked_consecutively", n + "G", f"step {n}: guaranteed uber on {bname}")
                    if follow and elsewhere:
                        ov.overrides[start + "G"] = (rv.cat_id, "uber", bname)
            if follow and step.rolls and step.rolls[-1].source == "guaranteed":
                ov.margins.setdefault((_row_of(site_label(step.offset_after)), _side_of(step.offset_after)), []).append(
                    f"↕ track {_side_of(step.offset_after)} (after guaranteed)")
        elif kind in (PLAT, LEGEND):
            rv = step.rolls[0]
            tag = "P" if kind == PLAT else "L"
            ov.cells[rv.label] = ("picked", n + tag, f"step {n}: {bname.lower()} ticket at this position")
            if follow:
                ov.overrides[rv.label] = (rv.cat_id, rv.rarity, f"{bname} ticket")
    ov.next_label = site_label(plan.replay.end_offset)
    return ov


def _style(major: str, minor: str) -> str:
    text = ""
    if major in DARK_BACKGROUNDS:
        text = f"color:{LEGEND_TEXT if 'legend' in major else 'white'};"
    return f"background:linear-gradient(to right,{COLORS[minor]} 10%,{COLORS[major]} 10%);{text}"


def _cell(key: str, inner: str, major: str, minor: str, overlay: Overlay, icon_html: str = "") -> str:
    cls = ""
    badge = ""
    title = ""
    if key in overlay.cells:
        cls, b, title = overlay.cells[key]
        badge = f'<span class="badge">{html_mod.escape(b)}</span>'
    if overlay.next_label == key:
        cls = (cls + " next_position").strip()
        title = (title + "; " if title else "") + "next position after the plan"
    return (f'<td class="pos {cls}" style="{_style(major, minor)}" title="{html_mod.escape(title)}">'
            f'{badge}{icon_html}<span class="nm">{inner}</span></td>')


def render_tracks_html(tables: Tables, banner: Banner, last_id: int, rows: int, names: dict[int, str],
                       owned: set[int], found: set[int], exclusive: set[int], overlay: Overlay | None = None,
                       icon_url=None, icon_px: int = 24, banner_title: str = "") -> str:
    """The table for one banner from the current seed, as HTML."""
    overlay = overlay or Overlay()
    positions = site_table(tables, banner, last_id, rows, banner.guaranteed_rolls)
    show_margin = overlay.follow

    def icon(cid: int) -> str:
        if icon_url is None or cid < 0:
            return ""
        url = icon_url(cid)
        return f'<img src="{url}" style="height:{icon_px}px;vertical-align:middle;margin-right:3px">' if url else ""

    def name_of(cid: int) -> str:
        return html_mod.escape(names.get(cid, str(cid)))

    def result_cell(pos) -> str:
        key = pos.label
        if key in overlay.overrides:
            cid, _rarity, tag = overlay.overrides[key]
            major, minor = cell_colours(cid, pos.score, owned, found, exclusive)
            inner = name_of(cid) + f'<div class="tag">on {html_mod.escape(tag)}</div>'
            return _cell(key, inner, major, minor, overlay, icon(cid))
        major, minor = cell_colours(pos.cat_id, pos.score, owned, found, exclusive)
        inner = name_of(pos.cat_id)
        if pos.rerolled_id is not None:
            inner += f'<div class="rr">if dupe → {icon(pos.rerolled_id)}{name_of(pos.rerolled_id)} → {pos.rerolled_next}</div>'
        return _cell(key, inner, major, minor, overlay, icon(pos.cat_id))

    def guaranteed_cell(pos) -> str:
        key = pos.label + "G"
        if key in overlay.overrides:
            cid, _rarity, tag = overlay.overrides[key]
            major, minor = cell_colours(cid, None, owned, found, exclusive, rarity_override="rare")
            inner = name_of(cid) + f'<div class="tag">on {html_mod.escape(tag)}</div>'
            return _cell(key, inner, major, minor, overlay, icon(cid))
        if pos.guaranteed_id is None:
            return '<td class="pos empty"></td>'
        major, minor = cell_colours(pos.guaranteed_id, None, owned, found, exclusive, rarity_override="rare")
        inner = name_of(pos.guaranteed_id) + f" → {pos.guaranteed_next}"
        if pos.rerolled_guaranteed_id is not None:
            inner += f'<div class="rr">if dupe → {name_of(pos.rerolled_guaranteed_id)} → {pos.rerolled_guaranteed_next}</div>'
        return _cell(key, inner, major, minor, overlay, icon(pos.guaranteed_id))

    out = [CSS, '<div class="tracks">']
    if banner_title:
        out.append(f'<div class="ttl">{html_mod.escape(banner_title)}</div>')
    head = '<th class="mg"></th>' if show_margin else ""
    out.append(f'<table><thead><tr>{head}<th>No.</th><th>Result</th><th>Guaranteed</th><th>Alt. result</th>'
               f'<th>Alt. guaranteed</th><th>Alt. No.</th>{head}</tr></thead><tbody>')
    for a, b in positions:
        row = _row_of(a.label)
        margin_l = margin_r = ""
        if show_margin:
            left = "<br>".join(html_mod.escape(x) for x in overlay.margins.get((row, "A"), []))
            right = "<br>".join(html_mod.escape(x) for x in overlay.margins.get((row, "B"), []))
            margin_l = f'<td class="mg l">{left}</td>'
            margin_r = f'<td class="mg r">{right}</td>'
        out.append(f'<tr>{margin_l}<th>{a.label}</th>{result_cell(a)}{guaranteed_cell(a)}{result_cell(b)}{guaranteed_cell(b)}'
                   f'<th>{b.label}</th>{margin_r}</tr>')
    out.append("</tbody></table>")
    out.append('<ul class="key">')
    for label, word, rest in KEY_ROWS:
        out.append(f'<li><span class="sw" style="{_style(label, label)}">{word}</span> {rest}</li>')
    out.append('<li><span class="sw" style="background:white">Guaranteed</span> cells are white: they are always ubers</li>'
               '<li><span class="sw picked" style="background:white">Rolled</span> cats on the plan</li>'
               '<li><span class="sw picked_consecutively" style="background:white">Rolled</span> cats with consecutive (11 or 15) rolls</li>'
               '<li><span class="sw next_position" style="background:white">Next position</span> after the rolls</li>'
               '<li>Badge = plan step (* on another banner, P platinum, L legend, G guaranteed)</li></ul></div>')
    return "".join(out)


CSS = """<style>
.tracks { font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; color: #111; }
.tracks .ttl { font-weight: 600; font-size: 15px; margin: 4px 0 8px; color: #eee; }
.tracks ul.key { list-style: none; padding: 0; margin: 12px 0 0; display: block; }
.tracks ul.key li { color: #ddd; display: block; margin: 3px 0; }
.tracks .sw { display: inline-block; padding: 1px 6px; color: #111; border: 1px solid #333; position: relative; overflow: hidden; }
.tracks table { border-collapse: collapse; }
.tracks th, .tracks td { border: 1px solid #444; padding: 3px 6px; text-align: center; vertical-align: middle; }
.tracks th { background: #2a2d36; color: #eee; font-weight: 600; }
.tracks th.mg, .tracks td.mg { background: transparent; border-color: transparent; color: #9ee493; font-size: 11px;
                               min-width: 120px; max-width: 170px; }
.tracks td.mg.l { text-align: right; padding-right: 8px; }
.tracks td.mg.r { text-align: left; padding-left: 8px; }
.tracks td.pos { position: relative; overflow: hidden; isolation: isolate; min-width: 150px; }
.tracks td.empty { background: #1e2028; }
.tracks .rr, .tracks .tag { font-size: 11px; opacity: 0.85; }
.tracks .tag { font-style: italic; }
.tracks .badge { position: absolute; top: 1px; left: 2px; background: #1b5e20; color: #fff; font-size: 10px; line-height: 14px;
                 padding: 0 4px; border-radius: 7px; z-index: 2; }
.tracks .picked::after, .tracks .picked_consecutively::after, .tracks .next_position::after {
  content: ""; position: absolute; inset: -1px; pointer-events: none; z-index: 1; }
.tracks .picked::after { background: rgba(0, 200, 60, 0.28); }
.tracks .picked_consecutively::after { background: rgba(0, 200, 60, 0.5); }
.tracks .next_position::after { background: repeating-linear-gradient(90deg, #00c83c66 5px, #00c83c66 15px, #00c83c33 15px, #00c83c33 25px); }
</style>"""

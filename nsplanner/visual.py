"""The plan as icons: one row per operation, the capsule's icon, how many pulls, and what comes out."""

from __future__ import annotations

import base64
import html
import json
from functools import lru_cache
from pathlib import Path

from .banners import BANNERS, DARK, POWER_UPS
from .plan import Result, Settings
from .report import ORBS_PER_RARE_TICKET, operations, site_url
from .sim import label

ASSETS = Path(__file__).parent / "assets"


@lru_cache(maxsize=1)
def _index() -> dict:
    try:
        return json.loads((ASSETS / "index.json").read_text(encoding="utf-8"))
    except OSError:
        return {"items": {}, "capsules": {}}


@lru_cache(maxsize=256)
def _uri(filename: str) -> str:
    return "data:image/png;base64," + base64.b64encode((ASSETS / filename).read_bytes()).decode("ascii")


_USED: set[str] = set()     # icon files referenced by the page being built (embedded once, in its <style>)


def _cls(filename: str) -> str:
    _USED.add(filename)
    return "i-" + filename.rsplit(".", 1)[0]


def icon(name: str, size: int = 34, title: str = "", style: str = "") -> str:
    """An item or unit icon, or a small text chip when there is no picture."""
    f = _index()["items"].get(name)
    t = html.escape(title or name, quote=True)
    if f and (ASSETS / f).exists():
        return (f'<i class="ic {_cls(f)}" title="{t}" role="img" aria-label="{t}" '
                f'style="width:{size}px;height:{size}px;{style}"></i>')
    return (f'<span class="chip" title="{t}" style="min-width:{size}px;height:{size}px;{style}">'
            f'{html.escape(name)}</span>')


def img(name: str, size: int = 22, title: str = "") -> str:
    """A standalone <img> (picture inlined) for pages without the plan's icon stylesheet."""
    f = _index()["items"].get(name) or _index()["capsules"].get(name)
    t = html.escape(title or name, quote=True)
    if f and (ASSETS / f).exists():
        return (f'<img src="{_uri(f)}" alt="{t}" title="{t}" '
                f'style="width:{size}px;height:{size}px;vertical-align:middle;object-fit:contain">')
    return html.escape(name)


def capsule_icon(code: str, size: int = 44) -> str:
    f = _index()["capsules"].get(code)
    t = html.escape(BANNERS[code].title, quote=True)
    if f and (ASSETS / f).exists():
        return f'<i class="ic {_cls(f)}" title="{t}" role="img" aria-label="{t}" style="width:{size}px;height:{size}px"></i>'
    return f'<b title="{t}">{html.escape(BANNERS[code].title)}</b>'


def _icon_css() -> str:
    return "".join(f".nsp .{'i-' + f.rsplit('.', 1)[0]}{{background-image:url({_uri(f)})}}" for f in sorted(_USED))


CSS = """
<style>
.nsp { font-family: system-ui, sans-serif; color: var(--nsp-ink, inherit); }
.nsp .sum { display:flex; flex-wrap:wrap; gap:18px; align-items:center; margin:2px 0 14px; font-size:20px; font-weight:700; }
.nsp .sum span { display:inline-flex; align-items:center; gap:6px; }
.nsp .row { display:flex; align-items:center; gap:10px; padding:6px 4px; border-bottom:1px solid #8884; }
.nsp .n { width:26px; text-align:right; font-size:12px; opacity:.6; }
.nsp .pill { min-width:44px; text-align:center; font-weight:800; font-size:18px; border-radius:999px; padding:2px 8px; }
.nsp .ten { background:#ff8c00; color:#111; }
.nsp .one { background:#8885; }
.nsp .times { font-size:15px; font-weight:700; opacity:.85; margin-left:-4px; min-width:30px; }
.nsp .cells { font-size:11px; opacity:.6; width:74px; }
.nsp .res { display:flex; flex-wrap:wrap; gap:3px; align-items:center; flex:1; }
.nsp .it { position:relative; display:inline-block; line-height:0; }
.nsp .ic { display:inline-block; background-size:contain; background-repeat:no-repeat; background-position:center; vertical-align:middle; }
.nsp .chip { display:inline-flex; align-items:center; justify-content:center; padding:0 4px; border-radius:6px; font-size:10px; background:#8883; }
.nsp .dim .ic, .nsp .dim .chip { opacity:.28; filter:grayscale(.6); }
.nsp .hit .ic { border-radius:50%; box-shadow:0 0 0 2px #2fd3ff, 0 0 8px #2fd3ffaa; }
.nsp .axe .ic { border-radius:6px; box-shadow:0 0 0 2px gold, 0 0 8px #ffd70099; }
.nsp .dark .ic { border-radius:50%; box-shadow:0 0 0 3px #ff2d55, 0 0 10px #ff2d55aa; }
.nsp .sw { position:absolute; right:-4px; bottom:-4px; font-size:10px; line-height:14px; font-weight:800;
           background:#ff8c00; color:#111; border-radius:7px; padding:0 3px; }
.nsp .gain { font-weight:800; font-size:15px; color:#2fd3ff; min-width:34px; text-align:right; }
.nsp .foot { margin-top:12px; font-size:13px; opacity:.85; }
.nsp [data-stop] { cursor:pointer; }
.nsp .n[data-stop]:hover { opacity:1; color:#ff8c00; text-decoration:underline; }
.nsp .it[data-stop]:hover .ic, .nsp .it[data-stop]:hover .chip { outline:2px dashed #ff8c00; outline-offset:2px; }
.nsp .it.after .ic, .nsp .it.after .chip { opacity:.12; filter:grayscale(1); box-shadow:none; }
.nsp .row.after-row { opacity:.35; }
.nsp .it.stop .ic, .nsp .it.stop .chip { outline:3px solid #ff2d55; outline-offset:2px; }
.nsp .it.stop::after { content:"STOP"; position:absolute; left:50%; top:-12px; transform:translateX(-50%);
                       font:800 9px/12px system-ui, sans-serif; color:#fff; background:#ff2d55; border-radius:4px; padding:0 3px; }
.nsp a { color:#2fa8ff; }
</style>
"""


def _result(r, st: Settings, k: int, stop: int) -> str:
    counted = r.name == DARK or st.weights.get(r.name, 0.0) > 0
    cls = "dark" if r.name == DARK else ("hit" if r.name in POWER_UPS else ("axe" if counted else "dim"))
    title = f"{r.name} at {r.cell}"
    badge = ""
    if r.rerolls:
        switch = r.rerolls % 2 == 1
        title += (f" (dupe of {r.canonical}: " + ("switches track" if switch else "stays on this track")
                  + f", next {label(r.next)})")
        badge = f'<span class="sw">{"⇄" if switch else "↻"}</span>'
    return f'<span class="it {cls}" data-k="{k}" data-stop="{stop}">{icon(r.name, title=title)}{badge}</span>'


def plan_html(res: Result, st: Settings, banners_param: str = "np,lt,ce") -> str:
    axe = res.weighted.get("Li'l Axe Cat", 0)
    _USED.clear()
    axe_icon = icon("Li'l Axe Cat", 30)
    out = [CSS, '<div class="nsp">', '<div class="sum">',
           f'<span>{icon("Cat Cannon Attack", 30, "Blue orbs")} {res.orbs} <span style="opacity:.5">=</span> '
           f'{icon("Rare Ticket", 30, f"Rare tickets at {ORBS_PER_RARE_TICKET} blue orbs each")} '
           f'{res.orbs // ORBS_PER_RARE_TICKET}</span>',
           f'<span>{axe_icon} {axe}</span>',
           f'<span>{icon(DARK, 30)} {len(res.darks)}</span>',
           '<span style="opacity:.5">·</span>']
    for code in st.banners:
        cur = st.currency[code]
        if code in ("np", "lt"):
            out.append(f'<span>{capsule_icon(code, 30)} {res.used.get(cur, 0)}</span>')
    out.append("</div>")
    base = 0      # index of the row's first pull in the plan; a 10x pull can only be stopped after its last pull
    for n, (kind, rs) in enumerate(operations(res.rolls), start=1):
        gain = sum(1 for r in rs if r.name == DARK or st.weights.get(r.name, 0.0) > 0)
        ks = [base + i for i in range(len(rs))]
        stops = [base + len(rs) - 1] * len(rs) if kind == "10x" else ks
        cells = rs[0].cell if len(rs) == 1 else f"{rs[0].cell}→{rs[-1].cell}"
        if kind == "10x":
            pill, times = '<span class="pill ten">10</span>', '<span class="times"></span>'
        else:
            pill = '<span class="pill one">1</span>'
            times = f'<span class="times">{"×" + str(len(rs)) if len(rs) > 1 else ""}</span>'
        out.append(f'<div class="row" data-first="{base}"><span class="n" data-stop="{base + len(rs) - 1}" '
                   f'title="Stop after this row">{n}</span>{capsule_icon(rs[0].code)}{pill}{times}'
                   f'<span class="cells">{cells}</span>'
                   f'<span class="res">{"".join(_result(r, st, k, sp) for r, k, sp in zip(rs, ks, stops))}</span>'
                   f'<span class="gain">{"+" + str(gain) if gain else ""}</span></div>')
        base += len(rs)
    ahead = ", ".join(res.darks_ahead) or "none in sight"
    out.append(f'<div class="foot">Ends at {label(res.end)} · next Dark Catseyes {ahead} · '
               f'<a href="{html.escape(site_url(res.end_seed, res.end_last, banners_param), quote=True)}" '
               f'target="_blank">continue on the tracker</a></div>')
    if res.missed:
        out.append(f'<div class="foot">Gives up a Dark Catseye at {", ".join(res.missed)}.</div>')
    out.append("</div>")
    return f"<style>{_icon_css()}</style>" + "".join(out)

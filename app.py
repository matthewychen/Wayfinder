"""Battle Cats Pull Planner - Streamlit GUI.

Run:  .venv/Scripts/streamlit run app.py      (Windows)
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_planner_modules_if_changed() -> bool:
    """Streamlit re-runs this script on every interaction but keeps imported modules cached.
    When any file in bcplanner/ is newer than what this process loaded, drop those modules so the
    imports below pick up the new code. No restart needed after code changes."""
    newest = max(f.stat().st_mtime for f in (ROOT / "bcplanner").glob("*.py"))
    last = getattr(sys, "_bcplanner_stamp", None)
    sys._bcplanner_stamp = newest
    if last is None or newest <= last:
        return False
    for name in list(sys.modules):
        if name == "bcplanner" or name.startswith("bcplanner."):
            del sys.modules[name]
    return True


RELOADED = _reload_planner_modules_if_changed()

from bcplanner.actions import describe  # noqa: E402
from bcplanner.future import FutureModel, FutureValue, estimate_p_new_from  # noqa: E402
from bcplanner.icons import IconCache, item_icon_html  # noqa: E402
from bcplanner.options import platinum_options, platinum_positions, spending_options  # noqa: E402
from bcplanner.ownedstore import export_text, import_text  # noqa: E402
from bcplanner.report import RARITY_LABEL, plan_text, rows_for  # noqa: E402
from bcplanner.sim import Tables  # noqa: E402
from bcplanner.tracks_view import plan_overlay, render_tracks_html  # noqa: E402
from bcplanner.guideimport import IconLibrary, data_url, png_bytes, read_pages  # noqa: E402
from bcplanner.wiki import WikiClient, home_groups, lookup_titles  # noqa: E402
from bcplanner.session import (Inputs, Plan, display_names, load_fixtures, load_live, load_settings,  # noqa: E402
                               make_plan, parse_tracks_url, readings, row_matches, run, run_coverage,
                               save_settings, unit_rows, wishlist_multipliers)

st.set_page_config(page_title="Battle Cats Pull Planner", page_icon="🐱", layout="wide")

CACHE = ROOT / "data_cache"
SETTINGS = CACHE / "settings.json"
FIXTURE_EVENTS = ["2026-09-11_1002", "2026-09-11_1059", "2026-09-11_1076", "2026-09-14_991",
                  "2026-07-24_1063", "2026-07-24_1064"]
DEPTH = {"Normal (fast)": "normal", "Thorough (slower)": "thorough", "Exact (proves the best plan, slowest)": "exact"}

ss = st.session_state
icons = IconCache(CACHE)


def _stateless() -> bool:
    """True on a shared deployment: inputs live in the browser session only, never in settings.json.

    Turn it on with the environment variable BCPLANNER_STATELESS=1 or a Streamlit secret
    `stateless = true` (Community Cloud: app settings -> Secrets). Icon, wiki and banner
    caches are still shared on disk, which is harmless and saves requests.
    """
    import os

    if os.environ.get("BCPLANNER_STATELESS"):
        return True
    try:
        return bool(st.secrets.get("stateless", False))
    except Exception:  # noqa: BLE001 - no secrets file locally
        return False


STATELESS = _stateless()


# --------------------------------------------------------------------------------------
# Saved settings: load once into widget state
# --------------------------------------------------------------------------------------
def init_state():
    if ss.get("_init"):
        return
    saved = {} if STATELESS else load_settings(SETTINGS)
    defaults = {
        "tracks_url": "", "tickets": 0, "cat_food": 0, "plats": 0, "legends": 0, "game_version": "15.6",
        "rate": 30.0, "w_supa": 0.8, "w_uber": 1.0, "w_legend": 8.0, "multiplier": 3.0, "wishlist": "",
        "forbid": True, "max_skips": 4, "depth": "Normal (fast)", "fixtures": False, "icon_size": 64,
        "priority_skip": False, "discount_first": False, "d_supa": 0.05, "d_uber": 0.2, "d_legend": 0.0,
        "uber_mult": 1.5, "p_uber": 0.8, "p_fest": 0.2, "p_legend": 5.0, "t_cost": 0.02,
        "f_on": True, "f_outlook": 50,
    }
    for k, v in defaults.items():
        ss[k] = saved.get(k, v)
    ss.owned_ids = set(saved.get("owned_ids", []))
    ss.priority_ids = set(saved.get("priority_ids", []))
    ss.uber_priority_ids = set(saved.get("uber_priority_ids", []))
    ss.banner_flags = saved.get("banner_flags", {})     # event_id -> {"guaranteed": int, "discount": bool}
    ss.owned_version = 0
    ss.priority_version = 0
    ss.uber_version = 0
    ss.loaded = None
    ss.display = {}
    ss.result = None
    ss._init = True


def persist():
    if STATELESS:
        return
    keys = ["tracks_url", "tickets", "cat_food", "plats", "legends", "game_version", "rate", "w_supa", "w_uber",
            "w_legend", "multiplier", "wishlist", "forbid", "max_skips", "depth", "fixtures", "icon_size",
            "priority_skip", "discount_first", "d_supa", "d_uber", "d_legend", "uber_mult", "p_uber", "p_fest",
            "f_on", "f_outlook", "p_legend", "t_cost"]
    data = {k: ss.get(k) for k in keys}
    data["owned_ids"] = sorted(ss.owned_ids)
    data["priority_ids"] = sorted(ss.priority_ids)
    data["uber_priority_ids"] = sorted(ss.uber_priority_ids)
    data["banner_flags"] = ss.banner_flags
    save_settings(SETTINGS, data)
    ss.settings_stamp = SETTINGS.stat().st_mtime if SETTINGS.exists() else 0.0


HOME_FILE = CACHE / "home_map.json"


def load_home_map() -> dict[int, str]:
    data = load_settings(HOME_FILE)
    if not data:                                     # fresh install: the snapshot shipped with the code
        data = load_settings(ROOT / "bcplanner" / "data" / "home_map.json")
    ss.home_titles = data.get("titles", {})
    ss.home_titles = {int(k): v for k, v in ss.home_titles.items()}
    ss.home_rarities = data.get("rarities", {})
    return {int(k): v for k, v in data.get("home", {}).items()}


def save_home_map(home: dict[int, str]) -> None:
    save_settings(HOME_FILE, {"home": {str(k): v for k, v in home.items()},
                              "titles": {str(k): v for k, v in ss.get("home_titles", {}).items()},
                              "rarities": ss.get("home_rarities", {})})


init_state()
if RELOADED:
    # objects kept in the session were built by the old classes; start fresh
    ss.loaded = None
    ss.result = None
    st.toast("Planner code updated. Press Fetch banners, then Plan again.")
_home_stamp = HOME_FILE.stat().st_mtime if HOME_FILE.exists() else 0.0
if ss.get("home_stamp") != _home_stamp:          # (re)load when the file changes on disk
    ss.home_map = load_home_map()
    ss.home_stamp = _home_stamp
_settings_stamp = SETTINGS.stat().st_mtime if SETTINGS.exists() else 0.0
if not STATELESS and ss.get("settings_stamp") not in (None, _settings_stamp):
    # something else (an import script, another window) changed the saved lists: take them over
    _saved = load_settings(SETTINGS)
    ss.owned_ids = set(_saved.get("owned_ids", []))
    ss.priority_ids = set(_saved.get("priority_ids", []))
    ss.uber_priority_ids = set(_saved.get("uber_priority_ids", []))
    ss.owned_version = ss.get("owned_version", 0) + 1
    ss.priority_version = ss.get("priority_version", 0) + 1
    ss.uber_version = ss.get("uber_version", 0) + 1
    st.toast("Owned and priority lists reloaded from the settings file.")
ss.settings_stamp = _settings_stamp
ss.setdefault("owned_version", 0)
ss.setdefault("priority_version", 0)
ss.setdefault("priority_ids", set())
ss.setdefault("uber_priority_ids", set())
ss.setdefault("uber_version", 0)
ss.setdefault("banner_flags", {})


def future_model(loaded, on: bool, outlook: int) -> FutureModel:
    """One slider stands in for the estimate's knobs. The chance that a next-banner unit is new starts
    from the unowned share of the shared pools and is pulled towards 0 (pessimistic) or 1 (optimistic);
    the floor under the value of kept resources runs from 1 to 3 per 11-draw's worth."""
    if not on:
        return FutureModel(mode="none")
    s = max(0.0, min(1.0, outlook / 100))
    est = estimate_p_new_from(loaded.banners, ss.owned_ids)
    if s <= 0.5:
        p_new = {r: v * (s / 0.5) for r, v in est.items()}
    else:
        p_new = {r: v + (1 - v) * ((s - 0.5) / 0.5) for r, v in est.items()}
    return FutureModel(mode="seed", flat_per_draw=1.0 + 2.0 * s, confidence=0.8, p_new=p_new)


def icon_px() -> int:
    return int(ss.get("icon_size", 64))


def img_width() -> int:
    """Icon column width in pixels: the image plus a little padding."""
    return icon_px() + 18


def icon_img(cat_id: int, size: int | None = None) -> str:
    url = icons.data_url(cat_id)
    size = size or icon_px()
    return f'<img src="{url}" style="height:{size}px;vertical-align:middle;margin-right:4px">' if url else ""


def resource_row(kind: str, label: str, key: str, maxv: int, step: int = 1):
    c1, c2 = st.columns([1, 5])
    c1.markdown(item_icon_html(kind, 26), unsafe_allow_html=True)
    c2.number_input(label, 0, maxv, step=step, key=key)


# --------------------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------------------
with st.sidebar:
    st.title("Pull planner")
    st.date_input("Plan date (device date today)", value=date.today(), key="plan_date")
    st.text_input("Your bc.godfat.org tracks URL", key="tracks_url",
                  placeholder="https://bc.godfat.org/?seed=...&last=...&event=...",
                  help="Open your tracks page after your last roll and copy the address. Press Enter after pasting.")
    st.subheader("Resources")
    resource_row("ticket", "Rare tickets", "tickets", 999)
    resource_row("cat_food", "Cat food", "cat_food", 200000, 750)
    resource_row("plat", "Platinum tickets to use", "plats", 99)
    resource_row("legend", "Legend tickets", "legends", 99)
    st.checkbox("First 11-draw of this plan costs 750 CF", key="discount_first",
                help="The half-price offer applies once, to whichever 11-draw the plan does first.")
    owned_caption = st.empty()   # filled at the end of the run so it reflects this run's changes
    fetch_clicked = st.button("Fetch banners", width="stretch")
    banner_options_box = st.container()   # per-banner guaranteed / 750 CF flags, filled once banners are loaded
    plan_clicked = st.button("Plan", type="primary", width="stretch")
    with st.expander("Advanced"):
        st.number_input("Rare tickets worth one 11-draw", 1.0, 200.0, key="rate")
        w1, w2, w3 = st.columns(3)
        w1.number_input("New super", 0.0, 10.0, key="w_supa",
                        help="Also the value of a new rare. Repeats of rares are worth nothing.")
        w2.number_input("New uber", 0.0, 10.0, key="w_uber")
        w3.number_input("New legend", 0.0, 50.0, key="w_legend")
        st.caption("A repeat is worth")
        d1, d2, d3 = st.columns(3)
        d1.number_input("Repeat super", 0.0, 10.0, key="d_supa", step=0.05)
        d2.number_input("Repeat uber", 0.0, 10.0, key="d_uber", step=0.05)
        d3.number_input("Repeat legend", 0.0, 50.0, key="d_legend", step=0.05)
        st.caption("Going past an uber slot on the other track costs")
        q1, q2, q3 = st.columns(3)
        q1.number_input("Passing an uber slot", 0.0, 10.0, key="p_uber", step=0.05)
        q2.number_input("Uberfest-only slot", 0.0, 10.0, key="p_fest", step=0.05)
        q3.number_input("Legend slot", 0.0, 50.0, key="p_legend", step=0.5)
        st.number_input("Each rare ticket costs", 0.0, 1.0, key="t_cost", step=0.01, format="%.2f")
        st.markdown("**Next banner**")
        st.toggle("Weigh what you keep for the next banner", key="f_on",
                  help="The seed only moves when you roll, so positions you keep are the positions the next banner "
                       "will use. On: a position is spent now only when it beats what it should give later.")
        st.slider("Outlook for the next banner", 0, 100, key="f_outlook", format="%d",
                  help="Left: pessimistic, the next banner holds little for you, so spend now. "
                       "Right: optimistic, it will hold ubers you lack, so keep more.")
        st.number_input("Uber priority multiplier", 1.0, 20.0, key="uber_mult", step=0.1,
                        help="Value multiplier for the ubers ticked in the Uber priority tab. 1 = they only sort the "
                             "platinum table; more makes the plan itself favour them (like the wishlist).")
        st.number_input("Wishlist multiplier", 1.0, 50.0, key="multiplier")
        st.text_area("Wishlist: one unit per line, optional ', multiplier'", key="wishlist", height=70)
        st.toggle("Forbid 11-draws that roll over a legend slot", key="forbid")
        st.number_input("Max clock changes", 0, 10, key="max_skips")
        if ss.get("depth") not in DEPTH:
            ss.depth = "Normal (fast)"
        st.selectbox("Search depth", list(DEPTH), key="depth",
                     help="Normal keeps the 12 best partial plans at each state; Thorough keeps 30; Exact runs "
                          "Thorough first and then a full search that can only discard plans it proves cannot "
                          "win, so the result is certified optimal.")
        st.toggle("Use saved pages (offline test data)", key="fixtures")
        refresh = st.checkbox("Refresh banner data from the site", value=False)
        st.text_input("Game version (for owned-list exports)", key="game_version")
    ss.icon_size = min(128, max(32, int(ss.get("icon_size", 64))))
    st.slider("Icon size", 32, 128, key="icon_size", label_visibility="visible")
    if STATELESS:
        st.caption("Shared deployment: your inputs stay in this browser tab only. Keep your owned and wanted "
                   "lists with the export text and paste them back next time.")

# --------------------------------------------------------------------------------------
# Fetch banners
# --------------------------------------------------------------------------------------
if fetch_clicked:
    with st.spinner("Loading banners from bc.godfat.org…"):
        try:
            if ss.fixtures:
                loaded = load_fixtures(ROOT / "tests" / "fixtures", FIXTURE_EVENTS, ss.plan_date)
            else:
                fbar = st.progress(0.0, text="Loading from bc.godfat.org (a page can take a minute when the site is busy)…")
                loaded = load_live(ss.plan_date, CACHE, refresh=refresh,
                                   progress=lambda d, n: fbar.progress(d / n, text=f"Loaded {d} of {n} pages from bc.godfat.org…"))
                fbar.empty()
                stale = [n for n in loaded.notes if "did not answer" in n]
                if stale:
                    st.warning(f"bc.godfat.org did not answer for {len(stale)} page(s); used saved copies (see Checks).")
            ss.loaded = loaded
            ss.result = None
            ss.pop("banner_editor", None)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not load banners: {exc}")
    if ss.loaded is not None:
        bar = st.progress(0.0, text="Looking up official banner names on the Battle Cats Wiki…")
        names_all = dict(ss.loaded.names)
        ss.display, wiki_notes = display_names(ss.loaded.banners, names_all, CACHE,
                                               progress=lambda i, n: bar.progress(min(1.0, i / max(1, n))))
        bar.empty()
        ss.wiki_notes = wiki_notes
    persist()

loaded = ss.loaded
st.title("Battle Cats Pull Planner")
if loaded is None:
    st.info("Paste your tracks URL on the left, enter your resources, tick what you own in **Owned units**, "
            "then press **Fetch banners** and **Plan**.")
    owned_caption.caption(f"Owned units: {len(ss.owned_ids)} ticked.")
    st.stop()

names: dict[int, str] = dict(loaded.names)
if loaded.catalog:
    for cid, cat in loaded.catalog.cats.items():
        names.setdefault(cid, cat.name)
display = ss.display or {ev: b.name for ev, b in loaded.banners.items()}

for note in loaded.notes:
    st.warning(note)

# --------------------------------------------------------------------------------------
# Per-banner flags in the sidebar (guaranteed 11-draw, 750 CF first draw) and Banners-tab overrides
# --------------------------------------------------------------------------------------
with banner_options_box:
    st.markdown("**Guaranteed uber in the 11-draw?**")
    st.caption("Tick the banners whose 11-draw ends with a guaranteed uber. To leave a banner out of the plan, untick *include* in the Banners tab.")
    for ev, b in loaded.banners.items():
        if b.kind != "rare":
            continue
        flags = ss.banner_flags.setdefault(ev, {"guaranteed": int(b.guaranteed_rolls)})
        fest = any(w in display.get(ev, b.name).lower() for w in ("uberfest", "epicfest"))   # never guaranteed
        g = st.checkbox(display.get(ev, b.name), value=bool(flags.get("guaranteed")) and not fest, key=f"g_{ev}",
                        disabled=fest)
        flags["guaranteed"] = 0 if fest else ((flags.get("guaranteed") or 11) if g else 0)
        b.guaranteed_rolls = flags["guaranteed"]
for ev, ov in ss.get("banner_overrides", {}).items():
    if ev in loaded.banners:
        for k, v in ov.items():
            setattr(loaded.banners[ev], k, v)

multipliers, wl_errors = wishlist_multipliers(ss.wishlist, loaded.catalog, names, float(ss.multiplier))
if float(ss.get("uber_mult", 1.0)) != 1.0:
    for _cid in ss.uber_priority_ids:
        multipliers.setdefault(_cid, float(ss.uber_mult))
for e in wl_errors:
    st.warning(f"Wishlist: {e}")

# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------
if plan_clicked:
    seed, last, _ = parse_tracks_url(ss.tracks_url) if ss.tracks_url.strip() else (0, 0, None)
    if not seed:
        st.error("The tracks URL has no seed. Copy it from bc.godfat.org after your last roll.")
        st.stop()
    mode = DEPTH[ss.depth]
    inputs = Inputs(seed=seed, last=last, today=ss.plan_date, owned=frozenset(ss.owned_ids), tickets=int(ss.tickets),
                    cat_food=int(ss.cat_food), plats=int(ss.plats), legends=int(ss.legends),
                    tickets_per_draw=float(ss.rate),
                    weights={"rare": float(ss.w_supa), "supa": float(ss.w_supa), "uber": float(ss.w_uber),
                             "legend": float(ss.w_legend)},
                    multipliers=multipliers, forbid_eleven_over_legend_slot=bool(ss.forbid),
                    dupe_values={"supa": float(ss.d_supa), "uber": float(ss.d_uber), "legend": float(ss.d_legend)},
                    pass_penalties={"uber": float(ss.p_uber), "uber_fest": float(ss.p_fest), "legend": float(ss.p_legend)},
                    ticket_cost=float(ss.t_cost),
                    future=future_model(loaded, bool(ss.get("f_on", True)), int(ss.get("f_outlook", 50))),
                    max_clock_changes=int(ss.max_skips), mode=mode,
                    priority=frozenset(ss.priority_ids), priority_allow_skip=bool(ss.priority_skip),
                    discount_first_draw=bool(ss.discount_first))
    bar = st.progress(0.0, text="Searching…")
    problem, res = run(inputs, loaded.banners,
                       progress=lambda k, h: bar.progress(min(1.0, k / max(1, h)), text=f"Searching… {k} of about {h} steps"))
    bar.progress(0.0, text="Searching for the cheapest full coverage…")
    cov_res = run_coverage(inputs, problem,
                           progress=lambda k, h: bar.progress(min(1.0, k / max(1, h)), text=f"Coverage search… {k} of about {h} steps"))
    bar.empty()
    future = FutureValue(problem, inputs.future)
    rd = readings(problem, res, cov_res=cov_res, future=future)
    ss.result = (inputs, problem, res, rd, spending_options(problem, res, future), platinum_options(problem, res))
    if rd.best is not None:
        ss.tr_rows = min(200, rd.best.replay.end_offset // 2 + 1 + 20)
    persist()

tab_plan, tab_opts, tab_tracks, tab_owned, tab_ubers, tab_prio, tab_banners, tab_checks = st.tabs(
    ["Plan", "Options", "Tracks", "Owned units", "Uber priority", "Wanted copies", "Banners", "Checks"], key="main_tabs")


# --------------------------------------------------------------------------------------
# Plan rendering helpers
# --------------------------------------------------------------------------------------
def plan_table(problem, plan: Plan, key: str):
    """The step table and, on a second tab, the same plan as copy-pastable text."""
    tab_tbl, tab_txt = st.tabs(["Table", "Text"])
    with tab_tbl:
        _plan_dataframe(problem, plan, key)
    with tab_txt:
        st.code(plan_text(problem, plan.replay, names, display, plan.title, plan.keep), language=None)


def _plan_dataframe(problem, plan: Plan, key: str):
    rows = rows_for(problem, plan.replay, names, display, plan.rerouted)
    icons.prefetch([r_.cat_id for st_ in plan.replay.steps for r_ in st_.rolls])
    data = []
    roll_ids = []
    rerouted = set(plan.rerouted)
    for r in rows:
        if r.kind == "clock":
            data.append({"icon": "", "step": r.step, "date": r.date, "what": r.action, "banner": "", "pos": "",
                         "rarity": "", "new": "", "note": "", "check": ""})
        elif r.kind == "action":
            data.append({"icon": "", "step": r.step, "date": r.date, "what": ("🔀 " if r.switched else "") + r.action,
                         "banner": r.banner, "pos": "", "rarity": "", "new": "🔀" if r.switched else "",
                         "note": r.note, "check": ""})
        elif r.kind == "roll":
            what = ("NEW " if r.new else "") + r.result
            flag = "✓" if r.new else ("★" if r.wanted else "")
            if r.switched:
                flag = "🔀" + flag
            data.append({"icon": "", "step": "", "date": "", "what": what, "banner": r.banner, "pos": r.position,
                         "rarity": r.rarity, "new": flag, "note": r.note, "check": ""})
            roll_ids.append(len(data) - 1)
        else:
            data.append({"icon": "", "step": "", "date": "", "what": f"left: {r.tickets_left} tickets, "
                         f"{r.cat_food_left} CF, {r.plats_left} plat, {r.legends_left} legend",
                         "banner": "", "pos": "", "rarity": "", "new": "", "note": "", "check": r.link})
    roll_views = [rv for st_ in plan.replay.steps for rv in st_.rolls]
    for idx, rv in zip(roll_ids, roll_views):
        data[idx]["icon"] = icons.data_url(rv.cat_id)
    tdf = pd.DataFrame(data)

    def style_row(row):
        if row["rarity"] in ("Uber Rare", "Legend Rare"):
            base = "background-color: rgba(220, 60, 50, 0.18); font-weight: 600;"
        elif row["new"] == "✓":
            base = "background-color: rgba(60, 160, 90, 0.15);"
        elif "★" in str(row["new"]) or "🔀" in str(row["new"]):
            base = "background-color: rgba(90, 110, 220, 0.16);"
        elif str(row["what"]).startswith(("Single", "single", "11-draw", "Platinum", "Legend", "Set device")) or \
                str(row["what"])[:2].strip().isdigit() and "draws" in str(row["what"]):
            base = "background-color: rgba(120, 120, 140, 0.12); font-weight: 600;"
        elif str(row["what"]).startswith("left:"):
            base = "color: gray; font-size: 90%;"
        else:
            base = ""
        return [base] * len(row)

    st.dataframe(tdf.style.apply(style_row, axis=1), width="stretch", hide_index=True, height=620,
                 key=key, row_height=max(35, icon_px() + 8), column_config={
                     "icon": st.column_config.ImageColumn("", width=img_width()),
                     "step": st.column_config.TextColumn("step", width=60),
                     "date": st.column_config.TextColumn("date", width=100),
                     "what": st.column_config.TextColumn("action / result", width=340),
                     "banner": st.column_config.TextColumn("banner", width=170),
                     "pos": st.column_config.TextColumn("pos", width=60),
                     "rarity": st.column_config.TextColumn("rarity", width=100),
                     "new": st.column_config.TextColumn("", width=60, help="✓ new unit · ★ wanted copy · 🔀 banner switched only for a wanted copy"),
                     "note": st.column_config.TextColumn("note", width=260),
                     "check": st.column_config.LinkColumn("cross-check", display_text="open on bc.godfat.org", width=140),
                 })


def spend_html(tickets, cat_food, plats, legends) -> str:
    parts = []
    if tickets:
        parts.append(f"{item_icon_html('ticket')} {tickets}")
    if cat_food:
        parts.append(f"{item_icon_html('cat_food')} {cat_food}")
    if plats:
        parts.append(f"{item_icon_html('plat')} {plats}")
    if legends:
        parts.append(f"{item_icon_html('legend')} {legends}")
    return " &nbsp; ".join(parts) if parts else "nothing"


def units_html(ids: list[int], limit: int = 12) -> str:
    icons.prefetch(ids[:limit])
    parts = [f"{icon_img(cid)}{names.get(cid, cid)}" for cid in ids[:limit]]
    if len(ids) > limit:
        parts.append(f"… +{len(ids) - limit} more")
    return " &nbsp; ".join(parts) if parts else "none"


def units_html_counted(ids: list[int], limit: int = 12) -> str:
    """Like units_html, but a unit obtained several times is listed once with ×n."""
    from collections import Counter

    counts = Counter(ids)
    order = list(dict.fromkeys(ids))
    icons.prefetch(order[:limit])
    parts = [f"{icon_img(cid)}{names.get(cid, cid)}" + (f" ×{counts[cid]}" if counts[cid] > 1 else "")
             for cid in order[:limit]]
    if len(order) > limit:
        parts.append(f"… +{len(order) - limit} more")
    return " &nbsp; ".join(parts) if parts else "none"


def units_column_html(ids: list[int], counted: bool = False) -> str:
    """One unit per line; with `counted`, a unit listed several times appears once with ×n."""
    from collections import Counter

    counts = Counter(ids)
    order = list(dict.fromkeys(ids)) if counted else list(ids)
    icons.prefetch(order)
    if not order:
        return "<div style='opacity:.6'>none</div>"
    return "".join(f"<div style='margin:3px 0'>{icon_img(cid)}{names.get(cid, cid)}"
                   + (f" ×{counts[cid]}" if counted and counts[cid] > 1 else "") + "</div>" for cid in order)


def plan_header(problem, plan: Plan, key: str):
    m = plan.metrics
    legends = [cid for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "legend"]
    ubers = [cid for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "uber"]
    top = legends + ubers
    supa = [cid for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "supa"]
    rares = [cid for cid in plan.replay.gained if problem.unit_rarity.get(cid) == "rare"]
    wanted = [rv.cat_id for st_ in plan.replay.steps for rv in st_.rolls if rv.cat_id in problem.priority]
    st.markdown(f"**Spend:** {spend_html(m.tickets, m.cat_food, m.plats, m.legends)}"
                + (f" &nbsp; · {m.clock_changes} clock change(s)" if m.clock_changes else ""), unsafe_allow_html=True)
    if ss.get("plan_cols"):
        cols = st.columns(4 if problem.priority else 3)
        cols[0].markdown(f"**New legends ({len(legends)})**")
        cols[0].markdown(units_column_html(legends), unsafe_allow_html=True)
        cols[1].markdown(f"**New ubers ({len(ubers)})**")
        cols[1].markdown(units_column_html(ubers), unsafe_allow_html=True)
        cols[2].markdown(f"**New super rares ({len(supa)})**")
        cols[2].markdown(units_column_html(supa), unsafe_allow_html=True)
        if rares:
            cols[2].markdown(f"**New rares ({len(rares)})**")
            cols[2].markdown(units_column_html(rares), unsafe_allow_html=True)
        if problem.priority:
            cols[3].markdown(f"**Wanted copies ({len(wanted)})**")
            cols[3].markdown(units_column_html(wanted, counted=True), unsafe_allow_html=True)
    else:
        st.markdown(f"**New ubers and legends ({len(top)}):** {units_html(top)}", unsafe_allow_html=True)
        st.markdown(f"**New super rares ({len(supa)}):** {units_html(supa, 8)}", unsafe_allow_html=True)
        if rares:
            st.markdown(f"**New rares ({len(rares)}):** {units_html(rares, 8)}", unsafe_allow_html=True)
        if problem.priority:
            st.markdown(f"**Wanted copies ({len(wanted)}):** {units_html_counted(wanted, 10)}", unsafe_allow_html=True)
    if plan.keep:
        k = plan.keep
        if k["tickets"] or k["cf_units"] or k["plats"] or k["legends"]:
            st.markdown(f"**Kept for the next banner:** {spend_html(k['tickets'], k['cf_units'] * 750, k['plats'], k['legends'])}"
                        f" &nbsp; → about **+{k['value']:.1f}** later", unsafe_allow_html=True)
        else:
            st.markdown("**Nothing kept:** spending now beats saving.")
    bits = [f"Value {m.value:.2f}", f"repeat ubers {m.dupe_ubers}"]
    if m.uber_slots_passed:
        bits.append(f"singles that could have hit a new uber elsewhere {m.uber_slots_passed}")
    if m.uber_slots_skipped or m.fest_slots_skipped:
        bits.append(f"uber slots passed on the other track {m.uber_slots_skipped}+{m.fest_slots_skipped} fest (−{m.pass_penalty:.1f})")
    if problem.legends:
        bits.append(f"legend slots used/passed {m.legend_slots_used}/{m.legend_slots_passed}")
    bits.append(f"banner changes {m.banner_switches}")
    st.caption(" · ".join(bits))
    if plan.replay.problems:
        st.error("Replay check failed: " + "; ".join(plan.replay.problems))


# --------------------------------------------------------------------------------------
# Shared unit picker (owned units, priority units)
# --------------------------------------------------------------------------------------
@st.fragment
def unit_picker(state_key: str, version_key: str, prefix: str, rarities_all: list[str], rarities_default: list[str],
                caption: str, exclude: set[int] | None = None, every_default: bool = True):
    """A picker grid. Runs as a fragment: ticking or filtering reruns only this grid, not the page.
    `exclude` hides units (the Uber priority tab hides what you own)."""
    selected: set[int] = ss[state_key]
    st.caption(caption)
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    rarities = f1.multiselect("Rarity", rarities_all, default=rarities_default, key=f"{prefix}_rar")
    every = f2.toggle("Every gacha unit in the game", value=every_default, key=f"{prefix}_every",
                      help="On: every gacha unit in the English version, whether or not its banner is running. "
                           "Off: only units in today's banners and the platinum pool.")
    scope = "all" if every else "current"
    show = f3.selectbox("Show", ["all", "not ticked", "ticked"], key=f"{prefix}_show")
    query = f4.text_input("Search name or banner", key=f"{prefix}_query",
                          help="Matches the unit name, its home banner (e.g. almighties) or a banner it is running in.")
    by_home = f1.toggle("Group by home banner", key=f"{prefix}_home",
                        help="Sort by the set a unit belongs to (Dark Heroes, Summer Gals, Uberfest …) even when "
                             "that banner is not running, using the Battle Cats Wiki.")
    rows = unit_rows(loaded, selected, display, only_current=not every, rarities=tuple(rarities_all),
                     home=ss.home_map, group_by_home=by_home)
    if by_home:
        missing = [r for r in rows if r["home"] == "not looked up"]
        info_box = st.empty()
        if missing:
            info_box.info(f"{len(missing)} of these units have not been looked up on the wiki yet.")
            est = max(1, round(len(missing) * 2.0 / 60))
            if st.button(f"Look up home banners for {len(missing)} units (one-time, about {est} min)",
                         key=f"{prefix}_lookup"):
                bar = st.progress(0.0, text="Asking the Battle Cats Wiki…")
                client = WikiClient(CACHE)
                titles = lookup_titles(client, [(r["id"], r["name"], r["rarity"]) for r in missing],
                                       progress=lambda i, n: bar.progress(min(1.0, i / max(1, n)),
                                                                          text=f"Asking the Battle Cats Wiki… {i}/{n}"))
                bar.empty()
                known = {r["id"]: t for r in rows if r["home"] != "not looked up" for t in [None]}
                all_titles = dict(ss.get("home_titles", {}))
                all_titles.update(titles)
                ss.home_titles = all_titles
                rarities_of = {r["id"]: r["rarity"] for r in rows}
                rarities_of.update({int(k): v for k, v in ss.get("home_rarities", {}).items()})
                ss.home_rarities = {str(k): v for k, v in rarities_of.items()}
                ss.home_map = home_groups(all_titles, rarities_of)
                save_home_map(ss.home_map)
                rows = unit_rows(loaded, selected, display, only_current=not every,
                                 rarities=tuple(rarities_all), home=ss.home_map, group_by_home=True)
                info_box.empty()
    rows = [r for r in rows if r["rarity"] in rarities and row_matches(r, query)
            and (show == "all" or (show == "ticked") == r["selected"])
            and (not exclude or r["id"] not in exclude)]
    if by_home:
        banner_filter = f2.selectbox("Home banner", ["all"] + sorted({r["home"] for r in rows}), key=f"{prefix}_hbanner")
        if banner_filter != "all":
            rows = [r for r in rows if r["home"] == banner_filter]
    else:
        banner_filter = f2.selectbox("Banner", ["all"] + sorted({b for r in rows for b in r["banners"].split(", ")}),
                                     key=f"{prefix}_banner")
        if banner_filter != "all":
            rows = [r for r in rows if banner_filter in r["banners"].split(", ")]
    count_caption = st.empty()
    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Tick all shown", key=f"{prefix}_all"):
        selected.update(r["id"] for r in rows)
        ss[version_key] += 1
        persist()
    if b2.button("Untick all shown", key=f"{prefix}_none"):
        selected.difference_update(r["id"] for r in rows)
        ss[version_key] += 1
        persist()
    for r in rows:
        r["selected"] = r["id"] in selected
    if rows:
        need = [r["id"] for r in rows if not icons.path(r["id"]).exists()]
        if need:
            bar = st.progress(0.0, text=f"Fetching {len(need)} unit icons (once)…")
            icons.prefetch(need, progress=lambda i, n: bar.progress(min(1.0, i / max(1, n))))
            bar.empty()
        pdf = pd.DataFrame([{"ticked": r["selected"], "icon": icons.data_url(r["id"]), "name": r["name"],
                             "rarity": RARITY_LABEL.get(r["rarity"], r["rarity"]),
                             "home": r["home"] if by_home else "", "banners": r["banners"], "id": r["id"]}
                            for r in rows])
        if not by_home:
            pdf = pdf.drop(columns=["home"])
        editor_key = f"{prefix}_editor_{ss[version_key]}_{hash((tuple(rarities), scope, show, query, banner_filter, by_home))}"
        edited = st.data_editor(pdf, key=editor_key, hide_index=True, width="stretch", height=560,
                                row_height=max(35, icon_px() + 8),
                                disabled=["icon", "name", "rarity", "home", "banners", "id"],
                                column_config={"ticked": st.column_config.CheckboxColumn("", width=44),
                                               "icon": st.column_config.ImageColumn("", width=img_width()),
                                               "name": st.column_config.TextColumn("name", width=230),
                                               "rarity": st.column_config.TextColumn("rarity", width=110),
                                               "home": st.column_config.TextColumn("home banner", width=200),
                                               "banners": st.column_config.TextColumn("running now in", width=300),
                                               "id": st.column_config.NumberColumn("id", width=70)})
        changed = False
        shown = dict(zip(pdf["id"], pdf["ticked"]))
        for _, row in edited.iterrows():
            cid = int(row["id"])
            now = bool(row["ticked"])
            if now != bool(shown.get(cid, False)):
                if now:
                    selected.add(cid)
                else:
                    selected.discard(cid)
                changed = True
        if changed:
            persist()          # the editor keeps its own ticks; only bulk changes need a new editor key
    count_caption.caption(f"{len(rows)} units shown · {len(selected)} ticked in total")


# --------------------------------------------------------------------------------------
# Plan tab
# --------------------------------------------------------------------------------------
with tab_plan:
    if ss.result is None:
        st.info("Press **Plan** in the sidebar.")
    else:
        inputs, problem, res, rd, spend_opts, plat_opts = ss.result
        mode = ("proven optimal" if getattr(res.stats, "proven_optimal", False)
                else ("exact proof stopped after 120 s, best found shown" if getattr(res.stats, "timed_out", False)
                      else ("best found, not proven" if res.stats.truncated else "exact")))
        st.caption(f"Seed {inputs.seed}, last cat {names.get(inputs.last, inputs.last) if inputs.last else 'none'}, "
                   f"{len(inputs.owned)} owned units, {len(inputs.priority)} priority units, "
                   f"search {res.stats.seconds:.1f}s ({mode}).")
        st.toggle("Show new units in columns by rarity", key="plan_cols")
        if rd.best is None:
            st.info("No plan: check your resources.")
        else:
            st.subheader(rd.best.title)
            if not rd.best.actions and rd.all_in is not None and rd.best.keep:
                st.info(f"Best today: spend nothing. These banners give at most {rd.all_in.metrics.value:.1f}; what you "
                        f"hold is worth about {rd.best.keep['value']:.1f} kept. Move the outlook slider left, or turn "
                        f"the next-banner weighing off, to spend anyway.")
            plan_header(problem, rd.best, "best")
            plan_table(problem, rd.best, "tbl_best")
            if rd.all_in is not None:
                a, b = rd.all_in, rd.best
                a_total = a.metrics.value + (a.keep or {}).get("value", 0.0)
                b_total = b.metrics.value + (b.keep or {}).get("value", 0.0)
                with st.expander(f"Spend everything instead: {a.metrics.value:.1f} now, {a_total:.1f} with what is left; "
                                 f"the plan above: {b.metrics.value:.1f} now, {b_total:.1f} in all"):
                    plan_header(problem, a, "allin")
                    plan_table(problem, a, "tbl_allin")
        st.divider()
        if rd.coverage is not None:
            st.subheader("Cheapest way to get every missing unit on today's banners")
            plan_header(problem, rd.coverage, "cov")
            with st.expander("Show the steps"):
                plan_table(problem, rd.coverage, "tbl_cov")
        elif not bin(problem.targets_mask).count("1"):
            st.caption("You already own every valued unit on today's banners.")
        else:
            st.subheader("Every missing unit on today's banners")
            if rd.missing_targets:
                st.warning("Not reachable with these resources. Out of reach: " +
                           ", ".join(names.get(c, str(c)) for c in rd.missing_targets))
            for m, plan in rd.near_misses:
                with st.expander(f"{plan.title}: {plan.metrics.cost_draw_equivalents:.2f} draw-equivalents, value {plan.metrics.value:.2f}"):
                    plan_header(problem, plan, f"nm{m}")
                    plan_table(problem, plan, f"tbl_nm{m}")

# --------------------------------------------------------------------------------------
# Options tab
# --------------------------------------------------------------------------------------
with tab_opts:
    if ss.result is None:
        st.info("Press **Plan** first.")
    else:
        inputs, problem, res, rd, spend_opts, plat_opts = ss.result
        st.subheader("How much to spend")
        st.caption("One row per number of 11-draws: the best plan that spends exactly that cat food, with your "
                   "tickets and platinum tickets available. \"Later\" is what the row's leftovers are expected to "
                   "earn on the next banner; the row with the best total is the one to follow if the next banner "
                   "counts. Every row can be overlaid in the Tracks tab.")
        best_total_i = max(range(len(spend_opts)), key=lambda i: spend_opts[i].total) if spend_opts else -1
        for i, o in enumerate(spend_opts):
            with st.container(border=True):
                c1, c2 = st.columns([2, 5])
                c1.markdown(f"**{o.title}**" + (" &nbsp; ▶ best total" if i == best_total_i and o.later else ""),
                            unsafe_allow_html=True)
                c1.markdown(spend_html(o.tickets, o.cat_food, o.plats, o.legends), unsafe_allow_html=True)
                gain = f"+{o.delta_value:.1f} value vs the row above" if i else f"value {o.value:.1f}"
                c2.markdown(f"**{len(o.new_top)} new uber/legend, {o.new_supa} new super rare"
                            + (f", {o.new_rare} new rare" if o.new_rare else "") + f"** — {gain}"
                            + (f" &nbsp; · later +{o.later:.1f} → total {o.total:.1f}" if o.later else ""),
                            unsafe_allow_html=True)
                c2.markdown(units_html(o.new_top), unsafe_allow_html=True)
                if o.note:
                    c2.caption(o.note)
                if o.alt is not None:
                    a = o.alt
                    extra = [cid for cid in a.new_top if cid not in o.new_top]
                    c2.markdown(f"or, with {a.tickets} tickets: **{len(a.new_top)} new** — {units_html(extra, 6)} — "
                                f"value {a.value:.1f}" + (f", total {a.total:.1f}" if a.later else ""), unsafe_allow_html=True)
                    with st.expander(f"Steps for the {len(a.new_top)}-new plan"):
                        plan_header(problem, a.plan, f"alt{i}")
                        plan_table(problem, a.plan, f"tbl_alt{i}")
                with st.expander("Steps for this option"):
                    plan_header(problem, o.plan, f"opt{i}")
                    plan_table(problem, o.plan, f"tbl_opt{i}")
        if plat_opts:
            st.subheader("Are the platinum tickets worth using?")
            for i, o in enumerate(plat_opts):
                with st.container(border=True):
                    c1, c2 = st.columns([2, 5])
                    c1.markdown(f"**{o.title}**")
                    c1.markdown(spend_html(o.tickets, o.cat_food, o.plats, o.legends), unsafe_allow_html=True)
                    gain = f"+{o.delta_value:.1f} value versus without" if i else f"value {o.value:.1f}"
                    c2.markdown(f"**{len(o.new_top)} new uber/legend, {o.new_supa} new super rare"
                                + (f", {o.new_rare} new rare" if o.new_rare else "") + f"** — {gain}")
                    c2.markdown(units_html(o.new_top), unsafe_allow_html=True)
                    if o.note:
                        c2.caption(o.note)
            st.markdown("**Where a platinum ticket could go**")
            st.caption("Every position from the start to a little past the plan's end, and the uber a platinum "
                       "ticket gives there. ★ = on your Uber priority list, ✓ = new to you; those come first. "
                       "\"step\" is the plan step that starts at that position, where a platinum pull could be "
                       "slotted in (the rolls after it then shift by one position).")
            positions = platinum_positions(problem, rd.best, set(ss.uber_priority_ids))
            if positions:
                icons.prefetch([x.cat_id for x in positions[:60]])
                pdf = pd.DataFrame([{"position": x.label, "icon": icons.data_url(x.cat_id) or "", "uber": names.get(x.cat_id, x.cat_id),
                                     "priority": "★" if x.priority else "", "new": "✓" if x.new else "owned",
                                     "note": ("also obtained elsewhere in the plan" if x.gained_in_plan else ""),
                                     "step": str(x.step) if x.step is not None else ""} for x in positions])
                st.dataframe(pdf, hide_index=True, width="stretch", height=min(520, 40 + 36 * len(pdf)),
                             column_config={"icon": st.column_config.ImageColumn("", width=img_width()),
                                            "position": st.column_config.TextColumn("position", width=80),
                                            "uber": st.column_config.TextColumn("uber", width=230),
                                            "priority": st.column_config.TextColumn("★", width=40),
                                            "new": st.column_config.TextColumn("new", width=60),
                                            "step": st.column_config.TextColumn("step", width=60)})
        st.subheader("Pin a unit")
        pin = st.text_input("Best plan that includes this unit (name)", key="pin")
        if pin.strip():
            matches = [cid for cid, n in names.items() if n.lower() == pin.strip().lower()]
            if not matches:
                st.warning("No unit by that name.")
            else:
                labs = res.with_unit(matches[0])
                if not labs:
                    st.warning("No plan within your resources gets that unit.")
                else:
                    best_pin = min(labs, key=lambda l: (-l.value, res.cost(l)))
                    plan = make_plan(problem, res, best_pin, f"Best plan including {names[matches[0]]}")
                    plan_header(problem, plan, "pin")
                    plan_table(problem, plan, "tbl_pin")

# --------------------------------------------------------------------------------------
# Tracks tab: the site's two-track table with the plan overlaid
# --------------------------------------------------------------------------------------
with tab_tracks:
    st.subheader("Tracks A and B")
    tr_seed, tr_last, tr_event = parse_tracks_url(ss.tracks_url) if ss.tracks_url.strip() else (0, 0, None)
    if not tr_seed:
        st.info("Paste your tracks URL in the sidebar first.")
    else:
        ev_ids = list(loaded.banners)
        default_ev = tr_event if tr_event in loaded.banners else ev_ids[0]
        c1, c2, c3 = st.columns([3, 1, 1])
        tr_ev = c1.selectbox("Banner", ev_ids, index=ev_ids.index(default_ev),
                             format_func=lambda e: display.get(e, e), key="tr_banner")
        ss.setdefault("tr_rows", 50)
        tr_rows = c2.number_input("Rows", 10, 200, key="tr_rows", help="Defaults to the plan's rows plus 20.")
        tr_icons = c3.toggle("Icons", value=True, key="tr_icons")
        plans = {}
        plan_seed_ok = ss.result is not None and ss.result[0].seed == tr_seed and ss.result[0].last == tr_last
        if ss.result is not None:
            r_inputs, r_problem, r_res, r_rd, r_spend, r_plat = ss.result
            if r_rd.best:
                plans[r_rd.best.title] = r_rd.best                       # Max value
            if r_rd.all_in:
                plans[r_rd.all_in.title] = r_rd.all_in                   # Spend everything
            if r_rd.coverage:
                plans["Every missing unit on today's banners"] = r_rd.coverage
            for _m, nm in r_rd.near_misses:
                plans[nm.title] = nm                                     # All but m missing unit(s)
            for o in r_spend:
                plans[o.title] = o.plan
                if o.alt is not None:
                    plans[f"{o.title}: most new ubers, {o.alt.tickets} tickets"] = o.alt.plan
        overlay = None
        if plans:
            o1, o2, o3 = st.columns([1, 1, 3])
            tr_overlay = o1.toggle("Overlay plan", value=True, key="tr_overlay")
            tr_follow = o2.toggle("Follow the plan's banners", value=False, key="tr_follow",
                                  help="Positions spent on another banner show that banner's unit, and the margin "
                                       "notes banner changes and track changes.")
            if ss.get("tr_plan") not in plans:          # the plan names change with every Plan press
                ss.tr_plan = next(iter(plans))
            tr_which = o3.selectbox("Plan to overlay", list(plans), key="tr_plan")
            if tr_overlay and not plan_seed_ok:
                st.warning("The plan was made for a different seed or last cat than the URL in the sidebar; press Plan again.")
            elif tr_overlay:
                overlay = plan_overlay(plans[tr_which], tr_ev, {e: display.get(e, e) for e in loaded.banners},
                                       follow=bool(tr_follow))
        else:
            st.caption("Press Plan to be able to overlay a path here.")
        tr_banner = loaded.banners[tr_ev]
        tables = ss.result[1].tables if plan_seed_ok else Tables(tr_seed, 2 * int(tr_rows) + 80)
        exclusive = {cid for cid, h in ss.home_map.items() if h == "Single-banner exclusives"}
        html = render_tracks_html(tables, tr_banner, tr_last, int(tr_rows), names, set(ss.owned_ids), set(), exclusive,
                                  overlay, icon_url=(icons.data_url if tr_icons else None), icon_px=min(icon_px(), 40),
                                  banner_title=display.get(tr_ev, tr_banner.name))
        st.html(html)

# --------------------------------------------------------------------------------------
# Owned units tab
# --------------------------------------------------------------------------------------
with tab_owned:
    st.subheader("What you own")
    unit_picker("owned_ids", "owned_version", "own", ["legend", "uber", "supa", "rare", "special", "normal"],
                ["legend", "uber", "supa"],
                "Tick the units you have. An unticked rare counts as new (worth a new super). Sorted by rarity, then banner.")
    st.divider()

    @st.fragment
    def owned_transfer():
        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Export** (copy this text somewhere safe; paste it back later)")
            if st.button("Generate export text"):
                ss.export_blob = export_text(sorted(ss.owned_ids), names, ss.game_version, ss.plan_date)
            if ss.get("export_blob"):
                st.text_area("Export text", ss.export_blob, height=200, key="export_text")
        with e2:
            st.markdown("**Import**: paste an export, the site's cats-page URL with `o=`, or a bare code")
            imp = st.text_area("Import text", key="import_text", height=200)
            if st.button("Import and replace my owned list"):
                res_imp = import_text(imp, loaded.catalog, names, ss.game_version)
                ss.owned_ids = set(res_imp.ids)
                ss.owned_version += 1
                persist()
                for n in res_imp.notes:
                    st.info(n)
                st.success(f"Imported {len(res_imp.ids)} owned units. The grid above updates on your next click.")

    owned_transfer()
    st.divider()

    @st.fragment
    def guide_import():
        SKIP, OTHER = "Skip this cell", "Another unit…"
        st.markdown("**Import from Cat Guide screenshots**")
        st.caption("In the game open the Cat Guide, choose a rarity with Filter and screenshot every page of the 6 × 4 "
                   "grid; do every tab (Normal, Special, Rare, Super Rare, Uber, Legend) for a complete list. Owned "
                   "units are recognised from their icons, grey ? cells are skipped, and anything doubtful is shown to "
                   "you with its picture. Units are only ever added to your list.")
        c1, c2 = st.columns(2)
        uploads = c1.file_uploader("Screenshots", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True,
                                   key="guide_files")
        folder = "" if STATELESS else c2.text_input("…or a folder on this computer", key="guide_folder",
                                                     placeholder=r"C:\Users\you\Pictures\cat guide")
        if st.button("Read screenshots", key="guide_read"):
            files = [(f.name, f.getvalue()) for f in (uploads or [])]
            if folder.strip():
                fp = Path(folder.strip())
                if fp.is_dir():
                    files += [(p.name, p.read_bytes()) for p in sorted(fp.iterdir())
                              if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
                else:
                    st.error("That folder does not exist.")
            if not files:
                st.warning("No screenshots given.")
            elif loaded.catalog is None:
                st.error("The unit list could not be loaded, so icons cannot be matched.")
            else:
                need = [c.id for c in loaded.catalog.cats.values() if not icons.path(c.id).exists()]
                if need:
                    bar = st.progress(0.0, text=f"Fetching {len(need)} unit icons (once)…")
                    icons.prefetch(need, progress=lambda i, n: bar.progress(min(1.0, i / max(1, n))))
                    bar.empty()
                lib = IconLibrary(CACHE / "icons", loaded.catalog)
                with st.spinner(f"Reading {len(files)} screenshot(s)…"):
                    pages = read_pages(files, lib)
                ss.guide_pages = [{"name": p.name, "cells": len(p.cells), "unknown": p.unknown, "rarity": p.rarity,
                                   "found": [{"row": c.row, "col": c.col, "kind": c.kind, "id": c.cat_id, "name": c.name,
                                              "rarity": c.rarity, "score": c.score, "margin": c.margin, "sure": c.sure,
                                              "check": c.needs_check, "runner": c.runner_up_name,
                                              "candidates": c.candidates, "png": png_bytes(c.crop, 96)}
                                             for c in p.cells if c.kind != "?"]} for p in pages]
                ss.guide_units = lib.all_units()
                ss.guide_version = ss.get("guide_version", 0) + 1
        pages = ss.get("guide_pages")
        if not pages:
            return
        ver = ss.get("guide_version", 0)
        sure_rows, checks = [], []
        for p in pages:
            st.write(f"{p['name']}: {p['cells']} cells · {len(p['found'])} owned · {p['unknown']} not owned (?)"
                     + (f" · looks like the {RARITY_LABEL.get(p['rarity'], p['rarity'])} tab" if p["rarity"] else "")
                     + ("  — no grid found; is this a Cat Guide page?" if p["cells"] == 0 else ""))
            for c in p["found"]:
                (checks if c["check"] else sure_rows).append((p, c))
        chosen: set[int] = set()
        if sure_rows:
            st.markdown(f"**Recognised with confidence: {len(sure_rows)} cells** (untick any you do not want)")
            gdf = pd.DataFrame([{"add": True, "screenshot": data_url(c["png"]), "match": icons.data_url(c["id"]) or "",
                                 "unit": c["name"], "rarity": RARITY_LABEL.get(c["rarity"], c["rarity"]),
                                 "score": c["score"], "already ticked": c["id"] in ss.owned_ids, "id": c["id"],
                                 "page": p["name"], "cell": f"r{c['row'] + 1}c{c['col'] + 1}"} for p, c in sure_rows])
            gedit = st.data_editor(gdf, key=f"guide_editor_{ver}", hide_index=True, width="stretch",
                                   row_height=max(35, icon_px() + 8), height=min(600, 40 + 60 * len(gdf)),
                                   disabled=[col for col in gdf.columns if col != "add"],
                                   column_config={"add": st.column_config.CheckboxColumn("add", width=44),
                                                  "screenshot": st.column_config.ImageColumn("screenshot", width=img_width()),
                                                  "match": st.column_config.ImageColumn("match", width=img_width()),
                                                  "unit": st.column_config.TextColumn("unit", width=230),
                                                  "rarity": st.column_config.TextColumn("rarity", width=110),
                                                  "score": st.column_config.NumberColumn("score", width=70, format="%.2f"),
                                                  "id": st.column_config.NumberColumn("id", width=70)})
            chosen |= {int(row["id"]) for _, row in gedit.iterrows() if row["add"]}
        if checks:
            st.markdown(f"**What unit is this?** {len(checks)} cell(s) need your eye. The best guess is preselected; "
                        f"pick another unit, or *{SKIP}* to leave it out.")
            for p, c in checks:
                key = f"guide_pick_{ver}_{p['name']}_{c['row']}_{c['col']}"
                left, right = st.columns([1, 3])
                left.image(c["png"], caption=f"{p['name']} r{c['row'] + 1}c{c['col'] + 1}")
                reason = {"egg": "is an Ancient Egg (they all look alike); the guess comes from its position in the tab",
                          "unknown": "matched nothing in the icon library"}.get(c["kind"], f"could also be {c['runner']}")
                options = [f"{n}  ({cid})" for cid, n, s in c["candidates"]] + [SKIP, OTHER]
                default = len(options) - 2 if c["kind"] == "unknown" else 0
                choice = right.selectbox(f"What unit is this? It {reason}.", options, index=default, key=key)
                if choice == OTHER:
                    choice = right.selectbox("Which unit?", [f"{n}  ({cid})" for cid, n in ss.guide_units], key=key + "_o")
                m = re.search(r"\((\d+)\)$", choice)
                if m:
                    chosen.add(int(m.group(1)))
        if st.button(f"Add {len(chosen)} units to my owned list", key=f"guide_add_{ver}"):
            new = chosen - ss.owned_ids
            ss.owned_ids |= chosen
            ss.owned_version += 1
            persist()
            st.success(f"Added {len(new)} new units ({len(chosen) - len(new)} were already ticked). "
                       f"The grid above updates on your next click.")

    guide_import()

# --------------------------------------------------------------------------------------
# Priority units tab
# --------------------------------------------------------------------------------------
with tab_ubers:
    st.subheader("Ubers you want most")
    unit_picker("uber_priority_ids", "uber_version", "upri", ["uber"], ["uber"],
                "Tick the ubers you do not own yet that you care about most. They sort to the top of the platinum "
                "table in Options, and with an Uber priority multiplier above 1 (Advanced) the plan itself favours "
                "them. Owned ubers are not shown here.", exclude=ss.owned_ids, every_default=False)
    st.divider()

    @st.fragment
    def uber_transfer():
        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Export uber priority list** (copy this text somewhere safe; paste it back later)")
            if st.button("Generate uber priority export text"):
                ss.uber_blob = export_text(sorted(ss.uber_priority_ids), names, ss.game_version, ss.plan_date, kind="UBERS")
            if ss.get("uber_blob"):
                st.text_area("Uber priority export text", ss.uber_blob, height=200, key="uber_export_text")
        with e2:
            st.markdown("**Import uber priority list**: paste an export (or a bare code)")
            imp = st.text_area("Uber priority import text", key="uber_import_text", height=200)
            if st.button("Import and replace my uber priority list"):
                res_imp = import_text(imp, loaded.catalog, names, ss.game_version)
                if res_imp.kind != "UBERS" and imp.strip().startswith("BCPLANNER-"):
                    st.warning("That export belongs to another tab (owned units or wanted copies).")
                else:
                    ss.uber_priority_ids = set(res_imp.ids)
                    ss.uber_version += 1
                    persist()
                    for n in res_imp.notes:
                        st.info(n)
                    st.success(f"Imported {len(res_imp.ids)} ubers. The grid above updates on your next click.")

    uber_transfer()

with tab_prio:
    st.subheader("Units you want extra copies of")
    st.toggle("Allow a one-day clock change to reach a wanted copy", key="priority_skip",
              help="Only for single tickets. The planner may set the date forward and back around one roll.")
    unit_picker("priority_ids", "priority_version", "prio", ["supa", "rare", "uber", "legend"], ["supa", "rare"],
                "These only decide which banner a single ticket is rolled on. When two banners give the same "
                "value at a slot, the one with a ticked unit is chosen; nothing else in the plan changes.")
    st.divider()

    @st.fragment
    def wanted_transfer():
        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Export wanted list** (copy this text somewhere safe; paste it back later)")
            if st.button("Generate wanted export text"):
                ss.wanted_blob = export_text(sorted(ss.priority_ids), names, ss.game_version, ss.plan_date, kind="WANTED")
            if ss.get("wanted_blob"):
                st.text_area("Wanted export text", ss.wanted_blob, height=200, key="wanted_export_text")
        with e2:
            st.markdown("**Import wanted list**: paste a wanted export (or a bare code)")
            imp = st.text_area("Wanted import text", key="wanted_import_text", height=200)
            if st.button("Import and replace my wanted list"):
                res_imp = import_text(imp, loaded.catalog, names, ss.game_version)
                if res_imp.kind != "WANTED" and imp.strip().startswith("BCPLANNER-OWNED"):
                    st.warning("That is an owned-units export; paste it in the Owned units tab instead.")
                else:
                    ss.priority_ids = set(res_imp.ids)
                    ss.priority_version += 1
                    persist()
                    for n in res_imp.notes:
                        st.info(n)
                    st.success(f"Imported {len(res_imp.ids)} wanted units. The grid above updates on your next click.")

    wanted_transfer()

# --------------------------------------------------------------------------------------
# Banners tab
# --------------------------------------------------------------------------------------
with tab_banners:
    st.subheader("Banners open today and tomorrow")
    st.caption("Guaranteed flags are set in the sidebar under Banner options; the 750 CF first-draw offer is a plan-level checkbox there too.")
    records = []
    for ev, b in loaded.banners.items():
        unowned = [names.get(c, str(c)) for r, pool in b.pools.items() for c in pool if c not in ss.owned_ids]
        records.append({
            "event": ev, "include": b.include, "banner": display.get(ev, b.name), "kind": b.kind,
            "from": b.start.isoformat(), "to": b.end.isoformat(),
            "rates %": "/".join(f"{x / 100:g}" for x in b.rates),
            "guaranteed": b.guaranteed_rolls,
            "11-draw offered": b.offers_eleven and b.kind == "rare",
            "counts for coverage": b.counts_for_coverage and b.kind == "rare",
            "unowned": len(unowned), "site blurb": b.name,
        })
    df = pd.DataFrame(records)
    edited = st.data_editor(
        df, key="banner_editor", hide_index=True, width="stretch",
        disabled=["event", "banner", "kind", "from", "to", "rates %", "guaranteed", "unowned", "site blurb"],
    )
    overrides = {}
    for _, row in edited.iterrows():
        b = loaded.banners[row["event"]]
        ov = {"include": bool(row["include"]), "offers_eleven": bool(row["11-draw offered"]),
              "counts_for_coverage": bool(row["counts for coverage"])}
        for k, v in ov.items():
            setattr(b, k, v)
        overrides[row["event"]] = ov
    ss.banner_overrides = overrides

# --------------------------------------------------------------------------------------
# Checks tab
# --------------------------------------------------------------------------------------
with tab_checks:
    if ss.result is not None:
        inputs, problem, res, rd, _, _ = ss.result
        st.caption(f"Search {res.stats.seconds:.1f} s · {res.stats.labels_created} partial plans · "
                   f"{'best found, not proven' if res.stats.truncated else 'exact'} · "
                   f"{len(problem.unit_ids)} unowned units with value · {bin(problem.targets_mask).count('1')} coverage targets")
    if loaded.notes:
        for n in loaded.notes:
            st.write("• " + n)
    else:
        st.success("Every banner page reproduced by the simulation.")
    for n in ss.get("wiki_notes", []):
        st.write("• wiki: " + n)

owned_caption.caption(f"Owned units: {len(ss.owned_ids)} ticked · uber priority: {len(ss.uber_priority_ids)} · "
                      f"wanted copies: {len(ss.priority_ids)} ticked.")

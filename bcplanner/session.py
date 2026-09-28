"""Assembly shared by the CLI and the GUI: inputs -> banners -> problem -> search -> readings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .future import FutureModel, FutureValue
from .metrics import Metrics, compute
from .model import DEFAULT_DUPE_VALUES, DEFAULT_PASS_PENALTIES, DEFAULT_TICKET_COST, DEFAULT_WEIGHTS, Banner, Catalog
from .problem import Problem
from .replay import ReplayResult, replay
from .scrape import SiteData, infer_guaranteed_rolls, parse_cats, parse_details
from .search import Label, SearchResult, coverage_problem, search, search_exact
from .wiki import NOT_GACHA_GROUP
from .sim import Tables


@dataclass
class Inputs:
    seed: int
    last: int = 0
    today: date = field(default_factory=date.today)
    owned: frozenset[int] = frozenset()
    tickets: int = 0
    cat_food: int = 0
    plats: int = 0
    legends: int = 0
    tickets_per_draw: float = 30.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    multipliers: dict[int, float] = field(default_factory=dict)
    dupe_values: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DUPE_VALUES))
    pass_penalties: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PASS_PENALTIES))
    ticket_cost: float = DEFAULT_TICKET_COST
    exact_time_limit: float = 120.0          # seconds the exact proof may take before the beam result is kept
    forbid_eleven_over_legend_slot: bool = True
    legend_substitute_only: bool = True     # legend tickets only stand in for a rare ticket on a must-cross repeat slot
    max_clock_changes: int = 4
    skip_penalty: float = 0.02
    beam: int | None = 12
    mode: str = "normal"                    # normal (beam 12) | thorough (beam 30) | exact (proven optimal)
    priority: frozenset[int] = frozenset()   # wanted extra copies; only re-routes single tickets
    priority_allow_skip: bool = False
    discount_first_draw: bool = False        # the plan's first 11-draw costs 750 CF
    future: FutureModel = field(default_factory=FutureModel)   # what leftovers are worth on the next banner


@dataclass
class Loaded:
    banners: dict[str, Banner]
    names: dict[int, str]
    catalog: Catalog | None
    notes: list[str]                       # self-test problems, warnings


@dataclass
class Plan:
    title: str
    label: Label
    actions: list[tuple]
    replay: ReplayResult
    metrics: Metrics
    rerouted: list[int] = field(default_factory=list)   # offsets of singles moved to a priority banner
    keep: dict | None = None      # leftovers and what they are expected to be worth on the next banner


def parse_tracks_url(url: str) -> tuple[int, int, str | None]:
    """seed, last, event from a bc.godfat.org tracks URL (or 'seed' / 'seed,last' text)."""
    text = url.strip()
    if "=" in text:
        query = urlsplit(text).query if "://" in text or text.startswith("/") else text
        params = parse_qs(query.lstrip("?"))
        seed = int(params.get("seed", ["0"])[0] or 0)
        last = int(params.get("last", ["0"])[0] or 0)
        event = params.get("event", [None])[0]
        return seed, last, event
    parts = [p for p in re.split(r"[\s,]+", text) if p]
    seed = int(parts[0]) if parts else 0
    last = int(parts[1]) if len(parts) > 1 else 0
    return seed, last, None


def load_live(plan_date: date, cache_dir: Path, refresh: bool = False, progress=None, workers: int = 3) -> Loaded:
    """Every banner live on the plan date or the day after, plus the cat list. Pages come from the cache
    when fresh; the rest are fetched a few at a time (the site can take a minute per page). `progress`
    is called as progress(done, total) from the calling thread."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sd = SiteData(cache_dir, plan_date, refresh=refresh)
    notes: list[str] = []
    events = sd.live_events()
    results: dict[str, object] = {}
    catalog = None
    total = len(events) + 1
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(sd.banner, ev.event_id, ev.start <= plan_date): ev.event_id for ev in events}
        cat_fut = pool.submit(sd.catalog)
        futs[cat_fut] = None
        for fut in as_completed(futs):
            done += 1
            if progress is not None:
                progress(done, total)
            ev_id = futs[fut]
            try:
                out = fut.result()
            except Exception as exc:  # noqa: BLE001 - surface every failure to the user
                notes.append(f"{ev_id or 'catalog'}: could not load ({exc})")
                continue
            if ev_id is None:
                catalog = out
            else:
                results[ev_id] = out
    banners: dict[str, Banner] = {}
    for ev in events:                              # keep the site's order
        if ev.event_id not in results:
            continue
        b, rolls, problems = results[ev.event_id]
        for p in problems:
            notes.append(f"{ev.event_id} self-test: {p}")
        banners[ev.event_id] = b
    notes += merge_repeats(banners)
    notes = sd.notes + notes
    _check_shared_pool(banners, notes)
    return Loaded(banners=banners, names=dict(sd.names), catalog=catalog, notes=notes)


def load_fixtures(fixtures_dir: Path, event_ids: list[str], plan_date: date) -> Loaded:
    banners, names, notes = {}, {}, []
    for ev in event_ids:
        page = (fixtures_dir / f"details_{ev}.html").read_text(encoding="utf-8")
        b, n = parse_details(page, ev)
        b.guaranteed_rolls = infer_guaranteed_rolls(page, b)
        b.provisional = b.start > plan_date
        banners[ev] = b
        names.update(n)
    catalog = None
    cats_page = fixtures_dir / "cats.html"
    if cats_page.exists():
        catalog = parse_cats(cats_page.read_text(encoding="utf-8"))
    _check_shared_pool(banners, notes)
    return Loaded(banners=banners, names=names, catalog=catalog, notes=notes)


def merge_repeats(banners: dict[str, Banner]) -> list[str]:
    """The game schedules the same gacha in back-to-back windows (2026-06-08_974, then 2026-06-11_974).
    When the pools, rates and guaranteed flag agree and the windows touch, that is one banner: keep the
    earlier window and extend it to the later end date, so the list does not show it twice."""
    notes: list[str] = []
    by_gacha: dict[int, list[tuple[str, Banner]]] = {}
    for ev, b in sorted(banners.items(), key=lambda kv: (kv[1].start, kv[0])):
        by_gacha.setdefault(b.gacha_id, []).append((ev, b))
    for items in by_gacha.values():
        keep_ev, keep = items[0]
        for ev, b in items[1:]:
            same = b.pools == keep.pools and b.rates == keep.rates and b.guaranteed_rolls == keep.guaranteed_rolls
            if same and b.start <= keep.end:
                keep.end = max(keep.end, b.end)
                del banners[ev]                # silently: one banner, one entry
            else:
                keep_ev, keep = ev, b
    return notes


def _check_shared_pool(banners: dict[str, Banner], notes: list[str]) -> None:
    plat = next((b for b in banners.values() if b.kind == "platinum"), None)
    leg = next((b for b in banners.values() if b.kind == "legend"), None)
    if plat and leg and plat.pool("uber") != leg.pool("uber"):
        notes.append("platinum and legend banners do NOT share the same uber list; legend tickets will be simulated "
                     "with the legend banner's own list")


def wishlist_multipliers(text: str, catalog: Catalog | None, names: dict[int, str],
                         default_multiplier: float) -> tuple[dict[int, float], list[str]]:
    """Lines of 'name or id[, multiplier]' -> {cat id: multiplier}, plus unresolved lines."""
    out: dict[int, float] = {}
    errors: list[str] = []
    by_name = {v.lower(): k for k, v in names.items()}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        key = parts[0]
        mult = float(parts[1]) if len(parts) > 1 and parts[1] else default_multiplier
        cid = None
        if key.isdigit():
            cid = int(key)
        elif key.lower() in by_name:
            cid = by_name[key.lower()]
        elif catalog is not None:
            found = catalog.find_by_name(key)
            if len(found) == 1:
                cid = found[0].id
            elif len(found) > 1:
                errors.append(f"'{key}' matches several units: " + ", ".join(f"{c.name} ({c.id})" for c in found[:6]))
                continue
        if cid is None:
            errors.append(f"'{key}' not found")
            continue
        out[cid] = mult
    return out, errors


def build_problem(inputs: Inputs, banners: dict[str, Banner]) -> Problem:
    horizon = 2 * inputs.tickets + 22 * (inputs.cat_food // 1500 + 1) + 2 * inputs.plats + 2 * inputs.legends + 80
    tables = Tables(inputs.seed, horizon)
    return Problem(
        tables=tables, banners=banners, owned=frozenset(inputs.owned), today=inputs.today, last_id=inputs.last,
        tickets=inputs.tickets, cat_food=inputs.cat_food, plats=inputs.plats, legends=inputs.legends,
        tickets_per_draw=inputs.tickets_per_draw, forbid_eleven_over_legend_slot=inputs.forbid_eleven_over_legend_slot,
        legend_substitute_only=inputs.legend_substitute_only,
        max_clock_changes=inputs.max_clock_changes, skip_penalty=inputs.skip_penalty,
        weights=dict(inputs.weights), multipliers=dict(inputs.multipliers), dupe_values=dict(inputs.dupe_values),
        pass_penalties=dict(inputs.pass_penalties), ticket_cost=inputs.ticket_cost,
        priority=frozenset(inputs.priority), priority_allow_skip=inputs.priority_allow_skip,
        discount_first_draw=inputs.discount_first_draw,
    )


def make_plan(problem: Problem, res: SearchResult, label: Label, title: str,
              future: FutureValue | None = None) -> Plan:
    from .priority import apply_priorities

    actions = res.plan_actions(label)         # `res` may belong to the coverage copy; actions are what matter
    actions, rerouted = apply_priorities(problem, actions)
    rep = replay(problem, actions)
    keep = None
    if future is not None and future.m.mode != "none":
        left = (problem.tickets - rep.tickets, problem.cf_units - rep.cf_units, problem.plats - rep.plats,
                problem.legends - rep.legends)
        keep = {"tickets": left[0], "cf_units": left[1], "plats": left[2], "legends": left[3],
                **future.describe(rep.end_offset, *left)}
    return Plan(title=title, label=label, actions=actions, replay=rep, metrics=compute(problem, rep),
                rerouted=rerouted, keep=keep)


@dataclass
class Readings:
    best: Plan | None
    coverage: Plan | None
    near_misses: list[tuple[int, Plan]]
    knees: list[Plan]
    envelope: list[Label]
    frontier: list[Label]
    heatmap: list[list[float]]
    missing_targets: list[int]        # unowned units on today's banners that no plan reaches
    all_in: Plan | None = None        # the most value now, ignoring the next banner (when it differs from best)


def readings(problem: Problem, res: SearchResult, min_marginal: float = 0.5,
             cov_res: SearchResult | None = None, future: FutureValue | None = None) -> Readings:
    """`cov_res` is an optional result of the coverage problem (one point per target unit); when
    given, the coverage plan and near misses come from it instead of the value search. With a
    `future` value the best plan is the one with the most value now plus expected value later."""
    best_now = res.best_value()
    best = res.best_total(future) if future is not None and future.m.mode != "none" else best_now
    n_targets = bin(problem.targets_mask).count("1")
    if cov_res is not None and n_targets:
        full = [lab for lab in cov_res.candidates() if lab.value >= n_targets - 1e-9]
        cov = min(full, key=lambda lab: (cov_res.cost(lab), lab.skips, lab.k)) if full else None
        near = []
        for m in range(1, 4):
            part = [lab for lab in cov_res.candidates() if abs(lab.value - (n_targets - m)) < 1e-9]
            if part:
                near.append((m, min(part, key=lambda lab: (cov_res.cost(lab), lab.k))))
        reach_src = cov_res
    else:
        cov = res.cheapest_covering()
        near = res.near_misses(3)
        reach_src = res
    reachable = 0
    for lab in reach_src.labels:
        reachable |= lab.gained
    if cov_res is not None and n_targets:
        missing = [cid for cid in problem.mask_ids(problem.targets_mask)
                   if not any(lab.gained & cov_res.problem.bit(cid) for lab in cov_res.labels)]
    else:
        missing = problem.mask_ids(problem.targets_mask & ~reachable)
    all_in = None
    if best_now is not None and best is not None and best_now is not best and future is not None:
        all_in = make_plan(problem, res, best_now, "Spend everything", future)
    return Readings(
        best=make_plan(problem, res, best, "Max value", future) if best else None,
        all_in=all_in,
        coverage=make_plan(problem, cov_res or res, cov, "Cheapest way to get every missing unit on today's banners") if cov else None,
        near_misses=[(m, make_plan(problem, cov_res or res, lab, f"All but {m} missing unit(s)")) for m, lab in near],
        knees=[make_plan(problem, res, lab, f"Knee point {i + 1}") for i, lab in enumerate(res.knees(min_marginal))],
        envelope=res.envelope(),
        frontier=res.frontier(),
        heatmap=res.heatmap(),
        missing_targets=missing,
    )


def run(inputs: Inputs, banners: dict[str, Banner], progress=None) -> tuple[Problem, SearchResult]:
    """Value search. For mode 'exact' the result is proven optimal (stats.proven_optimal)."""
    problem = build_problem(inputs, banners)
    if inputs.mode == "exact":
        res = search_exact(problem, beam_first=30, progress=progress, time_limit=inputs.exact_time_limit)
    elif inputs.mode == "thorough":
        res = search(problem, beam=30, progress=progress)
    else:
        res = search(problem, beam=inputs.beam if inputs.beam else 12, progress=progress)
    return problem, res


def run_coverage(inputs: Inputs, problem: Problem, progress=None) -> SearchResult | None:
    """Coverage search over today's targets only (each worth one point). Exact in exact mode."""
    if not problem.targets_mask:
        return None
    cp = coverage_problem(problem)
    if inputs.mode == "exact":
        return search_exact(cp, beam_first=30, progress=progress)
    return search(cp, beam=30 if inputs.mode == "thorough" else 12, progress=progress)


# ---------------------------------------------------------------------------------------
# Display names, saved settings, unit rows for the owned-units picker
# ---------------------------------------------------------------------------------------
import json  # noqa: E402

from .report import short_banner_name  # noqa: E402

KIND_NAMES = {"platinum": "Platinum Capsules", "legend": "Legend Capsules"}


def display_names(banners: dict[str, Banner], names: dict[int, str], cache_dir: Path,
                  use_wiki: bool = True, progress=None) -> tuple[dict[str, str], list[str]]:
    """event_id -> name to show: the official title from the wiki (aliased), else the cleaned blurb."""
    from .wiki import WikiClient, display_name

    out: dict[str, str] = {}
    notes: list[str] = []
    client = WikiClient(cache_dir) if use_wiki else None
    for ev, b in banners.items():
        if b.kind in KIND_NAMES:
            out[ev] = KIND_NAMES[b.kind]
            continue
        official = None
        if client is not None:
            try:
                official, bnotes = client.banner_title(b, names, progress)
                notes.extend(f"{ev}: {n}" for n in bnotes)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"{ev}: wiki lookup failed ({exc})")
        out[ev] = display_name(official, short_banner_name(b.name))
    return out, notes


def load_settings(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def unit_rows(loaded: Loaded, selected: set[int], display: dict[str, str], only_current: bool = True,
              rarities: tuple[str, ...] = ("legend", "uber", "supa"), home: dict[int, str] | None = None,
              group_by_home: bool = False) -> list[dict]:
    """One row per gacha unit for a picker: id, name, rarity, current banners, home set, selected.

    With `group_by_home` the rows are ordered by rarity, then the unit's home set (from the wiki),
    then name; otherwise by rarity, then the banners it is currently in, then name."""
    in_banners: dict[int, list[str]] = {}
    rarity_of: dict[int, str] = {}
    for ev, b in loaded.banners.items():
        label = display.get(ev, ev)
        for r, pool in b.pools.items():
            for cid in pool:
                rarity_of.setdefault(cid, r)
                in_banners.setdefault(cid, [])
                if label not in in_banners[cid]:
                    in_banners[cid].append(label)
    names = dict(loaded.names)
    if loaded.catalog is not None:
        for cid, cat in loaded.catalog.cats.items():
            names.setdefault(cid, cat.name)
            rarity_of.setdefault(cid, cat.rarity)
    rows = []
    for cid, r in rarity_of.items():
        if r not in rarities:
            continue
        if only_current and cid not in in_banners:
            continue
        if cid not in in_banners and cid not in selected and (home or {}).get(cid) == NOT_GACHA_GROUP:
            continue                      # stage rewards etc. listed on the site's cat page; never in a capsule
        rows.append({"id": cid, "name": names.get(cid, str(cid)), "rarity": r,
                     "banners": ", ".join(in_banners.get(cid, [])) or "not in a current banner",
                     "home": (home or {}).get(cid, "not looked up"),
                     "selected": cid in selected})
    order = {"legend": 0, "uber": 1, "supa": 2, "rare": 3}
    if group_by_home:
        rows.sort(key=lambda x: (order.get(x["rarity"], 9), x["home"], x["name"]))
    else:
        rows.sort(key=lambda x: (order.get(x["rarity"], 9), x["banners"], x["name"]))
    return rows


def row_matches(row: dict, query: str) -> bool:
    """Picker search: matches the unit name, its home banner, or a banner it is running in now."""
    q = query.strip().lower()
    if not q:
        return True
    return any(q in str(row.get(field, "")).lower() for field in ("name", "home", "banners"))

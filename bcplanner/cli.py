"""Command-line planner. Example:

  python -m bcplanner.cli --url "https://bc.godfat.org/?seed=3163852999&last=689&event=2026-09-11_1076" \
      --owned "https://bc.godfat.org/cats?o=..." --tickets 30 --cf 6000 --plats 3 --legends 1 --out plan.md

Use --fixtures to plan from the saved pages in tests/fixtures instead of the live site.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .actions import describe
from .owned import parse_owned_input
from .report import to_csv, to_markdown
from .session import (Inputs, display_names, load_fixtures, load_live, parse_tracks_url, readings, run,
                      run_coverage, wishlist_multipliers)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_EVENTS = ["2026-09-11_1002", "2026-09-11_1059", "2026-09-11_1076", "2026-09-14_991",
                  "2026-07-24_1063", "2026-07-24_1064"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Battle Cats pull planner")
    ap.add_argument("--url", help="bc.godfat.org tracks URL (seed, last, event)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--last", type=int, default=0)
    ap.add_argument("--owned", default="", help="cats-page URL with o=, a bare o= value, or @file")
    ap.add_argument("--date", type=date.fromisoformat, default=date.today(), help="plan date, YYYY-MM-DD")
    ap.add_argument("--tickets", type=int, default=0)
    ap.add_argument("--cf", type=int, default=0, help="cat food available")
    ap.add_argument("--plats", type=int, default=0, help="platinum tickets to use")
    ap.add_argument("--legends", type=int, default=0, help="legend tickets available")
    ap.add_argument("--rate", type=float, default=30.0, help="rare tickets worth one 11-draw")
    ap.add_argument("--supa", type=float, default=0.8)
    ap.add_argument("--uber", type=float, default=1.0)
    ap.add_argument("--legend-weight", type=float, default=8.0)
    ap.add_argument("--dupe-super", type=float, default=0.05, help="value of a repeat super rare (0 = only new units count)")
    ap.add_argument("--dupe-uber", type=float, default=0.2, help="value of a repeat uber: makes uber slots count even when the uber repeats")
    ap.add_argument("--dupe-legend", type=float, default=0.0, help="value of a repeat legend")
    ap.add_argument("--pass-uber", type=float, default=0.8, help="cost of going past an uber slot on the other track")
    ap.add_argument("--pass-fest", type=float, default=0.2, help="cost of going past an Uberfest-only uber slot on the other track")
    ap.add_argument("--pass-legend", type=float, default=5.0, help="cost of going past a legend slot on the other track")
    ap.add_argument("--ticket-cost", type=float, default=0.02, help="value charged per rare ticket spent")
    ap.add_argument("--wishlist", help="file of 'name or id[, multiplier]' lines")
    ap.add_argument("--multiplier", type=float, default=3.0, help="default wishlist multiplier")
    ap.add_argument("--guaranteed", action="append", default=[], metavar="EVENT=0|11|15")
    ap.add_argument("--discount", action="store_true", help="the plan's first 11-draw costs 750 CF")
    ap.add_argument("--no-eleven", action="append", default=[], metavar="EVENT", help="banner offers no 11-draw")
    ap.add_argument("--exclude", action="append", default=[], metavar="EVENT")
    ap.add_argument("--allow-eleven-over-legend", action="store_true")
    ap.add_argument("--max-skips", type=int, default=4)
    ap.add_argument("--beam", type=int, default=12, help="partial plans kept per state (12 normal, 30 thorough)")
    ap.add_argument("--exact", action="store_true", help="prove optimality with the bounded full search (slower)")
    ap.add_argument("--refresh", action="store_true", help="bypass the data cache")
    ap.add_argument("--fixtures", action="store_true", help="use tests/fixtures instead of the live site")
    ap.add_argument("--no-wiki", action="store_true", help="do not look up official banner names on the wiki")
    ap.add_argument("--out", help="write the plans as Markdown to this file")
    ap.add_argument("--csv", help="write the best plan as CSV to this file")
    ap.add_argument("--heatmap", help="write the value heatmap (tickets x cat food) as CSV")
    args = ap.parse_args(argv)

    if args.url:
        seed, last, _event = parse_tracks_url(args.url)
        if args.last:
            last = args.last
    else:
        seed, last = args.seed or 0, args.last
    if not seed:
        ap.error("a seed is required (--url or --seed)")

    owned_text = args.owned
    if owned_text.startswith("@"):
        owned_text = Path(owned_text[1:]).read_text(encoding="utf-8")
    owned = parse_owned_input(owned_text) if owned_text else []

    if args.fixtures:
        loaded = load_fixtures(ROOT / "tests" / "fixtures", FIXTURE_EVENTS, args.date)
    else:
        loaded = load_live(args.date, ROOT / "data_cache", refresh=args.refresh)
    for note in loaded.notes:
        print("note:", note, file=sys.stderr)

    banners = loaded.banners
    for spec in args.guaranteed:
        ev, val = spec.split("=")
        banners[ev].guaranteed_rolls = int(val)
    for ev in args.no_eleven:
        banners[ev].offers_eleven = False
    for ev in args.exclude:
        banners[ev].include = False

    names = dict(loaded.names)
    if loaded.catalog:
        for cid, cat in loaded.catalog.cats.items():
            names.setdefault(cid, cat.name)
    display, wiki_notes = display_names(banners, names, ROOT / "data_cache", use_wiki=not args.no_wiki)
    for note in wiki_notes:
        print("wiki:", note, file=sys.stderr)

    multipliers: dict[int, float] = {}
    if args.wishlist:
        multipliers, errors = wishlist_multipliers(Path(args.wishlist).read_text(encoding="utf-8"),
                                                   loaded.catalog, names, args.multiplier)
        for e in errors:
            print("wishlist:", e, file=sys.stderr)

    inputs = Inputs(seed=seed, last=last, today=args.date, owned=frozenset(owned), tickets=args.tickets,
                    cat_food=args.cf, plats=args.plats, legends=args.legends, tickets_per_draw=args.rate,
                    weights={"rare": args.supa, "supa": args.supa, "uber": args.uber, "legend": args.legend_weight},
                    dupe_values={"supa": args.dupe_super, "uber": args.dupe_uber, "legend": args.dupe_legend},
                    pass_penalties={"uber": args.pass_uber, "uber_fest": args.pass_fest, "legend": args.pass_legend},
                    ticket_cost=args.ticket_cost,
                    multipliers=multipliers, forbid_eleven_over_legend_slot=not args.allow_eleven_over_legend,
                    max_clock_changes=args.max_skips, beam=(None if args.beam == 0 else args.beam),
                    discount_first_draw=args.discount, mode=("exact" if args.exact else "normal"))

    print(f"seed {seed}, last cat {names.get(last, last) if last else 'none'}, plan date {args.date}, "
          f"{len(owned)} owned units, {len([b for b in banners.values() if b.include])} banners", file=sys.stderr)
    for b in banners.values():
        flag = "tomorrow only" if b.provisional else "today"
        print(f"  {b.event_id} [{b.kind}] {display.get(b.event_id, b.name)[:50]} | guaranteed={b.guaranteed_rolls} "
              f"11-draw={b.offers_eleven} include={b.include} ({flag})", file=sys.stderr)

    problem, res = run(inputs, banners)
    s = res.stats
    print(f"search: {s.seconds:.1f}s, {s.labels_created} labels, {len(res.labels)} kept, "
          f"{'proven optimal' if getattr(s, 'proven_optimal', False) else ('heuristic (beam)' if s.truncated else 'exact')}", file=sys.stderr)
    cov_res = run_coverage(inputs, problem)
    rd = readings(problem, res, cov_res=cov_res)

    sections = []
    if rd.best:
        sections.append(to_markdown(problem, rd.best.replay, rd.best.metrics, names, rd.best.title, display))
    if rd.coverage:
        sections.append(to_markdown(problem, rd.coverage.replay, rd.coverage.metrics, names, rd.coverage.title, display))
    else:
        miss = ", ".join(names.get(c, str(c)) for c in rd.missing_targets)
        sections.append("## Full coverage\n\nNot reachable with these resources. Never reachable in this window: "
                        + (miss or "none; more resources would do it") + "\n")
        for m, plan in rd.near_misses:
            sections.append(to_markdown(problem, plan.replay, plan.metrics, names, plan.title, display))
    env = "## Value versus cost\n\n| draw-equivalents | value | tickets | CF | plats |\n|---|---|---|---|---|\n"
    for lab in rd.envelope:
        env += f"| {res.cost(lab):.2f} | {lab.value:.2f} | {lab.t} | {lab.c * 750} | {lab.p} |\n"
    sections.append(env)
    text = "\n".join(sections)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.csv and rd.best:
        Path(args.csv).write_text(to_csv(problem, rd.best.replay, names, display), encoding="utf-8")
    if args.heatmap:
        import csv
        with open(args.heatmap, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["tickets \\ CF"] + [c * 750 for c in range(problem.cf_units + 1)])
            for t, row in enumerate(rd.heatmap):
                w.writerow([t] + [f"{v:.2f}" for v in row])
    return 0


if __name__ == "__main__":
    sys.exit(main())

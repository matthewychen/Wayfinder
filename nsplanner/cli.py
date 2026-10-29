"""Command line: python -m nsplanner --url "<tracker URL>" --cat 100 --lucky 30"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import parse_qs, urlparse

from .banners import ALWAYS_OPEN, BANNERS
from .plan import Settings, default_weights, plan
from .report import improvement, plan_text


def parse_url(url: str) -> tuple[int, str]:
    """(seed, lastCat) from a bc-normal-seed-tracking URL."""
    q = parse_qs(urlparse(url.strip()).query)
    if "seed" not in q:
        raise SystemExit("The URL has no seed=... part. Copy it from the tracker after your last pull.")
    return int(q["seed"][0]), q.get("lastCat", [""])[0]


def settings_from(cat: int, lucky: int, dark: float, catfruit: bool, orb: float, axe: float,
                  extra: list[str] | None = None) -> Settings:
    w = default_weights()
    for name in list(w):
        w[name] = orb if name != "Li'l Axe Cat" else axe
    for item in extra or []:
        name, _, val = item.rpartition("=")
        if not name:
            raise SystemExit(f"--weight needs NAME=VALUE, got {item!r}")
        w[name.strip()] = float(val)
    banners = ALWAYS_OPEN + (("cf",) if catfruit else ())
    return Settings(tickets={"cat": cat, "lucky": lucky}, banners=banners, weights=w, dark_value=dark)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan cat-ticket and lucky-ticket pulls for the most blue orbs.")
    ap.add_argument("--url", help="your bc-normal-seed-tracking URL (gives the seed and the last result)")
    ap.add_argument("--seed", type=int, help="seed, instead of --url")
    ap.add_argument("--last", default=None, help="last result (the URL's lastCat), instead of --url")
    ap.add_argument("--cat", type=int, default=0, help="cat tickets (Cat Capsule and Catseye item capsule)")
    ap.add_argument("--lucky", type=int, default=0, help="lucky tickets")
    ap.add_argument("--dark", type=float, default=20.0,
                    help="blue orbs you would give up rather than lose one Dark Catseye (default 20)")
    ap.add_argument("--catfruit", action="store_true", help="the Catfruit capsule is open too")
    ap.add_argument("--orb", type=float, default=1.0, help="value of one blue orb (default 1)")
    ap.add_argument("--axe", type=float, default=1.0, help="value of one Li'l Axe Cat (default 1, same as an orb)")
    ap.add_argument("--weight", action="append", default=[], metavar="NAME=VALUE",
                    help="value of any other item, e.g. --weight \"Uber Rare Catseye=0.5\"")
    args = ap.parse_args(argv)
    if args.url:
        seed, last = parse_url(args.url)
    elif args.seed is not None:
        seed, last = args.seed, ""
    else:
        ap.error("give --url or --seed")
    if args.last is not None:
        last = args.last
    st = settings_from(args.cat, args.lucky, args.dark, args.catfruit, args.orb, args.axe, args.weight)
    unknown = [n for n in st.weights if not any(n in p.units for b in BANNERS.values() for p in b.pools)]
    if unknown:
        raise SystemExit(f"Unknown item name(s): {', '.join(unknown)}")
    res = plan(seed, last, st)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # the Windows console defaults to cp1252
    print(plan_text(res, st, ",".join(st.banners), improvement(seed, last, res, st)))


if __name__ == "__main__":
    main()

"""A plan as a list of operations: "Pull 10x" or "Pull once", with what each one gives."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from .banners import BANNERS, DARK, POWER_UPS
from .plan import Result, Settings
from .sim import Seeds, label, roll

SITE = "https://ampuri.github.io/bc-normal-seed-tracking/"
ORBS_PER_RARE_TICKET = 5          # his exchange rate: 5 blue orbs = 1 rare ticket


def rare_tickets(orbs: float) -> float:
    return orbs / ORBS_PER_RARE_TICKET


def runs(rolls):
    """Consecutive rolls on the same capsule."""
    out = []
    for r in rolls:
        if out and out[-1][0].code == r.code:
            out[-1].append(r)
        else:
            out.append([r])
    return out


def operations(rolls) -> list[tuple[str, list]]:
    """(kind, rolls) with kind "10x" or "once": each run gives as many 10x pulls as fit, then singles."""
    ops = []
    for run in runs(rolls):
        i = 0
        while len(run) - i >= 10:
            ops.append(("10x", run[i:i + 10]))
            i += 10
        if i < len(run):
            ops.append(("once", run[i:]))
    return ops


def site_url(seed: int, last: str, banners: str = "np,lt,ce") -> str:
    return SITE + "?" + urlencode({"seed": seed, "banners": banners, "lastCat": last})


def _item(r, st: Settings) -> str:
    text = r.name
    if r.name == DARK or st.weights.get(r.name, 0.0):
        text += "★"
    if r.rerolls:
        text += f" (dupe of {r.canonical}, now on track {'A' if r.next % 2 == 0 else 'B'})"
    return text


def straight_rate(code: str = "np") -> float:
    """Blue orbs per pull, on average, pulling one capsule over and over with no planning.

    A re-roll only swaps a repeat for one of the pool's other units, picked evenly, so in the long
    run every unit still comes up equally often and the rates alone give the answer (9 power-ups
    out of 19 on the Cat Capsule: 0.474 per pull)."""
    b = BANNERS[code]
    return sum(pool.rate * sum(1 for u in pool.units if u in POWER_UPS) / len(pool.units)
               for pool in b.pools if pool.units) / 10000


def straight_orbs(seed: int, last: str, pulls: int, code: str = "np") -> int:
    """Blue orbs from pulling `code` straight, `pulls` times, from this seed (re-rolls switch track as usual)."""
    S, p, got = Seeds(seed), 0, 0
    for _ in range(pulls):
        r = roll(S, BANNERS[code], p, last)
        got += r.name in POWER_UPS
        p, last = r.next, r.name
    return got


@dataclass
class Improvement:
    """Blue orbs per cat ticket in the plan, against pulling the Cat Capsule straight with the same tickets."""
    tickets: int         # cat tickets the plan spends (Catseye pulls included: they are the price of Dark Catseyes)
    per_ticket: float    # the plan's blue orbs per cat ticket
    average: float       # pulling straight on the Cat Capsule, on average
    this_seed: float     # pulling straight on the Cat Capsule from this seed
    factor: float        # per_ticket / average

    @property
    def over(self) -> float:
        """Blue orbs over pulling straight, on average, with the same cat tickets."""
        return (self.per_ticket - self.average) * self.tickets

    def line(self) -> str:
        return (f"Improvement ×{self.factor:.2f}: {self.per_ticket:.3f} blue orbs per cat ticket, against "
                f"{self.average:.3f} on average pulling straight on the Cat Capsule "
                f"({self.this_seed:.3f} straight from this seed); {self.over:+.0f} blue orbs, "
                f"{rare_tickets(self.over):+.1f} rare tickets.")


def improvement(seed: int, last: str, res: Result, st: Settings) -> Improvement | None:
    n = res.used.get(st.currency.get("np", "cat"), 0)
    if n <= 0:
        return None
    avg = straight_rate("np")
    per = res.orbs / n
    return Improvement(tickets=n, per_ticket=per, average=avg,
                       this_seed=straight_orbs(seed, last, n) / n, factor=per / avg)


def plan_text(res: Result, st: Settings, banners_param: str = "np,lt,ce", imp: Improvement | None = None) -> str:
    lines = []
    tickets = ", ".join(f"{n} {cur}" for cur, n in sorted(res.used.items())) or "nothing"
    axe = res.weighted.get("Li'l Axe Cat", 0)
    lines.append(f"Spend {tickets} tickets. Blue orbs {res.orbs} (= {res.orbs // ORBS_PER_RARE_TICKET} rare tickets), "
                 f"Li'l Axe Cat {axe}, "
                 f"Dark Catseyes {len(res.darks)}" + (f" ({', '.join(res.darks)})" if res.darks else "") + ".")
    if imp is not None:
        lines.append(imp.line())
    if res.missed:
        lines.append(f"Gives up Dark Catseye at {', '.join(res.missed)}: taking it costs more than "
                     f"{st.dark_value:g} blue orbs, or another Dark Catseye on the other track is taken instead.")
    lines.append("")
    for n, (kind, rs) in enumerate(operations(res.rolls), start=1):
        b = BANNERS[rs[0].code]
        cells = rs[0].cell if len(rs) == 1 else f"{rs[0].cell}-{rs[-1].cell}"
        if kind == "10x":
            what = f"Pull 10x on {b.title}"
        elif len(rs) == 1:
            what = f"Pull once on {b.title}"
        else:
            what = f"Pull once on {b.title}, {len(rs)} times"
        lines.append(f"{n}. {what} [{cells}]: {', '.join(_item(r, st) for r in rs)}.")
    lines.append("")
    lines.append(f"Ends at {label(res.end)}. Next Dark Catseyes: {', '.join(res.darks_ahead) or 'none in sight'}.")
    lines.append(f"Continue on the site: {site_url(res.end_seed, res.end_last, banners_param)}")
    lines.append("★ = counted (blue orb, Li'l Axe Cat, Dark Catseye)")
    return "\n".join(lines)


@dataclass
class Progress:
    """Where you are after the plan's pull number k (0-based): what to save to carry on later."""
    k: int
    cell: str          # the cell of that pull
    next_cell: str     # where the next pull would be
    seed: int          # the tracker's seed= for this point
    last: str          # the tracker's lastCat= for this point
    url: str
    used: dict         # tickets used up to and including that pull
    left: dict         # tickets left from the plan's budget
    orbs: int
    axe: int
    darks: int


def progress_after(seed: int, res: Result, st: Settings, k: int, banners_param: str = "np,lt,ce") -> Progress:
    r = res.rolls[k]
    done = res.rolls[:k + 1]
    used: dict[str, int] = {}
    for x in done:
        cur = st.currency[x.code]
        used[cur] = used.get(cur, 0) + 1
    left = {cur: int(n) - used.get(cur, 0) for cur, n in st.tickets.items()}
    seed_after = Seeds(seed)[r.next]
    return Progress(k=k, cell=r.cell, next_cell=label(r.next), seed=seed_after, last=r.name,
                    url=site_url(seed_after, r.name, banners_param), used=used, left=left,
                    orbs=sum(1 for x in done if x.name in POWER_UPS),
                    axe=sum(1 for x in done if x.name == "Li'l Axe Cat"),
                    darks=sum(1 for x in done if x.name == DARK))

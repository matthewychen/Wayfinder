"""How lucky tickets pay off: the plan for your cat tickets with 0 to 1.2 lucky tickets per cat ticket.

Lucky tickets give no blue orbs themselves; their pulls move you along the track so cat tickets land on
more of them. With few lucky tickets every extra one adds orbs; past a point (about 0.9-1 per cat ticket
on the seeds tried) the plan leaves the rest unused, because nearly every Cat Capsule pull is already a
blue orb. That point is the recommendation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from .plan import Result, Settings, plan
from .report import straight_rate

RATIOS = tuple(i / 10 for i in range(13))     # lucky tickets per cat ticket: 0, 0.1, ..., 1.2


@dataclass
class Point:
    cat: int            # cat tickets available
    lucky: int          # lucky tickets available
    lucky_used: int
    cat_used: int
    orbs: int
    axe: int
    darks: int
    missed: int
    score: float

    @property
    def ratio(self) -> float:
        return self.lucky / self.cat if self.cat else 0.0

    @property
    def factor(self) -> float:
        """The improvement factor: blue orbs per cat ticket against pulling the Cat Capsule straight."""
        return self.orbs / self.cat_used / straight_rate() if self.cat_used else 0.0


def from_result(res: Result, st: Settings) -> Point:
    cur = st.currency.get("np", "cat")
    return Point(cat=int(st.tickets.get(cur, 0)), lucky=int(st.tickets.get("lucky", 0)),
                 lucky_used=res.used.get("lucky", 0), cat_used=res.used.get(cur, 0), orbs=res.orbs,
                 axe=res.weighted.get("Li'l Axe Cat", 0), darks=len(res.darks), missed=len(res.missed), score=res.score)


def point(seed: int, last: str, st: Settings, lucky: int) -> Point:
    s2 = replace(st, tickets={**st.tickets, "lucky": int(lucky)})
    return from_result(plan(seed, last, s2), s2)


def lucky_counts(cat: int) -> list[int]:
    return sorted({round(r * cat) for r in RATIOS})


def _settings_to_json(st: Settings) -> dict:
    return {"tickets": st.tickets, "banners": list(st.banners), "currency": st.currency, "weights": st.weights,
            "dark_value": st.dark_value}


def _settings_from_json(d: dict) -> Settings:
    return Settings(tickets=d["tickets"], banners=tuple(d["banners"]), currency=d["currency"], weights=d["weights"],
                    dark_value=d["dark_value"])


def sweep(seed: int, last: str, st: Settings, progress=None, workers: int | None = None) -> list[Point]:
    """One plan per lucky-ticket count in `lucky_counts`, several at once in separate processes when the
    machine has the cores (one at a time if that fails, e.g. where processes cannot be started)."""
    cat = int(st.tickets.get(st.currency.get("np", "cat"), 0))
    counts = list(reversed(lucky_counts(cat)))           # biggest first: the slow plans start early
    if workers is None:
        workers = min(4, max(1, (os.cpu_count() or 2) - 1))
    out: list[Point] = []

    def add(p: Point) -> None:
        out.append(p)
        if progress is not None:
            progress(len(out), len(counts))

    if workers > 1 and len(counts) > 2:
        try:
            _in_processes(seed, last, st, counts, workers, add)
            return sorted(out, key=lambda p: p.lucky)
        except Exception:  # noqa: BLE001 - no helper processes here: do it in this process
            out.clear()
    for n in counts:
        add(point(seed, last, st, n))
    return sorted(out, key=lambda p: p.lucky)


def _in_processes(seed: int, last: str, st: Settings, counts: list[int], workers: int, add) -> None:
    """Plan `counts` in `workers` helper processes, each started as `python -m nsplanner.sweep` (not with
    multiprocessing: under Streamlit that would run app.py again in every helper)."""
    import json
    import queue
    import subprocess
    import sys
    import threading
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)      # no console window per helper on Windows
    lines: queue.Queue = queue.Queue()
    procs = []

    def read(proc) -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    for share in (counts[i::workers] for i in range(workers)):
        if not share:
            continue
        proc = subprocess.Popen([sys.executable, "-m", "nsplanner.sweep"], cwd=root, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                creationflags=flags)
        procs.append(proc)
        proc.stdin.write(json.dumps({"seed": seed, "last": last, "settings": _settings_to_json(st), "lucky": share}))
        proc.stdin.close()
        threading.Thread(target=read, args=(proc,), daemon=True).start()
    try:
        running, got = len(procs), 0
        while running:
            line = lines.get()
            if line is None:
                running -= 1
            elif line.strip():
                add(Point(**json.loads(line)))
                got += 1
        if got != len(counts):
            raise RuntimeError(f"helpers returned {got} of {len(counts)} plans")
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def _helper() -> None:
    """`python -m nsplanner.sweep`: read {seed, last, settings, lucky: [...]} on stdin, print one Point per line."""
    import json
    import sys
    from dataclasses import asdict

    job = json.loads(sys.stdin.read())
    st = _settings_from_json(job["settings"])
    for n in job["lucky"]:
        print(json.dumps(asdict(point(job["seed"], job["last"], st, n))), flush=True)


@dataclass
class Advice:
    now: Point
    best: Point            # the fewest lucky tickets that reach the sweep's best plan
    want: int              # lucky tickets that plan actually uses: more than this go unused
    still_rising: bool     # the best plan needed the largest count in the sweep, so more may still help

    @property
    def per_cat(self) -> float:
        return self.want / self.best.cat if self.best.cat else 0.0

    @property
    def baseline(self) -> float:
        """Blue orbs from the same cat tickets pulled straight on the Cat Capsule, on average."""
        return straight_rate() * self.now.cat_used

    @property
    def over_baseline(self) -> float:
        return self.now.orbs - self.baseline

    @property
    def extra_orbs(self) -> int:
        return max(0, self.best.orbs - self.now.orbs)

    @property
    def extra_lucky(self) -> int:
        return max(0, self.want - self.now.lucky)


def advise(points: list[Point], now: Point) -> Advice:
    top = max(p.score for p in points)
    best = min((p for p in points if p.score >= top - 1e-9), key=lambda p: p.lucky)
    if now.score > best.score + 1e-9 or (abs(now.score - best.score) <= 1e-9 and now.lucky < best.lucky):
        best = now
    most = max(p.lucky for p in points)
    return Advice(now=now, best=best, want=best.lucky_used, still_rising=best.lucky >= most > 0)


if __name__ == "__main__":
    _helper()

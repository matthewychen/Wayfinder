"""Fetch and parse bc.godfat.org pages: banners, the event list, the unit catalog.

All parsing is anchored on specific blocks of the site's HTML and fails loudly
when a block is missing. Saved copies of the pages live in tests/fixtures.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .model import Banner, Cat, Catalog
from .prng import site_label
from .sim import Tables, site_table
from .sitetable import parse_table

BASE_URL = "https://bc.godfat.org"
USER_AGENT = "bc-planner (personal Battle Cats pull planner; fan tool over bc.godfat.org data)"

DETAILS_RARITY = {"Rare": "rare", "Super": "supa", "Uber": "uber", "Legendary": "legend"}
HEADING_RARITY = {
    "Legend Rare Cat": "legend", "Uber Rare Cat": "uber", "Super Rare Cat": "supa",
    "Rare Cat": "rare", "Special Cat": "special", "Normal Cat": "normal",
}

_OPTION = re.compile(r'<option[^>]*value="(\d{4}-\d{2}-\d{2}_\d+)"[^>]*>\s*([^<]*?)\s*</option>', re.S)
_OPTION_TEXT = re.compile(r"(\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2}): (.*)")
_LI = re.compile(r"<li>\s*(Rare|Super|Uber|Legendary):(.*?)</li>", re.S)
_RATE = re.compile(r"\s*([\d.]+)%\s*\((\d+) cats\)")
_SLOT = re.compile(r'(\d+) <a href="//bc\.godfat\.org/cats/(\d+)\?[^>]*>([^<]*)<')
_CAT_ENTRY = re.compile(r'id="cat-(\d+)" value="\d+"\s*>\s*<a href="//bc\.godfat\.org/cats/\d+" title="[^"]*">([^<]*)</a>', re.S)
_HEADING = re.compile(r'<h2 id="[^"]*">([A-Za-z ]+ Cat) \((\d+)\)</h2>')
_PLACEHOLDER = re.compile(r"\d+[_-]\d+")                     # the site's name for a unit with no English name yet
_NON_LATIN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")       # kana / kanji: a Japanese-only unit
_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?)\s*</span>")


@dataclass(frozen=True)
class EventInfo:
    event_id: str
    gacha_id: int
    start: date
    end: date          # exclusive
    name: str


class ParseError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------
# Parsers (pure functions of page text)
# ---------------------------------------------------------------------------------------

def parse_events(page: str) -> list[EventInfo]:
    """Every event in the page's dropdown, deduplicated, in page order."""
    seen = set()
    out = []
    for value, text in _OPTION.findall(page):
        if value in seen:
            continue
        seen.add(value)
        text = html_mod.unescape(text).strip()
        m = _OPTION_TEXT.match(text)
        if not m:
            continue
        start = date.fromisoformat(m.group(1))
        end = date.fromisoformat(m.group(2))
        out.append(EventInfo(event_id=value, gacha_id=int(value.split("_")[1]),
                             start=start, end=end, name=m.group(3).strip()))
    if not out:
        raise ParseError("event dropdown not found on page")
    return out


def parse_details(page: str, event_id: str) -> tuple[Banner, dict[int, str]]:
    """The Gacha information block of a Details page -> Banner plus id->name for its cats."""
    start = page.find("Gacha information")
    if start < 0:
        raise ParseError("Gacha information block not found (is details=true set, and does the event exist?)")
    block = page[start:start + 80000]
    rates = {r: 0 for r in DETAILS_RARITY.values()}
    pools: dict[str, list[int]] = {r: [] for r in DETAILS_RARITY.values()}
    names: dict[int, str] = {}
    found = 0
    for label, body in _LI.findall(block):
        rarity = DETAILS_RARITY[label]
        m = _RATE.match(body)
        if not m:
            raise ParseError(f"rate line for {label} not understood")
        rates[rarity] = int(round(float(m.group(1)) * 100))
        count = int(m.group(2))
        entries = _SLOT.findall(body)
        if len(entries) != count:
            raise ParseError(f"{label}: listed {len(entries)} cats but header says {count}")
        for slot, cat_id, name in entries:
            pools[rarity].append(int(cat_id))
            names[int(cat_id)] = html_mod.unescape(name).strip()
        found += 1
    if found != 4:
        raise ParseError(f"expected 4 rarity lines, found {found}")
    events = {e.event_id: e for e in parse_events(page)}
    info = events.get(event_id)
    if info is None:
        raise ParseError(f"event {event_id} is not in the page's dropdown")
    banner = Banner(
        event_id=event_id, gacha_id=info.gacha_id, name=info.name,
        start=info.start, end=info.end,
        rates=(rates["rare"], rates["supa"], rates["uber"], rates["legend"]),
        pools={k: v for k, v in pools.items() if v},
    )
    return banner, names


def parse_cats(page: str) -> Catalog:
    """The /cats listing -> Catalog with rarity taken from the section headings."""
    catalog = Catalog()
    headings = list(_HEADING.finditer(page))
    if not headings:
        raise ParseError("no rarity headings found on the cats page")
    for idx, h in enumerate(headings):
        rarity = HEADING_RARITY.get(h.group(1))
        if rarity is None:
            continue
        section_end = headings[idx + 1].start() if idx + 1 < len(headings) else len(page)
        section = page[h.end():section_end]
        for cat_id, name in _CAT_ENTRY.findall(section):
            name = html_mod.unescape(name).strip()
            if _PLACEHOLDER.fullmatch(name) or _NON_LATIN.search(name):
                continue                      # "733_1", "819-1", Japanese-only names: not in the English game
            catalog.cats[int(cat_id)] = Cat(id=int(cat_id), name=name, rarity=rarity)
    if len(catalog.cats) < 500:
        raise ParseError(f"only {len(catalog.cats)} cats parsed; page structure may have changed")
    return catalog


def page_seed_and_last(page: str) -> tuple[int, int]:
    """The seed and last-cat parameters the page was rendered with (0 when absent)."""
    m = re.search(r"window\.location = '//bc\.godfat\.org/\?([^']*)'", page)
    seed = last = 0
    if m:
        for part in m.group(1).split("&"):
            if part.startswith("seed="):
                seed = int(part[5:] or 0)
            elif part.startswith("last="):
                last = int(part[5:] or 0)
    return seed, last


def infer_guaranteed_rolls(page: str, banner: Banner) -> int:
    """0, 11 or 15: which guaranteed-draw length reproduces the page's guaranteed cells.

    The page shows, for every position, the guaranteed uber and the landing position
    of an 11-draw (or 15-roll step-up) started there. We simulate both hypotheses
    from the page's own seed and pick the one that matches; no cells means 0.
    """
    positions = parse_table(page)
    shown = [p for p in positions.values() if p.guaranteed_id is not None]
    if not shown:
        return 0
    seed, last = page_seed_and_last(page)
    seed = seed or 1
    rows = max(int(lbl[:-1]) for lbl in positions)
    tables = Tables(seed, 2 * rows + 64)
    for hypothesis in (11, 15):
        mine = {}
        for a, b in site_table(tables, banner, last, rows, hypothesis):
            mine[a.label] = a
            mine[b.label] = b
        ok = all(
            mine[p.label].guaranteed_id == p.guaranteed_id and mine[p.label].guaranteed_next == p.guaranteed_next
            for p in shown[:40]
        )
        if ok:
            return hypothesis
    raise ParseError("guaranteed cells on the page match neither an 11-draw nor a 15-roll step-up")


def self_test(page: str, banner: Banner, guaranteed_rolls: int, rows: int | None = None) -> list[str]:
    """Compare the page's own table with our simulation. Returns a list of mismatches.

    The whole table is simulated (guaranteed cells land up to 15 rows further down);
    `rows` only limits how many rows are compared.
    """
    positions = parse_table(page)
    seed, last = page_seed_and_last(page)
    page_rows = max(int(lbl[:-1]) for lbl in positions)
    rows = page_rows if rows is None else min(rows, page_rows)
    tables = Tables(seed or 1, 2 * page_rows + 64)
    problems = []
    for a, b in site_table(tables, banner, last, page_rows, guaranteed_rolls)[:rows]:
        for mine in (a, b):
            theirs = positions.get(mine.label)
            if theirs is None:
                problems.append(f"{mine.label}: missing on page")
                continue
            for f in ("rarity_seed", "slot_seed", "score", "slot", "cat_id", "rerolled_id", "rerolled_next",
                      "guaranteed_id", "guaranteed_next", "rerolled_guaranteed_id", "rerolled_guaranteed_next"):
                tv, mv = getattr(theirs, f), getattr(mine, f)
                if tv is not None and tv != mv:
                    problems.append(f"{mine.label}.{f}: site={tv} mine={mv}")
    return problems


# ---------------------------------------------------------------------------------------
# Fetching with a file cache
# ---------------------------------------------------------------------------------------

FETCH_TIMEOUT = (15, 180)     # connect, read (seconds): a banner page can take over a minute when the site is busy
DETAILS_MAX_AGE_H = 24 * 7    # a started event's pools and rates do not change; its page is slow for the site to build


def _get(url: str, attempts: int = 2) -> str:
    """GET with a long read timeout, retried once on a timeout, a dropped connection or a 5xx answer."""
    import requests  # imported lazily so the parsers stay dependency-free

    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} from the site", response=resp)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500:
                break                     # a 4xx will not get better on a retry
            if i + 1 < attempts:
                time.sleep(3)
    assert last_exc is not None
    raise last_exc


def fetch_cached(url: str, cache_file: Path, max_age_hours: float = 24, refresh: bool = False,
                 notes: list[str] | None = None) -> str:
    """The page from the cache when it is fresh enough, else from the site. When the site fails and an
    older copy exists, that copy is used and a line saying so is added to `notes`."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists() and not refresh:
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_h <= max_age_hours:
            return cache_file.read_text(encoding="utf-8")
    try:
        text = _get(url)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to a saved copy when there is one
        if not cache_file.exists():
            raise
        age_h = (time.time() - cache_file.stat().st_mtime) / 3600
        if notes is not None:
            notes.append(f"{cache_file.name}: bc.godfat.org did not answer ({type(exc).__name__}); "
                         f"used the copy saved {age_h / 24:.1f} days ago")
        return cache_file.read_text(encoding="utf-8")
    cache_file.write_text(text, encoding="utf-8")
    time.sleep(0.5)  # be polite between requests
    return text


def details_url(event_id: str, seed: int = 1, last: int = 0, lang: str = "en") -> str:
    q = f"seed={seed}&event={event_id}&details=true&lang={lang}"
    if last:
        q += f"&last={last}"
    return f"{BASE_URL}/?{q}"


class SiteData:
    """Cached access to everything the planner needs from the site for one plan date."""

    def __init__(self, cache_dir: Path, plan_date: date, refresh: bool = False, lang: str = "en"):
        self.cache_dir = Path(cache_dir)
        self.plan_date = plan_date
        self.refresh = refresh
        self.lang = lang
        self.names: dict[int, str] = {}
        self.notes: list[str] = []        # saved copies used because the site did not answer

    # -- catalog ---------------------------------------------------------------------
    def catalog(self) -> Catalog:
        page = fetch_cached(f"{BASE_URL}/cats?lang={self.lang}", self.cache_dir / "cats.html", refresh=self.refresh,
                            notes=self.notes)
        return parse_cats(page)

    # -- events ----------------------------------------------------------------------
    def events(self) -> list[EventInfo]:
        page = fetch_cached(f"{BASE_URL}/?lang={self.lang}", self.cache_dir / "index.html", refresh=self.refresh,
                            notes=self.notes)
        return parse_events(page)

    def live_events(self, days: int = 2) -> list[EventInfo]:
        """Events live on the plan date or any of the next `days-1` days."""
        window = [self.plan_date + timedelta(days=d) for d in range(days)]
        return [e for e in self.events() if any(e.start <= d < e.end for d in window)]

    # -- banners ---------------------------------------------------------------------
    def banner(self, event_id: str, started: bool = False) -> tuple[Banner, int, list[str]]:
        """(banner, guaranteed_rolls as shown by the site, self-test problems). A started event's page is
        kept for a week; an upcoming one is refreshed daily in case the site corrects it."""
        page = fetch_cached(details_url(event_id, lang=self.lang),
                            self.cache_dir / f"details_{event_id}.html", refresh=self.refresh,
                            max_age_hours=DETAILS_MAX_AGE_H if started else 24, notes=self.notes)
        banner, names = parse_details(page, event_id)
        self.names.update(names)
        rolls = infer_guaranteed_rolls(page, banner)
        problems = self_test(page, banner, rolls)
        banner.guaranteed_rolls = rolls
        banner.provisional = banner.start > self.plan_date
        return banner, rolls, problems

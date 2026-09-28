"""True banner names from the Battle Cats Wiki (battlecats.miraheze.org).

Every gacha unit's wiki page says where it comes from in its first sentence: "can be unlocked
by playing the [[Rare Capsule]] during the [[Gals of Summer Blue Ocean (Gacha Event)|...]]" for a
set, or "... during the [[Street Fighter Collaboration Event]]" for a collab. A page with no Rare
Capsule link is a stage reward or another non-gacha unit. The infobox carries the game's unit ID
(the site's id minus one). A banner's official name is the event title shared by most of its ubers.
Results are cached on disk, one small file per unit, so the wiki is asked about each unit once.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

from .model import Banner

API = "https://battlecats.miraheze.org/w/api.php"
USER_AGENT = "bc-planner (personal Battle Cats pull planner; contact via GitLab issue if needed)"

_ID = re.compile(r"\|\s*ID\s*=\s*(\d+)")
# "Rare Capsule" / "Rare Cat Capsule(s)", linked or plain, in the page's opening paragraph
_CAPSULE = re.compile(r"Rare (?:Cat )?Capsules?", re.I)
_GACHA_CATEGORY = re.compile(r"\[\[Category:\s*Gacha Cats\s*\]\]", re.I)
# [[Name (Gacha Event)|...]] or [[Name Collaboration Event...]]; group 3 keeps any /subpage or #anchor
_EVENT_LINK = re.compile(r"\[\[([^\]|#]+?)( \(Gacha Event\)| Collaboration Event)([^\]|]*)(?:\|[^\]]*)?\]\]")
COLLAB = " collab"                          # suffix given to collaboration events, e.g. "Street Fighter collab"
NOT_GACHA = "Not from the Rare Capsule"     # pseudo-title for units the wiki does not describe as capsule units
CACHE_VERSION = 3


_OTHER_VERSIONS = ("POP!", "Unite!", "Switch", "Nintendo", "3DS")   # sentences about the 3DS / Switch games
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\'])")


def page_intro(text: str) -> str:
    """The opening paragraph of a wiki page: everything before its first section heading."""
    return text.split("\n==", 1)[0]


def classify(intro: str, has_gacha_category: bool) -> tuple[str | None, str]:
    """(event title, status) from a unit page's opening paragraph and its Gacha Cats category flag.

    A gacha unit's page carries [[Category:Gacha Cats]] or says in its opening paragraph that the
    unit comes from the Rare (Cat) Capsule; anything else is a stage reward or another non-gacha
    unit. Sentences about The Battle Cats POP! (3DS) or Unite! (Switch) are ignored: the Crazed Cats
    come from the capsule there but not in the phone game. The event is the first event link in the
    opening paragraph, preferring the one right after the capsule mention ("... the Rare Capsule
    during the [[X (Gacha Event)|X]]"); collaboration events get the " collab" suffix. Later
    sections are not searched: a regular-pool super's page may mention any banner there."""
    intro = " ".join(s for s in _SENTENCE.split(re.sub(r"\s+", " ", intro))
                     if not any(v in s for v in _OTHER_VERSIONS))
    cap = _CAPSULE.search(intro)
    if cap is None and not has_gacha_category:
        return None, "not from the Rare Capsule"
    candidates = [m for m in [_EVENT_LINK.search(intro, cap.end(), cap.end() + 300) if cap else None] if m]
    candidates += list(_EVENT_LINK.finditer(intro))
    for m in candidates:
        if "Switch" in m.group(3):
            continue
        name = m.group(1).strip()
        return (name + COLLAB if "Collaboration" in m.group(2) else name), "ok"
    return None, "no event on page"


def find_event(text: str) -> tuple[str | None, str]:
    """`classify` applied to a whole page's wikitext."""
    return classify(page_intro(text), bool(_GACHA_CATEGORY.search(text)))

# Short display aliases for well-known sets; the full official title is always kept too.
SET_ALIASES = [
    ("DRAGON EMPERORS", "Dragon Emperors"), ("The Almighties", "The Almighties"), ("ULTRA SOULS", "Ultra Souls"),
    ("Galaxy Gals", "Galaxy Gals"), ("Gals of Summer", "Summer Gals"), ("Xmas Gals", "Xmas Gals"),
    ("Dynamites", "Dynamites"), ("Sengoku", "Sengoku Wargods"), ("Iron Legion", "Iron Legion"),
    ("Elemental Pixies", "Elemental Pixies"), ("Dark Heroes", "Dark Heroes"), ("Nekoluga", "Nekolugas"),
    ("Elder Epoch", "Elder Epoch"), ("Vajiras", "Vajiras"), ("Girls & Monsters", "Girls & Monsters"),
    ("Girls and Monsters", "Girls & Monsters"), ("Frontline Assault", "Frontline Assault"),
    ("Halloween", "Halloween Gals"), ("Valentine", "Valentine Gals"), ("Easter", "Easter Carnival"),
    ("Uberfest", "Uberfest"), ("Epicfest", "Epicfest"), ("Superfest", "Superfest"),
    ("Royal Fest", "Royalfest"), ("RoyalFest", "Royalfest"), ("Dynasty Fest", "Dynasty Fest"),
    ("Best of the Best", "Best of the Best"),
]
# Every "... Busters" event (Red, Air, Dark, Metal, Colossus, Wave, ...) is its own small set: keep the full
# name, in title case, instead of lumping them together or treating them as single-banner exclusives.
_BUSTERS = "busters"


class WikiClient:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir) / "wiki"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- low level -------------------------------------------------------------------
    def _get(self, **params) -> dict:
        import requests  # lazy

        params["format"] = "json"
        r = requests.get(API, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        time.sleep(0.2)
        return r.json()

    def _wikitext(self, title: str) -> str | None:
        d = self._get(action="parse", page=title, prop="wikitext")
        if "error" in d:
            return None
        return d["parse"]["wikitext"]["*"]

    def _search_unit_page(self, name: str) -> str | None:
        d = self._get(action="query", list="search", srsearch=f'"{name}"', srlimit=8)
        for hit in d.get("query", {}).get("search", []):
            title = hit["title"]
            if title.endswith("Rare Cat)") or title.endswith("Cat)"):
                return title
        return None

    # -- per unit ------------------------------------------------------------------------
    def unit_info(self, cat_id: int, name: str, rarity: str) -> dict:
        """{'title', 'event', 'wiki_id', 'status'} for a unit; cached on disk."""
        f = self.dir / f"unit_{cat_id}.json"
        if f.exists():
            try:
                cached = json.loads(f.read_text(encoding="utf-8"))
                if cached.get("v") == CACHE_VERSION:
                    return cached
            except ValueError:
                pass
        suffix = {"legend": "Legend Rare Cat", "uber": "Uber Rare Cat", "supa": "Super Rare Cat", "rare": "Rare Cat"}.get(rarity, "Uber Rare Cat")
        name = name.replace("\uff06", "&").strip()          # the site writes a full-width ampersand
        info = {"v": CACHE_VERSION, "title": f"{name} ({suffix})", "event": None, "wiki_id": None, "status": "not found"}
        try:
            text = self._wikitext(info["title"])
            if text is None:
                alt = self._search_unit_page(name)
                if alt:
                    info["title"] = alt
                    text = self._wikitext(alt)
            if text is not None:
                info["event"], info["status"] = find_event(text)
                info["intro"] = page_intro(text)[:3000]                       # kept so a parser change needs no refetch
                info["gacha_category"] = bool(_GACHA_CATEGORY.search(text))
                m = _ID.search(text)
                info["wiki_id"] = int(m.group(1)) if m else None
                if info["wiki_id"] is not None and info["wiki_id"] + 1 != cat_id:
                    info["status"] = f"id mismatch (wiki {info['wiki_id']} vs site {cat_id})"
        except Exception as exc:  # noqa: BLE001 - names are cosmetic; never break planning
            info["status"] = f"error: {exc}"
            return info                       # do not cache transient failures
        f.write_text(json.dumps(info), encoding="utf-8")
        return info

    # -- per banner ----------------------------------------------------------------------
    def banner_title(self, banner: Banner, names: dict[int, str], progress=None) -> tuple[str | None, list[str]]:
        """Official event title shared by most of the banner's ubers (and legends), plus notes."""
        ids = list(banner.pool("uber")) + list(banner.pool("legend"))
        votes: Counter = Counter()
        notes = []
        for i, cid in enumerate(ids):
            info = self.unit_info(cid, names.get(cid, str(cid)), "legend" if cid in banner.pool("legend") else "uber")
            if info["event"] and info["status"] == "ok":
                votes[info["event"]] += 1
            elif info["status"] != "ok":
                notes.append(f"{names.get(cid, cid)}: {info['status']}")
            if progress is not None:
                progress(i + 1, len(ids))
        if not votes:
            return None, notes
        title, count = votes.most_common(1)[0]
        if count < max(1, len(ids) // 3):
            notes.append(f"weak agreement on the banner title ({count} of {len(ids)} ubers)")
        total = sum(votes.values())
        if count / total < 0.7:
            # a mixed banner (a seasonal re-run with Halloween and Xmas gals together): name every set
            # that holds at least a third of the ubers, most first
            parts = [t for t, n in votes.most_common() if n / total >= 0.3]
            if len(parts) > 1:
                title = " + ".join(short_alias(t) or t for t in parts)
                notes.append(f"mixed banner: {title}")
        return title, notes


def short_alias(title: str | None) -> str | None:
    if not title:
        return None
    low = title.lower()
    for needle, alias in SET_ALIASES:
        if needle.lower() in low:
            return alias
    if _BUSTERS in low:
        return " ".join(w.capitalize() for w in title.split())
    return None


def display_name(official: str | None, blurb_short: str) -> str:
    """What the app shows: the alias, else the official title, else the cleaned blurb."""
    if official:
        if " + " in official:               # a mixed banner, already spelled out set by set
            return official
        alias = short_alias(official)
        return alias if alias else official
    return blurb_short


# ---------------------------------------------------------------------------------------
# Home sets: which gacha set a unit belongs to, whether or not that banner is running
# ---------------------------------------------------------------------------------------
REGULAR_POOL = "Regular pool"
EXCLUSIVES = "Single-banner exclusives"
UNKNOWN = "Unknown"
NOT_GACHA_GROUP = "Not a gacha unit"


def home_groups(titles: dict[int, str | None], rarities: dict[int, str], min_shared: int = 3) -> dict[int, str]:
    """Map unit id -> home group name from the gacha-event titles found on the wiki.

    Units whose page names no event are regular-pool units. Event titles shared by fewer
    than `min_shared` units are lumped together as single-banner exclusives (Trixi, Empress, ...).
    Known sets get their short alias; collaboration events and every "... Busters" set keep their
    own name however few units they have; units never sold in the Rare Capsule form their own group.
    """
    from collections import Counter

    counts = Counter(t for t in titles.values() if t)
    out: dict[int, str] = {}
    for cid, title in titles.items():
        if not title:
            out[cid] = REGULAR_POOL if rarities.get(cid) in ("rare", "supa") else UNKNOWN
        elif title == NOT_GACHA:
            out[cid] = NOT_GACHA_GROUP
        elif counts[title] < min_shared and not short_alias(title) and not title.endswith(COLLAB):
            out[cid] = EXCLUSIVES
        else:
            out[cid] = short_alias(title) or title
    return out


def lookup_titles(client: "WikiClient", units: list[tuple[int, str, str]], progress=None) -> dict[int, str | None]:
    """Gacha-event title per unit (id, name, rarity); cached per unit by the client."""
    out: dict[int, str | None] = {}
    for i, (cid, name, rarity) in enumerate(units):
        info = client.unit_info(cid, name, rarity)
        status = info.get("status", "")
        if status.startswith("not from"):
            out[cid] = NOT_GACHA
        else:
            out[cid] = info.get("event") if status.startswith(("ok", "no event")) else None
        if progress is not None:
            progress(i + 1, len(units))
    return out

"""Unit and item icons.

Unit icons come from bc.godfat.org, which serves the game's own unit portraits at
/extract/en/uni{id-1:03d}_{form}00.png keyed by the same unit ids this planner uses
(forms: f = first, c = evolved, s = true, u = ultra). They are downloaded once,
cached under data_cache/icons, and embedded as data URLs so Streamlit tables and
HTML grids can show them without further requests.

Item icons (rare ticket, cat food, platinum ticket, legend ticket) are small PNGs
bundled in bcplanner/assets; emoji are the fallback if a file is missing.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from .scrape import BASE_URL, USER_AGENT

ASSETS = Path(__file__).resolve().parent / "assets"
FORMS = ("f", "c", "s", "u")
EMOJI = {"ticket": "🎟️", "cat_food": "🥫", "plat": "💿", "legend": "🏵️"}


def unit_icon_url(cat_id: int, form: str = "f", lang: str = "en") -> str:
    return f"{BASE_URL}/extract/{lang}/uni{cat_id - 1:03d}_{form}00.png"


class IconCache:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir) / "icons"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._data_urls: dict[int, str] = {}
        self._missing: set[int] = set()

    def path(self, cat_id: int) -> Path:
        return self.dir / f"{cat_id}.png"

    def fetch(self, cat_id: int, session=None) -> bytes | None:
        """Bytes of the unit's first-form portrait, from cache or the site. None if unavailable."""
        p = self.path(cat_id)
        if p.exists():
            return p.read_bytes()
        if cat_id in self._missing or cat_id <= 0:
            return None
        import requests  # lazy

        s = session or requests
        try:
            for form in FORMS[:2]:      # first form, then evolved form as a fallback
                r = s.get(unit_icon_url(cat_id, form), headers={"User-Agent": USER_AGENT}, timeout=20)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                    p.write_bytes(r.content)
                    time.sleep(0.05)
                    return r.content
        except Exception:  # noqa: BLE001 - icons are cosmetic; never fail the planner
            pass
        self._missing.add(cat_id)
        return None

    def prefetch(self, cat_ids, progress=None) -> int:
        """Download every missing icon in the list; returns how many were fetched."""
        import requests

        ids = [c for c in cat_ids if c > 0 and not self.path(c).exists()]
        fetched = 0
        with requests.Session() as s:
            for i, cid in enumerate(ids):
                if self.fetch(cid, s) is not None:
                    fetched += 1
                if progress is not None:
                    progress(i + 1, len(ids))
        return fetched

    def data_url(self, cat_id: int) -> str | None:
        if cat_id in self._data_urls:
            return self._data_urls[cat_id]
        data = self.fetch(cat_id)
        if data is None:
            return None
        url = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        self._data_urls[cat_id] = url
        return url


def item_icon_html(kind: str, size: int = 18) -> str:
    """Inline <img> for a resource icon, or the emoji fallback."""
    p = ASSETS / f"{kind}.png"
    if p.exists():
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{b64}" alt="{kind}" style="height:{size}px;vertical-align:-3px">'
    return EMOJI.get(kind, "")


def item_icon_text(kind: str) -> str:
    """Emoji for plain-text contexts (Streamlit widget labels, Markdown)."""
    return EMOJI.get(kind, "")

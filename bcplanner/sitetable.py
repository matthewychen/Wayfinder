"""Parse the tracks table of a bc.godfat.org Details page into positions.

Used by the golden tests and by the scrape self-test. Only the Details view
(`details=true`) is supported because it carries seeds and scores.

Row layout, from lib/battle-cats-rolls/view/table.erb:
  tr1: [No. nA] [seed a.rarity] [score,slot a] [g-score a] ([prev_b result] [prev_b guaranteed] [seed prev_b.slot] | [Backtrack])
  tr?: [prev_b rerolled result] [its guaranteed]            (only when prev_b has a reroll)
  tr2: [seed a.slot] [a result] [a guaranteed] [score,slot b] [g-score b] [seed b.rarity] [No. nB]
  tr?: [a rerolled result] [its guaranteed]                 (only when a has a reroll)
  footer: [colspan] [last_b result] [last_b guaranteed] [seed last_b.slot]
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_TR = re.compile(r"<tr>(.*?)</tr>", re.S)
_TD = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)
_CAT = re.compile(r"/cats/(\d+)\?")
_NEXT = re.compile(r"(?:<-|->)\s*(\d+[AB]R?G?)")   # the site writes arrow first, then the label
_NO = re.compile(r"^\s*(\d+)([AB])\s*$")
_SCORE = re.compile(r"^\s*(\d+),\s*(-?\d+)\s*$")


@dataclass
class Cell:
    raw: str
    text: str
    cat_id: int | None
    next_label: str | None


@dataclass
class ParsedPosition:
    label: str
    rarity_seed: int | None = None
    slot_seed: int | None = None
    score: int | None = None
    slot: int | None = None
    cat_id: int | None = None
    guaranteed_id: int | None = None
    guaranteed_next: str | None = None
    rerolled_id: int | None = None
    rerolled_next: str | None = None
    rerolled_guaranteed_id: int | None = None
    rerolled_guaranteed_next: str | None = None


def _cell(raw: str) -> Cell:
    text = html.unescape(re.sub(r"<[^>]*>", "", raw)).strip()
    m = _CAT.search(raw)
    cat_id = int(m.group(1)) if m else None
    n = _NEXT.search(html.unescape(raw))
    nxt = n.group(1) if n else None
    return Cell(raw=raw, text=text, cat_id=cat_id, next_label=nxt)


def parse_table(page: str) -> dict[str, ParsedPosition]:
    """Return positions keyed by label ('1A', '1B', ...)."""
    start = page.find('<div class="table">')
    end = page.find("</table>", start)
    if start < 0 or end < 0:
        raise ValueError("tracks table not found on page")
    body = page[start:end]
    positions: dict[str, ParsedPosition] = {}
    last_result_owner: ParsedPosition | None = None
    for tr in _TR.findall(body):
        cells = [_cell(c) for c in _TD.findall(tr)]
        if not cells or "<th" in tr:
            continue
        first = _NO.match(cells[0].text)
        last = _NO.match(cells[-1].text) if len(cells) >= 2 else None
        if first and first.group(2) == "A":
            label = f"{first.group(1)}A"
            pos = positions.setdefault(label, ParsedPosition(label))
            pos.rarity_seed = int(cells[1].text)
            sc = _SCORE.match(cells[2].text)
            if sc:
                pos.score, pos.slot = int(sc.group(1)), int(sc.group(2))
            if len(cells) >= 7:   # prev_b result / guaranteed / slot seed
                prev_label = f"{int(first.group(1)) - 1}B"
                prev = positions.setdefault(prev_label, ParsedPosition(prev_label))
                prev.cat_id = cells[4].cat_id
                prev.guaranteed_id, prev.guaranteed_next = cells[5].cat_id, cells[5].next_label
                prev.slot_seed = int(cells[6].text)
                last_result_owner = prev
            else:
                last_result_owner = None
        elif last and last.group(2) == "B":
            label_a = f"{last.group(1)}A"
            label_b = f"{last.group(1)}B"
            a = positions.setdefault(label_a, ParsedPosition(label_a))
            b = positions.setdefault(label_b, ParsedPosition(label_b))
            a.slot_seed = int(cells[0].text)
            a.cat_id = cells[1].cat_id
            a.guaranteed_id, a.guaranteed_next = cells[2].cat_id, cells[2].next_label
            sc = _SCORE.match(cells[3].text)
            if sc:
                b.score, b.slot = int(sc.group(1)), int(sc.group(2))
            b.rarity_seed = int(cells[5].text)
            last_result_owner = a
        elif len(cells) == 2 and last_result_owner is not None:
            owner = last_result_owner
            owner.rerolled_id, owner.rerolled_next = cells[0].cat_id, cells[0].next_label
            owner.rerolled_guaranteed_id, owner.rerolled_guaranteed_next = cells[1].cat_id, cells[1].next_label
            last_result_owner = None
        elif len(cells) == 4 and cells[0].text == "":
            # footer: last B result
            labels = sorted(positions, key=lambda s: (int(s[:-1]), s[-1]))
            if labels:
                last_b = positions[labels[-1]]
                if last_b.label.endswith("B"):
                    last_b.cat_id = cells[1].cat_id
                    last_b.guaranteed_id, last_b.guaranteed_next = cells[2].cat_id, cells[2].next_label
                    last_b.slot_seed = int(cells[3].text)
    return positions

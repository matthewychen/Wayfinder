"""Owned-units export and import that survives unit-list changes.

Export format (plain text, paste it back later):

    BCPLANNER-OWNED v1
    game: 15.6
    date: 2026-09-13
    code: <the site's compact o= value>
    689	Brainwashed Lizard Cat
    873	Jungle Gourmet Tomoe
    ...

The compact code alone is enough while unit ids are unchanged. If the game's unit list
ever shifts ids, the id/name lines let the import repair itself: every id whose name no
longer matches the current catalog is re-resolved by name, and the import reports what it
did. Import also accepts the site's cats-page URL or a bare code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .model import Catalog
from .owned import decode, encode, parse_owned_input

HEADER = "BCPLANNER-OWNED v1"
HEADERS = ("BCPLANNER-OWNED v1", "BCPLANNER-WANTED v1", "BCPLANNER-UBERS v1")   # owned, wanted copies, uber priority


@dataclass
class ImportResult:
    ids: list[int]
    notes: list[str] = field(default_factory=list)
    repaired: int = 0
    unresolved: list[str] = field(default_factory=list)
    game_version: str | None = None
    exported_on: str | None = None
    kind: str = "OWNED"


def export_text(owned: list[int], names: dict[int, str], game_version: str, today: date | None = None,
                kind: str = "OWNED") -> str:
    """kind is 'OWNED', 'WANTED' or 'UBERS'; the header tells the lists apart on import."""
    today = today or date.today()
    lines = [f"BCPLANNER-{kind} v1", f"game: {game_version}", f"date: {today.isoformat()}", f"code: {encode(owned)}"]
    for cid in sorted(owned):
        lines.append(f"{cid}\t{names.get(cid, '')}")
    return "\n".join(lines) + "\n"


def import_text(text: str, catalog: Catalog | None, names: dict[int, str], current_version: str | None = None) -> ImportResult:
    text = text.strip()
    if not text:
        return ImportResult([])
    if not text.startswith(HEADERS):
        # site URL, query string, or bare code
        return ImportResult(parse_owned_input(text), notes=["imported the site's compact code; no name check possible"])
    res = ImportResult([])
    res.kind = ("UBERS" if text.startswith("BCPLANNER-UBERS") else
                "WANTED" if text.startswith("BCPLANNER-WANTED") else "OWNED")
    code = None
    pairs: list[tuple[int, str]] = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith("game:"):
            res.game_version = line[5:].strip()
        elif line.startswith("date:"):
            res.exported_on = line[5:].strip()
        elif line.startswith("code:"):
            code = line[5:].strip()
        else:
            parts = line.split("\t") if "\t" in line else line.split(None, 1)
            try:
                pairs.append((int(parts[0]), parts[1].strip() if len(parts) > 1 else ""))
            except ValueError:
                res.unresolved.append(line)
    known = {cid: n for cid, n in names.items()}
    if catalog is not None:
        for cid, cat in catalog.cats.items():
            known.setdefault(cid, cat.name)
    ids: set[int] = set()
    if not pairs and code:
        ids.update(decode(code))
        res.notes.append("no id/name lines; used the compact code")
    for cid, name in pairs:
        current = known.get(cid)
        if not name or not known or (current is not None and current.lower() == name.lower()):
            ids.add(cid)
            continue
        # the name at this id changed or the id is unknown: the unit list shifted, resolve by name
        matches = [k for k, v in known.items() if v.lower() == name.lower()]
        if len(matches) == 1:
            if matches[0] != cid:
                res.repaired += 1
            ids.add(matches[0])
        else:
            res.unresolved.append(f"{cid} {name}")
    if res.repaired:
        res.notes.append(f"repaired {res.repaired} unit(s) whose id changed since the export")
    if res.unresolved:
        res.notes.append(f"{len(res.unresolved)} line(s) could not be matched; tick them again")
    if current_version and res.game_version and res.game_version != current_version:
        res.notes.append(f"export was made on game version {res.game_version}, current is {current_version}")
    res.ids = sorted(ids)
    return res

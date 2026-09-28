"""Read Cat Guide screenshots: every icon cell is an owned unit, every grey "?" cell is not.

The guide shows one rarity tab at a time, pages of 6 x 4 cells with a thick black frame. Owned
units are drawn with the game's own icon file (the site serves the same file: the 128 x 128
`uni###_f00.png`, of which the guide shows the 100 x 76 interior at (14, 26)-(114, 102), hiding the
icon's border). So each icon cell is identified by matching its picture against the icon library the
planner already caches, and the unit's position in the guide never matters. That is deliberate:
the guide's order is not the unit number (variants such as the Brainwashed cats are listed as a
series, seasonal variants follow their base unit) and collab units you do not own are not listed
at all, so counting "?" cells could never say which unit each one is.

Matching: normalised cross-correlation on grayscale, a coarse pass over the whole library, then a
fine pass over the best candidates with small shifts; the bottom-right corner is ignored because
the guide draws a star badge there on favourited units. Near ties are settled by colour when the
icons differ only in colour (Gold vs Metal Cat, Yuki vs Redhead Yuki), and units that still tie
(Crazed vs Brainwashed cats: the difference sits under the badge) are marked `sure=False` so the
user confirms them. Ancient Eggs all share one egg picture, so egg cells are numbered in reading
order and offered as a guess. A cell that matches nothing well is `unknown` and must be named.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .model import Catalog

ICON_BOX = (14, 26, 114, 102)       # the part of the site's 128x128 icon file the guide shows
W, H = 100, 76                      # its size
COARSE = (50, 38)
SURE_SCORE = 0.75
SURE_MARGIN = 0.06
UNKNOWN_SCORE = 0.6                 # below this the cell matches nothing in the library (real matches score 0.69+)
EGG_ASSET = Path(__file__).parent / "assets" / "ancient_egg.png"
EGG_ID = -1
RARITIES = ("legend", "uber", "supa", "rare", "special", "normal")


@dataclass
class CellResult:
    row: int
    col: int
    kind: str                       # "icon", "?", "egg" or "unknown"
    cat_id: int = 0
    name: str = ""
    rarity: str = ""
    score: float = 0.0
    margin: float = 0.0
    runner_up: int = 0
    runner_up_name: str = ""
    sure: bool = False
    candidates: list[tuple[int, str, float]] = field(default_factory=list)   # (id, name, score), best first
    crop: Image.Image | None = None  # the cell's picture, for review
    box: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def needs_check(self) -> bool:
        return self.kind in ("egg", "unknown") or (self.kind == "icon" and not self.sure)


@dataclass
class PageResult:
    name: str
    width: int
    height: int
    cells: list[CellResult]
    rarity: str = ""                # the tab this page most likely shows (majority of sure matches)

    @property
    def icons(self) -> list[CellResult]:
        return [c for c in self.cells if c.kind in ("icon", "egg")]

    @property
    def unknown(self) -> int:
        return sum(1 for c in self.cells if c.kind == "?")


# ---------------------------------------------------------------------------------------
# Icon library
# ---------------------------------------------------------------------------------------
def _flat(im: Image.Image) -> Image.Image:
    """RGB on white (the icon files have transparent corners)."""
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def _mean_colour(rgb: np.ndarray) -> np.ndarray:
    """Mean colour of the coloured pixels, as a length-3 vector in 0..255: the saturated pixels when
    there are enough of them (Yuki's blue hair, Gold Cat's yellow body), else every drawn pixel."""
    px = rgb.reshape(-1, 3).astype(np.float32)
    ink = px[px.min(axis=1) < 235]
    if not len(ink):
        return np.array([255.0, 255.0, 255.0])
    sat = ink[(ink.max(axis=1) - ink.min(axis=1)) > 60]
    return sat.mean(axis=0) if len(sat) >= 0.02 * len(px) else ink.mean(axis=0)


def egg_code(name: str) -> int:
    m = re.search(r"N(\d+)", name)
    return int(m.group(1)) if m else 10 ** 6


class IconLibrary:
    """Every cached unit icon as a 100x76 grayscale array (plus a coarse copy and a mean colour),
    keyed by unit id, with the Ancient Egg picture as an extra template."""

    def __init__(self, icons_dir: Path, catalog: Catalog):
        ids, fine, coarse, colours = [], [], [], []
        self.names: dict[int, str] = {}
        self.rarities: dict[int, str] = {}
        self.eggs: dict[str, list[int]] = {}
        for cat in catalog.cats.values():
            if cat.name.startswith("Ancient Egg"):
                self.eggs.setdefault(cat.rarity, []).append(cat.id)
                self.names[cat.id], self.rarities[cat.id] = cat.name, cat.rarity
            p = Path(icons_dir) / f"{cat.id}.png"
            if not p.exists():
                continue
            rgb = _flat(Image.open(p)).crop(ICON_BOX)
            self._add(ids, fine, coarse, colours, cat.id, rgb)
            self.names[cat.id], self.rarities[cat.id] = cat.name, cat.rarity
        for r in self.eggs:
            self.eggs[r].sort(key=lambda cid: egg_code(self.names[cid]))
        if EGG_ASSET.exists():
            self._add(ids, fine, coarse, colours, EGG_ID, Image.open(EGG_ASSET).convert("RGB").resize((W, H)))
            self.names[EGG_ID], self.rarities[EGG_ID] = "Ancient Egg", ""
        if not ids:
            raise ValueError("no unit icons in the cache; open the Owned units tab once so they are fetched")
        self.ids = np.array(ids)
        self.fine = np.stack(fine)
        self.coarse = np.stack(coarse)
        self.colours = np.stack(colours)
        self.mask_fine = _badge_mask(H, W)
        self.mask_coarse = _badge_mask(COARSE[1], COARSE[0])
        self.index = {cid: i for i, cid in enumerate(ids)}

    @staticmethod
    def _add(ids, fine, coarse, colours, cid: int, rgb: Image.Image) -> None:
        g = rgb.convert("L")
        ids.append(cid)
        fine.append(np.asarray(g, dtype=np.float32))
        coarse.append(np.asarray(g.resize(COARSE, Image.BILINEAR), dtype=np.float32))
        colours.append(_mean_colour(np.asarray(rgb)))

    def __len__(self) -> int:
        return len(self.ids)

    def all_units(self) -> list[tuple[int, str]]:
        return sorted(((cid, n) for cid, n in self.names.items() if cid != EGG_ID), key=lambda t: t[1].lower())


def _badge_mask(h: int, w: int) -> np.ndarray:
    """True where the cell is compared; the bottom-right corner (star badge) is left out."""
    yy, xx = np.mgrid[0:h, 0:w]
    return (xx / w + yy / h) <= 1.55


def _ncc_many(cell: np.ndarray, lib: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of one cell against every icon in `lib`, inside `mask`."""
    c = cell - cell[mask].mean()
    c = np.where(mask, c, 0.0)
    l = lib - lib[:, mask].mean(axis=1)[:, None, None]
    l = np.where(mask[None], l, 0.0)
    num = (l * c).sum(axis=(1, 2))
    den = np.sqrt((l * l).sum(axis=(1, 2)) * (c * c).sum()) + 1e-6
    return num / den


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


# ---------------------------------------------------------------------------------------
# Finding the cells
# ---------------------------------------------------------------------------------------
def _long_runs(mask: np.ndarray, min_len: int, axis: int) -> np.ndarray:
    """Pixels that belong to a run of True of at least `min_len` along `axis` (1 = horizontal)."""
    m = mask if axis == 1 else mask.T
    out = np.zeros_like(m)
    for i in range(m.shape[0]):
        row = m[i]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            if e - s >= min_len:
                out[i, s:e] = True
    return out if axis == 1 else out.T


def _cluster(values: list[int], gap: float) -> list[int]:
    """Index of the cluster each value falls in, clustering sorted values that are closer than `gap`."""
    order = sorted(set(values))
    labels, k = {}, 0
    for i, v in enumerate(order):
        if i and v - order[i - 1] > gap:
            k += 1
        labels[v] = k
    return [labels[v] for v in values]


def find_cells(a: np.ndarray) -> list[tuple[int, int, int, int, int, int]]:
    """(row, col, x0, y0, x1, y1) of every framed cell; the frame is included in the box.

    A frame is a pure black rectangle a few pixels thick: its left and right edges are vertical
    black runs exactly one cell tall (about 12.5% of the screenshot height), one cell width apart
    (about 7.4% of the width), joined by black top and bottom edges. Each cell is found from its
    own frame, so black strokes inside an icon or black labels elsewhere cannot shift or merge
    cells. Positions without a frame (a short last page) simply yield nothing."""
    h, w = a.shape[:2]
    black = (a[:, :, :3] < 40).all(axis=2)
    cell_w, cell_h = 0.074 * w, 0.125 * h
    ver = _long_runs(black, int(cell_h * 0.85), axis=0)
    edges: list[list[int]] = []           # [x_first, x_last, y_top, y_bottom] of vertical frame runs
    for x in np.where(ver.sum(axis=0) >= cell_h * 0.85)[0]:
        col = ver[:, x].astype(np.int8)
        d = np.diff(np.concatenate(([0], col, [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            if not (cell_h * 0.85 <= e - s <= cell_h * 1.2):
                continue
            for g in reversed(edges[-12:]):      # runs of several rows interleave; merge with the right one
                if x - g[1] <= 2 and abs(s - g[2]) <= 6 and abs(e - g[3]) <= 6:
                    g[1] = int(x)
                    break
            else:
                edges.append([int(x), int(x), int(s), int(e)])
    span = int(cell_w * 0.6)

    def is_left(g) -> bool:      # a left frame: the top edge runs on to the right
        return black[g[2]:g[2] + 3, g[0]:g[0] + span].mean() > 0.8

    def is_right(g) -> bool:     # a right frame: the top edge runs on to the left
        return black[g[2]:g[2] + 3, max(0, g[1] - span):g[1]].mean() > 0.8

    lefts = [g for g in edges if is_left(g)]
    rights = [g for g in edges if is_right(g)]
    boxes = []
    for L in lefts:
        cands = [R for R in rights if cell_w * 0.85 <= R[1] - L[0] <= cell_w * 1.15
                 and abs(R[2] - L[2]) <= 10 and abs(R[3] - L[3]) <= 10]
        if not cands:
            continue
        R = min(cands, key=lambda R: R[1] - L[0])
        x0, x1, y0, y1 = L[0], R[1], min(L[2], R[2]), max(L[3], R[3]) - 1
        if black[y0:y0 + 2, x0:x1].mean() > 0.8 and black[y1 - 1:y1 + 1, x0:x1].mean() > 0.8:
            if not any(abs(x0 - b[0]) < cell_w / 2 and abs(y0 - b[1]) < cell_h / 2 for b in boxes):
                boxes.append((x0, y0, x1, y1))
    if not boxes:
        return []
    rows = _cluster([b[1] for b in boxes], cell_h / 2)
    cols = _cluster([b[0] for b in boxes], cell_w / 2)
    cells = [(r, c, *b) for r, c, b in zip(rows, cols, boxes)]
    cells.sort(key=lambda t: (t[0], t[1]))
    return cells


# ---------------------------------------------------------------------------------------
# Reading a page
# ---------------------------------------------------------------------------------------
def _inner(x0: int, y0: int, x1: int, y1: int, h: int) -> tuple[int, int, int, int]:
    t = max(3, int(round(0.0065 * h)))          # frame thickness plus the light inner bevel
    return x0 + t + 1, y0 + t + 1, x1 - t, y1 - t


def read_page(image: Image.Image, lib: IconLibrary, name: str = "") -> PageResult:
    rgb = image.convert("RGB")
    a = np.asarray(rgb)
    gray = np.asarray(rgb.convert("L"), dtype=np.float32)
    h = a.shape[0]
    results = []
    for (r, c, x0, y0, x1, y1) in find_cells(a):
        ix0, iy0, ix1, iy1 = _inner(x0, y0, x1, y1, h)
        inner = gray[iy0:iy1, ix0:ix1]
        crop = rgb.crop((ix0, iy0, ix1, iy1))
        if inner.size == 0:
            continue
        if (inner > 200).mean() < 0.05:                 # the grey "?" placeholder has no white at all
            results.append(CellResult(r, c, "?", crop=crop, box=(x0, y0, x1, y1)))
            continue
        cell = _identify(inner, np.asarray(crop), crop, r, c, lib)
        cell.box = (x0, y0, x1, y1)
        results.append(cell)
    _resolve_duplicates(results, lib)
    page = PageResult(name, a.shape[1], h, results)
    votes: dict[str, int] = {}
    for cell in results:
        if cell.kind == "icon" and cell.sure:
            votes[cell.rarity] = votes.get(cell.rarity, 0) + 1
    page.rarity = max(votes, key=votes.get) if votes else ""
    return page


def _identify(inner: np.ndarray, rgb: np.ndarray, crop: Image.Image, r: int, c: int, lib: IconLibrary) -> CellResult:
    small = Image.fromarray(inner.astype(np.uint8))
    coarse = np.asarray(small.resize(COARSE, Image.BILINEAR), dtype=np.float32)
    top = np.argsort(-_ncc_many(coarse, lib.coarse, lib.mask_coarse))[:15]
    # fine pass at the icon's size, or at the cell's own size on a small screen (never blow a cell up)
    fw, fh = min(W, inner.shape[1]), min(H, inner.shape[0])
    fine = np.asarray(small.resize((fw, fh), Image.BILINEAR), dtype=np.float32)
    if (fw, fh) == (W, H):
        lib_top, mask = lib.fine[top], lib.mask_fine
    else:
        lib_top = np.stack([np.asarray(Image.fromarray(lib.fine[i].astype(np.uint8)).resize((fw, fh), Image.BILINEAR),
                                       dtype=np.float32) for i in top])
        mask = _badge_mask(fh, fw)
    best: dict[int, float] = {}
    for dy in (-2, 0, 2):
        for dx in (-2, 0, 2):
            shifted = np.roll(np.roll(fine, dy, axis=0), dx, axis=1)
            s = _ncc_many(shifted, lib_top, mask)
            for i, sc in zip(top, s):
                best[i] = max(best.get(i, -1.0), float(sc))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    candidates = [(int(lib.ids[i]), lib.names[int(lib.ids[i])], round(s, 3)) for i, s in ranked[:5]]
    (i1, s1), (i2, s2) = ranked[0], ranked[1]
    if int(lib.ids[i1]) == EGG_ID and s1 >= 0.6:
        return CellResult(r, c, "egg", 0, "Ancient Egg", "", round(s1, 3), 0.0, crop=crop)
    if s1 < UNKNOWN_SCORE and not (s1 >= 0.45 and s1 - s2 >= 0.2):
        # nothing fits; a weak score that still beats everything else by a wide margin (a detailed
        # icon on a small screen) goes on as a guess the user must confirm
        cands = [cand for cand in candidates if cand[0] != EGG_ID]
        return CellResult(r, c, "unknown", 0, "", "", round(s1, 3), round(s1 - s2, 3), candidates=cands, crop=crop)
    if s1 - s2 < 0.15:
        # near-identical icons: compare at the cell's own resolution, away from the badge corner
        hh, ww = int(inner.shape[0] * 0.75), int(inner.shape[1] * 0.75)
        full = {}
        for i in (i1, i2):
            ic = Image.fromarray(lib.fine[i].astype(np.uint8)).resize((inner.shape[1], inner.shape[0]), Image.BICUBIC)
            full[i] = _ncc(inner[:hh, :ww], np.asarray(ic, dtype=np.float32)[:hh, :ww])
        (i1, s1), (i2, s2) = sorted(full.items(), key=lambda kv: -kv[1])
        margin = s1 - s2
        if margin < 0.15:
            # icons that differ only in colour: the drawn pixels' mean colour decides (the yellow star
            # badge in the corner is left out, or every badged cell would look golden)
            colour = _mean_colour(rgb[_badge_mask(rgb.shape[0], rgb.shape[1])])
            d = {i: float(np.linalg.norm(colour - lib.colours[i]) / 255.0) for i in (i1, i2)}
            if abs(d[i1] - d[i2]) >= 0.08:
                i1, i2 = sorted((i1, i2), key=lambda i: d[i])
                s1, s2 = full[i1], full[i2]
                margin = 0.15 + abs(d[i1] - d[i2])
    else:
        margin = s1 - s2
    cid, cid2 = int(lib.ids[i1]), int(lib.ids[i2])
    return CellResult(r, c, "icon", cid, lib.names[cid], lib.rarities[cid], round(s1, 3), round(margin, 3),
                      cid2, lib.names[cid2], sure=_is_sure(s1, margin), candidates=candidates, crop=crop)


def _is_sure(score: float, margin: float) -> bool:
    """Detailed icons correlate less well after the game's scaling (0.7 is common) but still beat every
    other icon by a wide margin; a small margin only happens between near-identical icons."""
    return (score >= SURE_SCORE and margin >= SURE_MARGIN) or (score >= 0.6 and margin >= 0.2)


def _resolve_duplicates(cells: list[CellResult], lib: IconLibrary) -> None:
    """A unit is listed once per page, so when two cells match the same unit the weaker one must be
    its lookalike (e.g. the second "Brainwashed Cat" is really Crazed Cat); swap it and ask for a check."""
    by_id: dict[int, list[CellResult]] = {}
    for c in cells:
        if c.kind == "icon":
            by_id.setdefault(c.cat_id, []).append(c)
    for cid, group in by_id.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda c: -c.margin)
        for c in group[1:]:
            if c.runner_up and c.runner_up not in by_id:
                c.cat_id, c.runner_up = c.runner_up, c.cat_id
                c.name, c.runner_up_name = lib.names[c.cat_id], lib.names[c.runner_up]
                c.rarity = lib.rarities[c.cat_id]
            c.sure = False


def number_eggs(pages: list[PageResult], lib: IconLibrary) -> None:
    """Egg cells all look alike, so guess them in reading order across the pages of one rarity tab:
    the k-th egg cell of a tab is offered as the k-th Ancient Egg of that rarity (by code number).
    Every egg stays a "check" for the user."""
    seen: dict[str, int] = {}
    for p in pages:
        rarity = p.rarity or "special"
        eggs = lib.eggs.get(rarity, [])
        for c in p.cells:
            if c.kind != "egg":
                continue
            k = seen.get(rarity, 0)
            seen[rarity] = k + 1
            c.candidates = [(cid, lib.names[cid], 0.0) for cid in eggs]
            c.rarity = rarity
            if k < len(eggs):
                c.cat_id, c.name = eggs[k], lib.names[eggs[k]]
                c.candidates.insert(0, c.candidates.pop(k))
            c.sure = False


def read_pages(files: list[tuple[str, bytes]], lib: IconLibrary) -> list[PageResult]:
    """`files` are (name, png/jpg bytes) pairs in page order, e.g. from an upload widget."""
    pages = [read_page(Image.open(io.BytesIO(data)), lib, name) for name, data in files]
    number_eggs(pages, lib)
    return pages


def read_folder(folder: Path, lib: IconLibrary) -> list[PageResult]:
    files = []
    for p in sorted(Path(folder).iterdir()):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            files.append((p.name, p.read_bytes()))
    return read_pages(files, lib)


def png_bytes(im: Image.Image, height: int = 64) -> bytes:
    w = max(1, int(im.width * height / im.height))
    buf = io.BytesIO()
    im.resize((w, height), Image.BILINEAR).save(buf, format="PNG")
    return buf.getvalue()


def thumbnail_data_url(im: Image.Image, height: int = 48) -> str:
    """A small PNG data URL of a cell crop, for an image column in a review table."""
    import base64

    return "data:image/png;base64," + base64.b64encode(png_bytes(im, height)).decode()


def data_url(png: bytes) -> str:
    import base64

    return "data:image/png;base64," + base64.b64encode(png).decode()

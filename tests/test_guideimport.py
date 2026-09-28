"""Reading Cat Guide screenshots: synthetic pages drawn from a handful of real unit icons."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from bcplanner.guideimport import EGG_ASSET, ICON_BOX, IconLibrary, find_cells, read_page, read_pages
from bcplanner.model import Cat, Catalog

ICONS = Path(__file__).parent / "fixtures" / "icons"
UNITS = {1: ("Cat", "normal"), 2: ("Tank Cat", "normal"), 3: ("Axe Cat", "normal"), 35: ("Nekoluga", "uber"),
         92: ("Crazed Cat", "supa"), 565: ("Summerluga", "uber"), 630: ("Brainwashed Cat", "supa"),
         687: ("Goddess of Light Sirius", "uber"), 130: ("Gold Cat", "supa"), 201: ("Metal Cat", "supa"),
         182: ("Yuki Cat", "special"), 341: ("Redhead Yuki Cat", "rare"),
         900: ("Ancient Egg: N001", "normal"), 901: ("Ancient Egg: N002", "normal")}


def catalog() -> Catalog:
    cat = Catalog()
    for cid, (name, rarity) in UNITS.items():
        cat.cats[cid] = Cat(id=cid, name=name, rarity=rarity)
    return cat


def make_page(layout, scale=1.0, badge=()):
    """A Cat Guide page like an iPhone screenshot (2556 x 1179 at scale 1): `layout` holds rows of
    unit id, "?", "egg" or None (no cell); `badge` lists entries that get the star badge in the corner."""
    W, H = int(2556 * scale), int(1179 * scale)
    im = Image.new("RGB", (W, H), (70, 170, 190))
    d = ImageDraw.Draw(im)
    cw, ch, t = int(190 * scale), int(148 * scale), max(3, int(7 * scale))
    x_start, y_start, px, py = int(637 * scale), int(233 * scale), 218.6 * scale, 174.7 * scale
    for r, row in enumerate(layout):
        for c, entry in enumerate(row):
            if entry is None:
                continue
            x0, y0 = int(x_start + c * px), int(y_start + r * py)
            d.rectangle([x0, y0, x0 + cw - 1, y0 + ch - 1], fill=(0, 0, 0))
            inner = (x0 + t, y0 + t, x0 + cw - t, y0 + ch - t)          # exclusive right/bottom, like paste
            if entry == "?":
                d.rectangle([inner[0], inner[1], inner[2] - 1, inner[3] - 1], fill=(128, 128, 128))
                d.text(((inner[0] + inner[2]) // 2, (inner[1] + inner[3]) // 2), "?", fill=(170, 170, 170))
                continue
            if entry == "egg":
                icon = Image.open(EGG_ASSET).convert("RGB")
            else:
                icon = Image.open(ICONS / f"{entry}.png").convert("RGBA")
                bg = Image.new("RGBA", icon.size, (255, 255, 255, 255))
                icon = Image.alpha_composite(bg, icon).convert("RGB").crop(ICON_BOX)
            im.paste(icon.resize((inner[2] - inner[0], inner[3] - inner[1]), Image.BILINEAR), (inner[0], inner[1]))
            if entry in badge:
                x1, y1 = inner[2], inner[3]
                d.polygon([(x1 - int(60 * scale), y1), (x1, y1), (x1, y1 - int(45 * scale))], fill=(240, 180, 0))
    return im


LAYOUT = [[1, "?", 2, 3, "?", 687], [35, 565, "?", 630, 92, "?"], [None] * 6, [None] * 6]


def test_cells_are_found_and_empty_positions_skipped():
    cells = find_cells(np.asarray(make_page(LAYOUT)))
    assert len(cells) == 12
    assert {(r, c) for (r, c, *_) in cells} == {(r, c) for r in range(2) for c in range(6)}
    widths = {x1 - x0 for (_, _, x0, y0, x1, y1) in cells}
    assert all(185 <= wd <= 192 for wd in widths)        # each cell's own frame, not its neighbour's


def test_page_is_read_with_lookalikes_told_apart():
    lib = IconLibrary(ICONS, catalog())
    page = read_page(make_page(LAYOUT, badge=(2, 630, 92)), lib, "page.png")
    assert page.unknown == 4 and len(page.icons) == 8
    got = {(c.row, c.col): c.cat_id for c in page.icons}
    assert got == {(0, 0): 1, (0, 2): 2, (0, 3): 3, (0, 5): 687, (1, 0): 35, (1, 1): 565, (1, 3): 630, (1, 4): 92}
    sure = {c.cat_id for c in page.icons if c.sure}
    assert {1, 2, 3, 687} <= sure                       # distinct icons are always sure
    for c in page.icons:                                 # near-identical pairs may need a check, never a wrong pick
        assert c.score >= 0.6
        assert c.sure or {c.cat_id, c.runner_up} == {92, 630} or {c.cat_id, c.runner_up} == {35, 565}


def test_colour_twins_are_settled_by_colour():
    lib = IconLibrary(ICONS, catalog())
    page = read_page(make_page([[130, 201, 182, 341, None, None]], badge=(130, 341)), lib)
    got = {c.col: (c.cat_id, c.sure) for c in page.icons}
    assert got == {0: (130, True), 1: (201, True), 2: (182, True), 3: (341, True)}


def test_eggs_are_guessed_in_order_and_flagged():
    lib = IconLibrary(ICONS, catalog())
    pages = read_pages([("p1.png", _png(make_page([[1, "egg", 2, "egg", 3, None]], badge=("egg",))))], lib)
    eggs = [c for c in pages[0].cells if c.kind == "egg"]
    assert [c.cat_id for c in eggs] == [900, 901] and all(c.needs_check for c in eggs)
    assert pages[0].rarity == "normal"
    assert [c.cat_id for c in pages[0].cells if c.kind == "icon"] == [1, 2, 3]


def test_smaller_phone_screenshot_works_too():
    lib = IconLibrary(ICONS, catalog())
    page = read_page(make_page(LAYOUT, scale=0.55), lib)
    assert page.unknown == 4
    assert sorted(c.cat_id for c in page.icons) == [1, 2, 3, 35, 92, 565, 630, 687]


def _png(im: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()

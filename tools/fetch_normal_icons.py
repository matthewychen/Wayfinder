"""Download the item, capsule and unit icons once and bundle them in nsplanner/assets.

Items and capsules come from the Battle Cats Wiki (the game's GatyaitemD_<id>_f.png files),
unit portraits from bc.godfat.org. Run from the project folder:  .venv\\Scripts\\python tools\\fetch_normal_icons.py
"""

from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "nsplanner" / "assets"
WIKI = "https://battlecats.miraheze.org/w/api.php"
GODFAT = "https://bc.godfat.org/extract/en/uni{n:03d}_f00.png"
HEADERS = {"User-Agent": "normal-seed-planner (personal Battle Cats pull planner)"}

ITEMS = {  # item name -> game item id
    "Speed Up": 0, "Treasure Radar": 1, "Rich Cat": 2, "Cat CPU": 3, "Cat Jobs": 4, "Sniper the Cat": 5,
    "5K XP": 10, "10K XP": 11, "30K XP": 12, "50K XP": 13, "100K XP": 14, "100K XP (β)": 14, "200K XP": 15,
    "500K XP": 16, "1M XP": 17,
    "Purple Catfruit Seed": 30, "Red Catfruit Seed": 31, "Blue Catfruit Seed": 32, "Green Catfruit Seed": 33,
    "Yellow Catfruit Seed": 34, "Epic Catfruit": 40,
    "Special Catseye": 50, "Rare Catseye": 51, "Super Rare Catseye": 52, "Uber Rare Catseye": 53, "Dark Catseye": 58,
    "Catamin A": 55, "Catamin B": 56, "Catamin C": 57,
    "Cat Cannon Attack": 60, "Cat Cannon Charge": 62, "Worker Cat Rate": 63, "Worker Cat Wallet": 64,
    "Base Defense": 65, "Research": 66, "Accounting": 67, "Study": 68, "Cat Energy": 69,
}
CAPSULES = {"np": ("file", "Normalcapsule.png"), "n": ("file", "Normalcapsule.png"),
            "lt": ("item", 26), "ltg": ("file", "G-ticket.png"), "ce": ("item", 51), "cf": ("item", 40)}
UNITS = {"Cat": 1, "Tank Cat": 2, "Axe Cat": 3, "Gross Cat": 4, "Cow Cat": 5, "Bird Cat": 6, "Fish Cat": 7,
         "Lizard Cat": 8, "Titan Cat": 9, "Superfeline": 644, "Li'l Cat": 210, "Li'l Tank Cat": 211,
         "Li'l Axe Cat": 212, "Li'l Gross Cat": 246, "Li'l Cow Cat": 247, "Li'l Bird Cat": 248,
         "Li'l Fish Cat": 312, "Li'l Lizard Cat": 313, "Li'l Titan Cat": 314}


def wiki_url(filename: str) -> str:
    r = requests.get(WIKI, params={"action": "query", "titles": "File:" + filename, "prop": "imageinfo",
                                   "iiprop": "url", "format": "json"}, headers=HEADERS, timeout=30).json()
    page = next(iter(r["query"]["pages"].values()))
    return page["imageinfo"][0]["url"]


def save(img_bytes: bytes, name: str, crop=None) -> str:
    im = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    if crop:
        im = im.crop(crop)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    im.thumbnail((64, 64), Image.LANCZOS)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".png"
    im.save(OUT / slug, optimize=True)
    return slug


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = {"items": {}, "capsules": {}}
    got: dict[int, str] = {}
    for name, iid in ITEMS.items():
        if iid not in got:
            data = requests.get(wiki_url(f"GatyaitemD_{iid:02d}_f.png"), headers=HEADERS, timeout=30).content
            got[iid] = save(data, f"item_{iid}")
            time.sleep(0.2)
        index["items"][name] = got[iid]
    for code, (kind, ref) in CAPSULES.items():
        if kind == "item":
            if ref not in got:
                data = requests.get(wiki_url(f"GatyaitemD_{ref:02d}_f.png"), headers=HEADERS, timeout=30).content
                got[ref] = save(data, f"item_{ref}")
            index["capsules"][code] = got[ref]
        else:
            data = requests.get(wiki_url(ref), headers=HEADERS, timeout=30).content
            index["capsules"][code] = save(data, "capsule_" + ref.rsplit(".", 1)[0])
        time.sleep(0.2)
    for name, cid in UNITS.items():
        data = requests.get(GODFAT.format(n=cid - 1), headers=HEADERS, timeout=30).content
        index["items"][name] = save(data, "unit_" + name, crop=(14, 26, 114, 102))   # the portrait inside the frame
        time.sleep(0.2)
    # the rare ticket (what blue orbs are counted in) is the rare planner's bundled icon
    (OUT / "rare_ticket.png").write_bytes((ROOT / "bcplanner" / "assets" / "ticket.png").read_bytes())
    index["items"]["Rare Ticket"] = "rare_ticket.png"
    (OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(index['items'])} items, {len(index['capsules'])} capsules -> {OUT}")


if __name__ == "__main__":
    main()

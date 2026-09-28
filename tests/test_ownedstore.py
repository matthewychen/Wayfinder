from datetime import date

from bcplanner.model import Cat, Catalog
from bcplanner.ownedstore import HEADER, export_text, import_text

NAMES = {1: "Cat", 689: "Brainwashed Lizard Cat", 873: "Jungle Gourmet Tomoe", 565: "Summerluga"}


def catalog_from(names):
    c = Catalog()
    for cid, n in names.items():
        c.cats[cid] = Cat(cid, n, "uber")
    return c


def test_export_roundtrip():
    text = export_text([873, 689, 1], NAMES, "15.6", date(2026, 9, 13))
    assert text.startswith(HEADER) and "game: 15.6" in text and "689\tBrainwashed Lizard Cat" in text
    res = import_text(text, catalog_from(NAMES), NAMES, current_version="15.6")
    assert res.ids == [1, 689, 873] and res.repaired == 0 and res.unresolved == []


def test_import_repairs_shifted_ids():
    # exported when Summerluga was 565; a new unit was inserted so it is now 566
    text = export_text([565, 689], NAMES, "15.6", date(2026, 9, 13))
    shifted = {1: "Cat", 565: "Brand New Unit", 566: "Summerluga", 690: "Brainwashed Lizard Cat", 689: "Other Cat"}
    res = import_text(text, catalog_from(shifted), shifted, current_version="15.7")
    assert res.ids == [566, 690]
    assert res.repaired == 2
    assert any("15.6" in n and "15.7" in n for n in res.notes)


def test_import_accepts_site_url_and_bare_code():
    from bcplanner.owned import encode
    code = encode([689, 873])
    assert import_text(f"https://bc.godfat.org/cats?lang=en&o={code}", None, NAMES).ids == [689, 873]
    assert import_text(code, None, NAMES).ids == [689, 873]
    assert import_text("", None, NAMES).ids == []


def test_wanted_export_has_its_own_header_and_roundtrips():
    text = export_text([689, 873], NAMES, "15.6", date(2026, 9, 14), kind="WANTED")
    assert text.startswith("BCPLANNER-WANTED v1")
    res = import_text(text, catalog_from(NAMES), NAMES)
    assert res.kind == "WANTED" and res.ids == [689, 873]
    owned = import_text(export_text([1], NAMES, "15.6"), catalog_from(NAMES), NAMES)
    assert owned.kind == "OWNED" and owned.ids == [1]


def test_import_reports_unmatched_lines():
    text = HEADER + "\ngame: 15.6\n999\tNo Such Cat\n689\tBrainwashed Lizard Cat\n"
    res = import_text(text, catalog_from(NAMES), NAMES)
    assert res.ids == [689]
    assert res.unresolved == ["999 No Such Cat"]

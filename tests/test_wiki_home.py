from bcplanner.wiki import (COLLAB, EXCLUSIVES, NOT_GACHA, NOT_GACHA_GROUP, REGULAR_POOL, UNKNOWN, display_name,
                            find_event, home_groups, short_alias)

RYU = ("Ryu is an [[:Category:Uber Rare Cats|Uber Rare Cat]] that can be obtained by playing the "
       "[[Cat Capsule#Rare Capsule|Rare Capsule]] during the [[Street Fighter Collaboration Event]].")
ZEUS = ("can be unlocked by playing the [[Cat Capsule#Rare Capsule|Rare Capsule]] during the "
        "[[The Almighties The Majestic Zeus (Gacha Event)|The Almighties]] event.")
CORNELIA = ("created by [[Merc Storia Collaboration Event/Gacha Drop|Merc Storia Collaboration Gacha]] and can be "
            "unlocked by drawing the [[Cat Capsule#Rare Capsule|Rare Capsule]] during the event. [[True Form]]")
CRAZED = "can be unlocked once clearing the event stage [[Dark Souls (Insane)|The Crazed Cat]]. See [[Cat Capsule]]."
BASE_MINI = ("can be obtained by playing the [[Cat Capsule#Rare Capsule|Rare Capsule]]. In [[The Battle Cats Unite!]], "
             "it is unlocked in the [[UBERFEST (Gacha Event)/Switch Version|UBERFEST]] banner.")
KYOKO = ("'''Kyoko Sakura''' is an Uber Rare Cat that can be unlocked during the "
         "[[Puella Magi Madoka Magica Collaboration Event]].\n==Evolution==\n[[Category:Gacha Cats]]")
BLIZA = ("can be unlocked by playing the Rare Cat Capsule during the [[Nature's Guardians ELEMENTAL PIXIES (Gacha Event)|"
         "Pixies]] and [[Colossus Busters (Gacha Event)|Colossus Busters]] events.")
REGULAR = ("'''Nerd Cat''' can be unlocked by playing the [[Cat Capsule#Rare Capsule|Rare Capsule]].\n==Trivia==\n"
           "Featured in the [[SUPERFEST (Gacha Event)|Superfest]] banner.\n[[Category:Gacha Cats]]")
CRAZED_POP = ("'''Crazed Axe Cat''' can be unlocked once clearing [[Dark Souls (Insane)|its stage]]. In [[The Battle "
              "Cats POP!]], it is obtainable via [[Cat Capsule|Rare Cat Capsules]] after clearing Cosmic Club.")
NENEKO = ("'''Neneko''' can be obtained by playing the [[Cat Capsule#Rare Capsule|Rare Capsule]]. In [[The Battle Cats "
          "Unite!]], she is exclusively unlocked in the [[UBERFEST (Gacha Event)|UBERFEST]] banner.")


def test_find_event_reads_sets_collabs_and_non_gacha_pages():
    assert find_event(ZEUS) == ("The Almighties The Majestic Zeus", "ok")
    assert find_event(RYU) == ("Street Fighter" + COLLAB, "ok")
    assert find_event(CORNELIA) == ("Merc Storia" + COLLAB, "ok")      # event link before the capsule link
    assert find_event(CRAZED) == (None, "not from the Rare Capsule")
    assert find_event(BASE_MINI) == (None, "no event on page")        # the Switch banner does not count
    assert find_event(KYOKO) == ("Puella Magi Madoka Magica" + COLLAB, "ok")   # category, no capsule sentence
    assert find_event(BLIZA) == ("Nature's Guardians ELEMENTAL PIXIES", "ok")  # plain-text capsule, first set wins
    assert find_event(REGULAR) == (None, "no event on page")          # banners named in later sections do not count
    assert find_event(CRAZED_POP) == (None, "not from the Rare Capsule")   # the 3DS game's capsule does not count
    assert find_event(NENEKO) == (None, "no event on page")           # nor the Switch game's banners


def test_home_groups_keep_collabs_and_split_off_non_gacha_units():
    home = home_groups({1: "Street Fighter" + COLLAB, 2: NOT_GACHA, 3: "Best of the Best", 4: "NEO Best of the Best"},
                       {1: "uber", 2: "supa", 3: "uber", 4: "uber"})
    assert home == {1: "Street Fighter collab", 2: NOT_GACHA_GROUP, 3: "Best of the Best", 4: "Best of the Best"}


def test_home_groups_lump_exclusives_and_alias_sets():
    titles = {
        1: "Lords of Destruction DRAGON EMPERORS", 2: "Lords of Destruction DRAGON EMPERORS",
        3: "Lords of Destruction DRAGON EMPERORS", 4: "The Almighties The Majestic Zeus",
        5: "Agent Staal Joins the Fight", 6: "Trixi Special Capsules", 7: None, 8: None,
        9: "Gals of Summer Blue Ocean", 10: "Gals of Summer Blue Ocean", 11: "Gals of Summer Blue Ocean",
    }
    rarities = {1: "uber", 2: "uber", 3: "uber", 4: "uber", 5: "uber", 6: "uber", 7: "supa", 8: "uber",
                9: "uber", 10: "supa", 11: "uber"}
    home = home_groups(titles, rarities)
    assert home[1] == home[2] == home[3] == "Dragon Emperors"
    assert home[4] == "The Almighties"          # aliased sets are never lumped, even with one member
    assert home[5] == EXCLUSIVES and home[6] == EXCLUSIVES
    assert home[7] == REGULAR_POOL and home[8] == UNKNOWN
    assert home[9] == home[10] == home[11] == "Summer Gals"


def test_every_busters_set_keeps_its_own_name():
    assert short_alias("RED BUSTERS") == "Red Busters"
    assert short_alias("Colossus Busters") == "Colossus Busters"
    assert short_alias("AIR BUSTERS") == "Air Busters"
    assert short_alias("RoyalFest") == "Royalfest"
    # a lone Busters uber is a named set, not a single-banner exclusive
    home = home_groups({1: "Colossus Busters", 2: "RED BUSTERS"}, {1: "uber", 2: "uber"})
    assert home == {1: "Colossus Busters", 2: "Red Busters"}


def test_alias_and_display_name():
    assert short_alias("Ancient Heroes ULTRA SOULS") == "Ultra Souls"
    assert short_alias("Something Unheard Of") is None
    assert display_name("Cyber Academy Galaxy Gals", "blurb") == "Galaxy Gals"
    assert display_name("Brand New Set Name", "blurb") == "Brand New Set Name"
    assert display_name(None, "Survive! Mola Mola!") == "Survive! Mola Mola!"


def test_picker_search_matches_name_home_and_running_banner():
    from bcplanner.session import row_matches

    row = {"name": "Zeus", "home": "The Almighties", "banners": "Legend Capsules, The Almighties"}
    assert row_matches(row, "almighties")
    assert row_matches(row, "ZEUS")
    assert row_matches(row, "legend cap")
    assert not row_matches(row, "dragon")
    assert row_matches(row, "")


def test_catalog_skips_units_without_an_english_name():
    from pathlib import Path
    from bcplanner.scrape import parse_cats

    cat = parse_cats((Path(__file__).parent / "fixtures" / "cats.html").read_text(encoding="utf-8"))
    names = [c.name for c in cat.cats.values()]
    assert "Easter Neneko" in names and "Goddess of Light Sirius" in names
    assert not any(n[0].isdigit() and n[-1].isdigit() and ("_" in n or "-" in n) for n in names)
    assert not any(0x3040 <= ord(ch) <= 0x9fff for n in names for ch in n)   # no kana or kanji names
    assert "Kano ＆ Souma" in names                                          # a full-width & is fine

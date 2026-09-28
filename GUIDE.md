# Battle Cats Pull Planner: guide

Exact, seed-based planner for spending rare tickets, cat food, platinum tickets and
legend tickets on the banners open today and tomorrow. The game's gacha is a plain
xorshift32 generator, so once your seed is known every future roll is known; this
tool searches for the best way to spend what you have. See `PLAN.md` for the design.

Banner data is read from bc.godfat.org (by godfat, source on GitLab), and every fetched
page is checked against the simulation before it is used.

## Using the planner

How to install and start it: see README.md.

1. On bc.godfat.org, find your seed (or open your tracks page after your last roll) and copy the URL
   into the sidebar. Enter rare tickets, cat food, platinum tickets to use and legend tickets.
2. Press **Fetch banners**. Banners are named by their official gacha-event title (looked up on the
   Battle Cats Wiki through each uber's page), e.g. *The Almighties*, *Dragon Emperors*, *Summer Gals*.
3. In **Owned units**, tick what you own in the icon grid (sorted by rarity, then banner; filters and
   "mark all shown" buttons help). The grid lists every gacha unit of the English version (from the
   site's full cat list, so seasonal collab units are there even when their banner is not running);
   switch off **Every gacha unit in the game** to see only today's banners and the platinum pool.
   **Group by home banner** sorts by the set a unit belongs to, looked up once per unit on the Battle
   Cats Wiki (a snapshot for every unit ships with the app): named sets such as *Dark Heroes*, every
   "... Busters" set under its own name, collabs as "*Street Fighter collab*", and *Regular pool*.
   Units the wiki says never came from the Rare Capsule (stage rewards such as the Crazed Cats) are
   left out of the every-unit list. Rares count too: an unticked rare is new and worth as much as a
   new super rare, a repeat rare nothing. The quickest way to fill the list is
   **Import from Cat Guide screenshots** at the bottom of the tab: in the game open the Cat Guide,
   choose a rarity with Filter, screenshot every page, and drop the images in (or name a folder).
   Owned units are recognised from their icons and added to your list after a review table; grey
   "?" cells are skipped. Anything doubtful (Ancient Eggs, which all look alike; the near-identical
   Crazed and Brainwashed cats; a picture that matches nothing) is shown under **What unit is this?**
   with its screenshot, a preselected guess and a full unit list, so nothing wrong slips in. Do every
   tab, including Normal and Special, for a complete list. **Uber priority** lists the ubers you do
   not own yet: tick the ones you care about most and they sort to the top of the platinum table in
   Options ("Where a platinum ticket could go": every position, the uber a platinum ticket gives there,
   ★ priority, ✓ new); with the Advanced "Uber priority multiplier" above 1 the plan favours them too.
   **Wanted copies** holds units you want extra copies of. Under Advanced, "A repeat is worth" gives
   repeat super rares, ubers or legends a value (defaults 0.05, 0.2 and 0). "Going past an uber slot on the other
   track costs" charges every uber slot on the track you are not on that the path moves beyond
   (default 0.8 for a regular uber slot, 0.2 for an Uberfest-only one) when a banner open today or
   tomorrow would give a new uber there: once passed, that uber is gone for good, so a plan will
   sooner keep a ticket than roll past ubers it cannot reach; a legend slot has its own, much higher
   price. A slot where every open banner would only repeat an uber costs that repeat's value instead
   (the plan rows mark it "(repeat)"), so rolling through repeats is never preferred to taking a new
   uber elsewhere. Every rare ticket spent also costs a little ("Each rare
   ticket costs", 0.02). A legend ticket is only ever a stand-in for a rare ticket: it is used at a
   legend slot only when the plan must cross that slot anyway on its way to something new, the legend
   there is new, and every banner open today or tomorrow would give a repeat uber there; a plan never
   ends on a legend ticket. The plan rows say "passes uber slot 7B" where it happens. Exact depth gives
   up its proof after two minutes and keeps the Thorough result, so it never hangs. **Saving for the next banner**: the seed only moves
   when you roll, so positions you keep are the positions the next banner will use; the plan spends a
   position now only when its real gain beats what it is expected to give later (a future 11-draw's
   worth as a flat number, or estimated from the seed's bands and the chance a next-banner unit is
   new to you). Kept tickets also count as steering: on a future guaranteed banner every ticket rolled
   before the 11-draw moves its guaranteed slot one position, so more tickets mean more ubers to
   choose from. One slider under Advanced, "Outlook for the next banner", sets how good that banner
   is assumed to be; the chances and the floor under the value of kept resources are derived from it
   and your owned list. The Plan tab shows what is kept, and Options shows "later" and "total" per row.
   Everything you enter is saved locally in
   `data_cache/settings.json` so it is there next time. **Export** gives a text block with a game
   version tag and id/name lines; paste it back with **Import** on any machine. If unit ids ever shift,
   the import repairs itself by name and tells you what it did.
4. Under **Banner options** in the sidebar, tick per banner whether the 11-draw carries a guaranteed
   uber. Tick "First 11-draw of this plan costs 750 CF" when the half-price offer is up; it applies once,
   to whichever 11-draw the plan does first.
5. Optionally, in **Wanted copies**, tick super rares and rares you want extra copies of. These only
   decide which banner a single ticket is rolled on when the choice changes nothing else in the plan;
   a toggle allows a one-day clock change around such a roll.
6. Press **Plan**. The **Tracks** tab then shows the site's two-track table for any banner, in the
   site's colours, with the chosen plan drawn over it: darkened cells for the positions it uses,
   darker for the rolls of an 11-draw, stripes on the position after the last roll, and step badges. The **Plan** tab lists every pull, rares included, with unit icons, site positions,
   new units flagged and ubers/legends highlighted, plus a cross-check link into bc.godfat.org after every
   step. The **Options** tab shows what you get for no cat food, one 11-draw, two, and so on, and whether
   your platinum tickets add anything. Download the plan and follow it. Stop at the first result that differs.

## Command line

```bash
python -m bcplanner.cli --url "https://bc.godfat.org/?seed=...&last=...&event=..." --owned "https://bc.godfat.org/cats?o=..." --tickets 30 --cf 6000 --plats 3 --legends 1 --out plan.md
```

`--fixtures` plans from the saved pages in `tests/fixtures` without touching the network.

## Deploy online (Streamlit Community Cloud)

The app needs a Python server, so it cannot run on GitHub Pages. Streamlit Community Cloud hosts it for
free straight from a GitHub repository.

1. The code lives at https://github.com/matthewychen/Wayfinder (push your changes there first).

2. Go to https://share.streamlit.io, sign in with GitHub, press **Create app**, pick `matthewychen/Wayfinder`,
   branch `main`, main file `app.py`. Under *Advanced settings* choose Python 3.11 and paste this into
   *Secrets* so visitors' inputs never touch the shared settings file:

   ```toml
   stateless = true
   ```

3. Deploy. The first start installs the three requirements; afterwards the app behaves like the local
   one, except that inputs live in each browser tab only. Keep your owned and wanted lists with the
   export text and paste them back when you return. Icon, wiki and banner caches are shared on the
   server and rebuilt automatically if it restarts.

4. Sharing: an app from a private repository is still viewable by anyone with the link unless you
   restrict viewers in the app's *Share* settings.

To run locally with the same stateless behaviour, set `BCPLANNER_STATELESS=1` before starting.

## How sure is the plan?

Three search depths, under Advanced:

- **Normal** keeps the 12 best partial plans at each state (same position, last rare, discount state,
  and spend; a day change is folded into the roll that needs it, so plans that switched the date and
  plans that did not compete for the same slots). Up to about a minute on a large budget.
  It cannot prove its answer. On the largest case tested (30 tickets, four 11-draws, three platinum,
  one legend ticket) a width of 6 missed one super rare that width 12 found, which is why 12 is the
  default; widths 12 and 30 agreed on every case tested.
- **Thorough** keeps 30. Several minutes on a large budget, same caveat.
- **Exact** runs Thorough and then a full search that discards a partial plan only when a proven
  upper bound says it cannot beat the incumbent at any spend level. When it finishes, the plan
  caption reads "proven optimal": no plan within your resources and the modelled rules scores
  higher, and the full-coverage plan is the certified cheapest. Measured: 24 s for 15 tickets and two
  draws, 8.5 min for 20 tickets and three draws (both confirmed the Normal answer), and it did not
  finish within 30 min for 30 tickets and four draws. Use it to certify small and medium plans.

"Optimal" always means under your weights (super 0.8, uber 1, legend 5, wishlist multipliers) and
the rules in the plan document.

## Tests

```bash
python -m pytest tests -q
```

Golden tests reproduce seven saved site pages cell for cell; the search is checked against
brute-force enumeration on toy banners; every plan is re-run by an independent replay.

## Layout

```
bcplanner/prng.py      xorshift32 and its inverse
bcplanner/owned.py     o= owned-units codec
bcplanner/model.py     Cat, Banner, Catalog
bcplanner/sim.py       roll primitives, 11-draws, site-table reproduction
bcplanner/sitetable.py parser for the site's Details table
bcplanner/scrape.py    fetch, parse, cache, self-test
bcplanner/problem.py   values, rules, resources shared by search and replay
bcplanner/search.py    label search (exact dominance + beam), exact mode with bound pruning
bcplanner/bounds.py    relaxed upper bound used by exact mode
bcplanner/tracks_view.py the site's two-track table with the plan overlaid
bcplanner/replay.py    independent replay and legality check
bcplanner/metrics.py   per-plan metrics
bcplanner/report.py    step tables, Markdown and CSV
bcplanner/session.py   assembly for CLI and GUI, saved settings, display names
bcplanner/options.py   "how much to spend" and platinum-ticket comparisons
bcplanner/priority.py  re-routes single tickets to banners with wanted copies, nothing else
bcplanner/wiki.py      official banner titles from the Battle Cats Wiki (cached)
bcplanner/icons.py     unit portraits from bc.godfat.org (cached) and item icons
bcplanner/ownedstore.py owned-list export/import that survives unit-id shifts
bcplanner/cli.py       command line
app.py                 Streamlit GUI
tests/                 unit, golden, brute-force and replay tests
```

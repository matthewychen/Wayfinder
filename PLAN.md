# Battle Cats Pull Planner — Design Plan

Status: implemented through milestone M4 on 2026-09-13 (see "Build log" at the end). Written 2026-09-13 for Matthew (English region, BCEN).

The plan describes a local tool that reads your current gacha position and owned units, models the game's roll mechanics exactly, and searches for the best way to spend rare tickets, cat food, platinum tickets and legend tickets on the banners live today and tomorrow. Every section is written so that it can be implemented and checked independently.

## 0. Decisions carried in from the discussion

Confirmed by you:

- Region is BCEN. The seed comes from your bc.godfat.org tracks URL.
- Cat food is never spent on 150 CF singles. It is only spent on 11-draws at 1500 CF, or 750 CF for the first 11-draw on a banner where the discount box is ticked.
- Resources in play: rare tickets, cat food, platinum tickets (you enter how many to use), legend tickets.
- Legend tickets are only ever used at a legend slot that yields a legend you do not own. Whenever that is possible it is mandatory. They are never used anywhere else.
- Refined 2026-09-16: a legend ticket only stands in for a rare ticket. It may be used at a slot only when the plan has to cross that slot anyway on its way to something better (a later roll of the plan gains something new), the legend there is new, and every banner open today or tomorrow gives a repeat uber at that slot. If any open banner gives a new uber there, the rare ticket takes the uber and the legend ticket stays in the pocket. When the conditions hold the ticket is mandatory; otherwise the plan stops before the slot or rolls through it. Legend tickets are never spent just to grab a legend.
- Platinum tickets are the tool for uber slots. Platinum and legend banners share one uber pool.
- A new rare is worth as much as a new super rare (rule of 2026-09-16; before that rares were 0); a repeat rare is worth nothing. A new super rare is worth 0.8 of a new uber. Legends are must-gets. Exclusives get a multiplier.
- 30 rare tickets are worth one 11-draw. Tunable.
- The device clock can be moved forward one day and back. No chaining. The plan must say which date each action happens on.
- Whether an 11-draw may roll across a legend slot is a GUI toggle.
- Per-banner checkboxes in the GUI: guaranteed 11-draw, 750 CF first draw. Uberfest and Epicfest are never guaranteed. Platinum and legend banners never are.
- Outputs: the best plan under your caps, the cheapest plan that collects every unowned unit on today's banners with tradeoffs when that is infeasible, heatmaps over tickets and cat food, a few highlighted paths with efficiency metrics, and an action list with dates.
- Interleaving banners freely is fine.
- Only tomorrow's banners matter beyond today. Banner data is scraped from the live site, not pulled from git, because the repository does not contain current banner data.

Assumed until you say otherwise. Each has a default the build will use:

> A1. The GUI is Streamlit, a local Python web app. One `pip install`.
> A2. Repeated one-day skips are allowed: forward, back, and forward again later. Each clock change carries a small penalty and an optional cap.
> A3. No real-day waiting in version 1. A plan is for one sitting. The plan date is an input so the tool can be run on any day.
> A4. Inputs arrive as pasted URLs: the tracks URL for the seed and the cats-page URL for owned units. Exclusives come from a small text file.
> A5. An 11-draw on a banner without the guarantee is 11 normal rolls, 22 steps, no parity change. A banner that offers no 11-draw at all has its "11-draw offered" box unticked.
> A6. Rare tickets work on every rare banner, collabs included.
> A7. Step-up banners (3+5+7) are one atomic 15-roll action costing 2100 CF. Partial steps are not modelled in version 1.
> A8. Dupe memory persists across banners and is cleared by any non-rare result from any source, including platinum, legend and guaranteed ubers.

## 1. Goal

Given your seed, your last rolled cat, your owned units, your resources and the banners live today and tomorrow, produce an exact, verifiable sequence of actions that maximises weighted new units, never wastes a legend slot, and shows you the tradeoff between spending and gain so you can choose the cutoff yourself.

The tool is deterministic. The game's randomness is fully known once the seed is known, so the planner never estimates probabilities. It enumerates what will actually happen.

## 2. Mechanics model

This section is the ground truth the whole tool rests on. Items marked verified were confirmed against the site's source and its live output during the reverse engineering. Items marked to verify are checked in milestone M0 before anything depends on them.

### 2.1 The generator

The game's save holds one 32-bit number. Every roll steps it with xorshift32 using shifts 13, 17, 15. The step is invertible, which is what the site's Backtrack link uses. Verified.

```python
MASK = 0xFFFFFFFF
def advance(s):
    s ^= (s << 13) & MASK
    s ^= s >> 17
    s ^= (s << 15) & MASK
    return s
```

### 2.2 Offsets replace tracks

Define `S[0]` as the seed in your URL and `S[i+1] = advance(S[i])`. Your position is an integer offset `k`, the number of steps consumed since `S[0]`. The next roll at offset `k` uses `S[k+1]` to decide rarity and `S[k+2]` to decide the cat, and leaves you at `k+2`.

The site's track labels are a view of the same thing. Offset `k` is the site's row `k // 2 + 1`, track A when `k` is even and track B when odd. A track switch is nothing more than consuming an odd number of steps. Verified: all 400 seed cells on your page match this mapping.

A bc.godfat.org link for any state is `?seed=S[k]&last=<last cat id>&event=<event>` because the site advances the URL seed once before its first row. Verified.

### 2.3 One roll

- `score = S[k+1] % 10000`. Rarity is chosen by bands from the banner's rates: rare if `score < rare`, super if below `rare + supa`, uber if below `rare + supa + uber`, otherwise legend. Rates are per 10000. Your current banner is 7000 / 2500 / 500 / 0. Regular banners are usually 6970 / 2500 / 500 / 30. Verified.
- `slot = S[k+2] % pool_size` for that rarity. The pool order is the order the site lists in its Details view. Verified.
- The rolled cat becomes the last cat.

### 2.4 The duplicate rare rule

If the result is rare and its id equals the last cat's id, the game takes one extra step `S[k+3]`, removes the duplicate's slot from the rare list, and picks `S[k+3] % (n - 1)` from what remains. That extra step is why you land on the other track. If the pool contains the same cat more than once the loop repeats, one step each time. Verified against 5A and 14B on your page.

Consequences the planner relies on: the rule compares against your actual last cat, across banners, not against a track. Any uber or legend result clears the memory, so a platinum ticket can dodge a reroll. After a reroll the rerolled cat is the new last cat, so a second reroll can follow immediately.

### 2.5 The 11-draw

On a banner with the guarantee, taken from the site's source:

- 10 normal rolls exactly as in 2.3 and 2.4, so a duplicate rare mid-draw rerolls and shifts parity.
- The 11th roll uses one step only. With the 10 rolls finished at offset `k'`, the guaranteed uber is `ubers[S[k'+1] % n_uber]` from that banner's uber list, and you land at `k'+1`.
- The guaranteed uber becomes the last cat, so the next roll can never be a dupe reroll.
- Net 21 steps plus one per reroll. Cost 1500 CF, or 750 CF for the first draw on a discounted banner.

Step-up banners are the same with 14 rolls before the guaranteed one, 29 steps. Non-guaranteed 11-draws are 11 rolls of 2.3, 22 steps, under assumption A5.

### 2.6 Platinum and legend tickets

Both banners share the seed with everything else. Verified from the site's help text.

- Platinum: rates 0 / 0 / 10000. Two steps. Result `plat_ubers[S[k+2] % n]`. Clears dupe memory.
- Legend banner: rates 0 / 0 / 9500 / 500, to verify. Two steps. If `score >= 9500` the result is `legends[S[k+2] % n_legend]`, otherwise `ubers[S[k+2] % n_uber]` from the same shared uber pool, to verify.

A legend slot is any offset `k` with `S[k+1] % 10000 >= 10000 - legend_rate` on the legend banner. Legend slots are fixed by your seed and sit on both parities. Reaching one on the other parity requires an odd-step action: an 11-draw with the guarantee, or a dupe reroll. The planner finds these alignments itself.

Regular banners with a 0.3% legend rate also yield a legend at `score >= 9970` from their own legend list. This falls out of 2.3 automatically.

### 2.7 Time skipping

Moving the device date does not touch the seed. It only changes which banners are open. The clock has two values, today and tomorrow. Banners have live-day sets drawn from the site's date ranges, with end dates treated as exclusive, to verify at a boundary such as 2026-09-14.

### 2.8 The state

Everything the game will do next is determined by:

- `k`, the offset.
- `last_rare`, the id of the last cat if it was rare, else 0.
- `clock`, today or tomorrow.
- `discount_used`, one bit per banner with the 750 CF box ticked.

Resources spent and units gained are properties of the path, not of the game.

### 2.9 Worked example from your URL

Seed 3163852999, last cat 689 (Brainwashed Lizard Cat, a super rare, so no dupe pressure at 1A).

| Offset | Site label | Rarity seed | Score | Result |
|---|---|---|---|---|
| 0 | 1A | 491579265 | 9265 | super, slot 5 of 23, Lifeguard Cats |
| 1 | 1B | 3256026975 | 6975 | rare, slot 6 of 25, Psychocat |
| 8 | 5A | 2510915971 | 5971 | rare Rocker Cat, duplicates 4A, rerolls to Jurassic Cat, +1 step, lands at 6B |
| 20 | 11A | 2803218912 | 8912 | if an 11-draw had started at 1A, this seed picks the guaranteed uber: slot 4 of 7, Kaguya of the Coast, landing at 11B |

### 2.10 Verified versus to verify

Verified: the generator and its inverse; two steps per roll; rarity bands; slot order; the dupe reroll; tracks as parity; the guaranteed formula; guaranteed ubers use the banner's own uber list; the guaranteed uber clears dupe memory; all banners share the seed; platinum consumes two steps and clears dupe memory; dupe memory carries across banners.

To verify in M0: platinum uber list equals the legend banner's uber list in the same order; legend banner rates; guaranteed and 11-draw availability per live banner; the `o=` decoder against a URL you produce; the Details page's legend line on a 0.3% banner; end-date exclusivity.

## 3. Data layer

### 3.1 Sources

All data comes from bc.godfat.org over plain HTTPS GET requests, cached locally.

- Banner pools and rates: `/?seed=1&event=<YYYY-MM-DD_ID>&details=true&lang=en`. The Gacha information block lists each rarity as a percentage, a count, and the ordered cats with ids and names. Percentages become per-10000 integers by multiplying by 100. The page also renders its own table for seed 1, which doubles as a parse self-test (3.7).
- Banner discovery: the event dropdown on the same page. Each option is `<option value="2026-09-11_1076">2026-09-11 ~ 2026-09-18: name</option>`. Keep entries whose range covers today or tomorrow.
- Master unit list: `/cats?lang=en`, about 772 units with ids, names and rarity headings. Used to name owned units and to classify ids.
- Guaranteed flag: the Details table shows a Guaranteed column with content only on guaranteed banners, and labels such as 1AG. The GUI checkbox is prefilled from this and you can override it.
- Banner kind: uber rate 10000 means platinum; uber plus legend equal to 10000 means legend banner; anything else is a rare banner.

### 3.2 Owned units

The cats page has a checkbox per unit and an "Own all ticked" button. The resulting URL carries `o=`, a base-62 number using digits 0-9, a-z, A-Z in that order, where bit `id` set means you own cat `id`. The decoder is a direct port of the site's owned.rb. You paste either the URL or the raw string. The tool reports the count decoded by rarity so you can sanity check it. A plain text list of names is accepted as a fallback with fuzzy matching and a confirmation table.

### 3.3 Exclusives and weights

`wishlist.txt`, one unit per line as `name or id, multiplier`. Missing multiplier means the default from the GUI. Names are matched against the master list and any unmatched line is shown as an error rather than silently ignored. The site tags some cats as exclusive in its own data. M0 checks whether that tag is visible in the HTML and, if so, offers it as a one-click way to fill the wishlist.

### 3.4 Cache and refresh

`data_cache/<plan date>/<event id>.json` and `cats.json`, 24 hour lifetime, plus a Refresh button that bypasses the cache. Each cached file records the fetch time and the site's version string so stale data is visible in the GUI.

### 3.5 Validation on every fetch

- Rates sum to 10000 after the legend remainder.
- Rare banners have non-empty rare, super and uber lists. Platinum has only ubers.
- Every id resolves in the master list.
- Platinum uber list equals the legend banner uber list in order. Mismatch is a warning that switches the legend banner to its own list.
- Parse self-test: simulate 20 rows from seed 1 and compare names with the table on the fetched page. Any mismatch blocks planning with a clear message.

### 3.6 Politeness and failure

Under ten requests per refresh, a User-Agent naming the tool, no retries in tight loops. If the HTML structure changes, the parser fails with a message naming the block it could not find, and the saved fixture files in `tests/fixtures` show what it expected.

## 4. Simulation core

### 4.1 Precomputation

Horizon `H = 2T + 22C + 2P + 2L` plus ten percent for rerolls, where `T`, `C`, `P`, `L` are tickets, 11-draws, platinum and legend tickets. Compute `S[0..H+3]` once. Compute `score[k]` once since it is banner-independent. For each banner precompute arrays over `k`: rarity, cat id, and for rares the reroll outcome and its extra step count. For the legend banner precompute `legend_slot[k]` and the legend id at each slot. After this, a roll during search is a few array lookups and no arithmetic on seeds.

### 4.2 Primitives

- `single(banner, k, last_rare)` returns the cat, rarity, new offset, new last, and a reroll flag.
- `eleven(banner, k, last_rare, guaranteed)` returns the 10 or 11 results, the guaranteed uber if any, new offset and new last.
- `platinum(k)` and `legend_ticket(k)` return the uber or legend, and offset `k+2`.
- `replay(actions, start_state)` runs a full action list from scratch and returns every result, resource totals and legality checks. This is the independent checker used by tests and by the GUI (5.11).

### 4.3 Actions

| Action | Precondition | Steps | Cost | Result |
|---|---|---|---|---|
| Single on banner X | X live on the clock; a ticket left | 2, +1 per reroll | 1 rare ticket | 1 cat |
| 11-draw on X, guaranteed | X live; 11-draw offered; guaranteed ticked; CF left | 21, +rerolls | 1500 CF, or 750 first time if discounted | 10 cats + 1 uber |
| 11-draw on X, no guarantee | as above with guaranteed unticked | 22, +rerolls | same | 11 cats |
| Platinum ticket | a platinum ticket left | 2 | 1 platinum | 1 uber from the shared pool |
| Legend ticket | legend slot at k; that legend unowned; a ticket left | 2 | 1 legend ticket | 1 legend |
| Set clock forward | clock is today | 0 | skip penalty | tomorrow's banners open |
| Set clock back | clock is tomorrow | 0 | skip penalty | today's banners open |
| Stop | always | 0 | none | plan ends |

### 4.4 Verification harness

Golden tests fetch, or load from fixtures, four site pages and compare 100 rows of names and seeds with the simulation: your URL with its two dupe rerolls, a guaranteed banner including the guaranteed column and its jump labels, the platinum banner, and the legend banner. A fifth test sets `last` to a rare that duplicates 1A and checks the immediate reroll.

## 5. Search

### 5.1 The problem

Maximise the weighted value of newly gained units subject to resource caps, the legend rule, the clock rules and the toggles, over the directed graph whose nodes are game states from 2.8 and whose edges are the actions of 4.3. Every unit's value is paid once, the first time it is gained. Rare tickets, cat food, platinum and legend tickets are separate resources. Cat food is counted in 750 CF units so the discount is an integer.

### 5.2 Nodes and labels

Node: `(k, last_rare, clock, discount_used)`.

Label at a node: tickets used, cat food units used, platinum used, legend tickets used, clock changes, `gained`, and a back pointer to the parent label and the action taken. `gained` is a bitmask over the interesting units, meaning every unowned super, uber or legend appearing in any live pool, typically under 150 bits, held in a Python integer. Value is computed from `gained` with the weights, so it is not stored separately.

### 5.3 Processing order

All roll actions increase `k`, so nodes are processed in buckets of increasing `k`. Clock changes stay inside a bucket. Within a bucket, expand today's nodes, then tomorrow's, then any today labels newly created by a clock-back. A second round trip inside one bucket is always dominated, so the loop terminates in at most three passes.

### 5.4 Dominance

At the same node, label A dominates label B when A has used no more of every resource, made no more clock changes, and `gained_A` is a superset of `gained_B`. Superset dominance is exact: from the same state, any future path adds the same units to both, so the superset can never end lower. Value-only dominance is not exact and is used only in the beam fallback (5.10).

Optional bound pruning: if the current value plus the maximum obtainable from the remaining resources cannot beat the best known label at the same resource budget, drop the label. This is a safe bound because every roll yields at most one unit.

### 5.5 Legend rule enforcement

At any node where `legend_slot[k]` is true, the legend there is unowned and not yet gained, and a legend ticket remains, the only roll action allowed is the legend ticket. Clock changes remain allowed. When the "forbid 11-draw across legend slots" toggle is on, an 11-draw is rejected if any of its roll offsets, computed by simulating the draw including rerolls, is such a slot. When the toggle is off the draw is allowed and the slot is counted as wasted in metrics.

Legends also carry a weight of their own, default 5, so the planner has a reason to steer toward a legend slot on the other parity, not only to use one it happens to reach.

### 5.6 Reading the frontier

You may stop at any node, so every label anywhere is a candidate plan. Their union is reduced to a global frontier over resources and `gained`.

- Max value plan: among labels within your caps, the highest value; ties broken by lower scalarised cost at your exchange rate, then fewer clock changes, then fewer banner switches.
- Full coverage plan: targets are the unowned rare, super, uber and legend units in today's rare banners; which banners count is a checkbox column. Among labels whose `gained` covers the targets, the lowest scalarised cost. If none exists, report for one, two and three missing units the cheapest labels and list what each leaves out.
- Heatmaps: for every tickets value `t` up to your cap and cat food value `c` up to your cap, `best[t][c]` is the highest value among labels using at most `t` and `c`, with platinum and legend within their caps. Computed by placing frontier labels on the grid and taking a two-dimensional running maximum. A second map divides by `t / 30 + c / 2` for units per 11-draw equivalent.
- Knee points: along the value-versus-cost envelope, the points after which the marginal gain per 11-draw equivalent drops below a threshold, default 0.5.
- Pinned unit: filter labels whose `gained` includes a unit you name, then apply the max value or min cost reading.

### 5.7 Metrics per highlighted path

- Units gained by rarity and total weighted value.
- Resources used and cost in 11-draw equivalents.
- Value per 11-draw equivalent.
- Duplicate ubers received: uber-rarity results, including guaranteed and platinum ones, that were already owned or already gained on this path.
- Uber slots passed: offsets this path used as a rarity seed where some banner open at that moment, platinum included if a ticket remained, would have given a new uber, but the chosen action gave nothing new.
- Legend slots used and wasted.
- Clock changes and banner switches.

### 5.8 Size and speed

With 120 tickets, 15000 CF, 15 platinum and 3 legend tickets the horizon is about 500 steps. `last_rare` takes at most about 35 values, the clock two, the discount mask four. The reachable node count is far below the product because offsets advance in jumps of 2, 3, 21 or 22. Expected work is a few million label expansions, which is seconds in plain Python with integer bitmasks and tuples. The budget is 30 seconds at that scale. Above budget the beam fallback engages and the GUI shows a heuristic badge.

### 5.9 Fallbacks

- Beam: cap labels per node, default 50, keeping the highest value then lowest cost. Loses exactness, keeps the legend rule.
- Integer programme with OR-Tools CP-SAT: binary per node and action, flow conservation along offsets, one collected variable per unit, resource inequalities, and the legend rule as constraints. Exact, slower to set up, easy to add pinned units and switch limits. Kept in reserve.

### 5.10 Independent replay

Every plan shown is re-run through `replay` from the start state. The replay recomputes results, resources, legality and metrics. Any difference from what the search claimed fails the tests and shows a red banner in the GUI. This guards the search's bookkeeping with code that shares nothing with it except the primitives.

## 6. Plan output

A numbered table with columns: step, device date, action, banner, site position before the action such as 7B, expected result with rarity, whether it is new, and running totals of tickets, cat food, platinum, legend tickets and value. Every unit produced is listed, rares included, so that you can tick results off one by one and notice a divergence immediately. An 11-draw shows all 11 results in order. Ubers, legends and new units are highlighted distinctly from the rest. Clock changes are their own rows: "Set device date to 2026-09-14" and "Set device date back to 2026-09-13". A plan ends on today's date.

After each 11-draw and at the end, a bc.godfat.org link for the resulting state so you can cross-check against the site. Export as Markdown and CSV.

Divergence protocol printed with every plan: confirm each result against the expected column; on the first mismatch stop rolling; press Refresh to pick up a changed pool; re-enter your position from the site; re-plan. A mismatch almost always means a banner gained a unit, not that the seed moved.

## 7. GUI

Streamlit, run locally with `streamlit run app.py`.

Sidebar inputs:

- Plan date, default today.
- Tracks URL, or seed plus last cat id.
- Owned URL or `o=` string, with the decoded counts shown.
- Rare tickets available, cat food available, platinum tickets to use, legend tickets available.
- Weights: super 0.8, uber 1.0, legend 5, exclusive multiplier 3.0, wishlist file path.
- Exchange rate: tickets per 11-draw, default 30.
- Toggles: forbid 11-draw across legend slots, default on; allow repeated skips, default on; maximum clock changes, default 4; skip penalty, default 0.02 draw equivalents.
- Buttons: Fetch banners, Refresh, Plan.

Main area:

- Banner table, editable: name, dates, kind, rates, pool sizes, unowned units available with exclusives starred, and checkboxes for include, 11-draw offered, guaranteed (prefilled), 750 CF first draw, counts toward full coverage.
- Tabs: Max value plan, Full coverage plan, Heatmaps, Frontier and compare, Data and checks.
- Heatmaps in Plotly with hover showing value and units, and markers for the highlighted paths.
- Compare: pick up to four frontier labels for side-by-side metrics and action lists.
- Data and checks: parse self-test results, pool equality check, cache age, site version, and the assumption list from section 0 with its current settings.

## 8. Project layout

```text
Battle Cats Planner/
  PLAN.md                  this document
  README.md                install and run
  GUIDE.md                 every feature, in detail
  requirements.txt         requests, streamlit, pandas, plotly
  wishlist.txt             name or id, multiplier
  app.py                   Streamlit entry point
  bcplanner/
    prng.py                advance, retreat, seed stream
    owned.py               o= encode and decode
    scrape.py              fetch, parse, cache, validate
    model.py               Cat, Banner, pools, rates, legend slots
    sim.py                 precompute tables, primitives, replay
    search.py              label DP, frontier, readings, heatmap grids
    metrics.py             per-path metrics
    report.py              plan table, links, exports
    cli.py                 run without the GUI
  tests/
    test_prng.py
    test_owned.py
    test_scrape_fixtures.py
    test_sim_vs_site.py
    test_search_small.py   DP against brute force on toy banners
    test_replay.py
    fixtures/              saved site HTML
  data_cache/
```

Python 3.11. Four third-party packages. No database.

## 9. Testing

- Unit: generator forward and inverse over random seeds; owned decode against an encoder ported from the site; rarity bands at every boundary; reroll with a pool containing duplicates.
- Golden: the four site pages of 4.4 from fixtures, and optionally live.
- Search: toy banners with 3 to 5 units and a handful of resources, where a brute-force enumeration of all action sequences is feasible, must agree with the DP on the max value and the min cost for coverage. Property checks on generated instances: caps never exceeded, the legend rule never violated, the clock rules never violated, and replay agrees with the search for every frontier label.
- Performance: the 5.8 scenario completes within budget on your machine.
- Field: milestone M5.

## 10. Milestones

Each milestone has a deliverable you can look at and a check that has to pass before the next one starts.

1. M0, assumption check, about half a day. Fetch the platinum and legend Details pages and compare pools; read the legend rates; detect guaranteed flags and 11-draw availability for the live banners; decode an `o=` string you produce; check a date boundary. Deliverable: a findings note and an updated section 0.
2. M1, core and verification, about one day. `prng`, `model`, `sim`, and the golden tests. Check: the command line prints your page's table identical to the site, 100 rows, both tracks, both rerolls.
3. M2, data layer, about half a day. `scrape`, cache, master list, owned decode, banner discovery for today and tomorrow. Check: the banner table for the plan date, with the parse self-test green for every banner.
4. M3, search and command line, one to two days. `search`, readings, heatmap grids, metrics, replay. Check: toy-instance tests pass, the performance budget holds, and a real plan prints from the command line with its replay agreeing.
5. M4, GUI, about one day. Streamlit app, heatmaps, compare, export. Check: a full session from pasting URLs to an exported plan without touching code.
6. M5, field trial with you. Execute the first few actions of a real plan, compare every result with the expected column, and fix anything that diverges.

## 11. Risks and open questions

- The site's HTML changes. Fixtures and a loud parser error limit the damage; the fix is a parser update.
- A banner gains a unit on its launch day, reordering its uber slots. Steps on a banner that has not started yet are marked provisional, and Refresh is recommended before executing.
- The label frontier grows large on unusual inputs. The beam fallback bounds runtime at the cost of exactness and says so.
- Assumptions A1 to A8 in section 0, especially A5 on non-guaranteed 11-draws and A7 on step-up banners.
- Legend slots inside an allowed 11-draw are wasted by choice. The metric makes it visible.
- Time skipping is a game-side decision on your part. The tool only labels dates.
- Whether the in-game dupe immunity right after a guaranteed uber matches the site's model. The code says it does; M5 confirms it.

## 12. What a session looks like

1. Tick your owned units once on the site's cats page and copy the URL.
2. Open your tracks page on the site, confirm the last cat and copy the URL.
3. Start the app, paste both URLs, enter tickets, cat food, platinum count and legend tickets.
4. Press Fetch banners. Review the banner table, tick guaranteed and discount boxes, untick anything you will not roll on.
5. Press Plan. Read the max value plan and the coverage plan, look at the heatmap to decide how much to spend, and pin a unit if you want it guaranteed in the plan.
6. Export the plan. Follow it step by step, checking each result. Stop at the first mismatch and re-plan.

## 13. Build log and deviations from the plan

2026-09-13. Everything through M4 is built and tested; M5 (field trial) is yours.

- Verification beyond the plan: godfat's C seed seeker was compiled and, fed the ten observed rolls from your page, returned exactly your URL seed and the 21-steps-later value the model predicts. The PRNG matches the compiled C and a literal port of the Ruby on 200k seeds. The owned-units codec was verified against the live cats page.
- M0 findings: platinum and legend banners share an identical 134-uber list in the same order; the legend banner is 0/0/9500/500 with 13 legends; all four current rare banners are guaranteed 11-draws per the site's data (the collab included); two of them carry the 0.3% legend rate.
- Golden tests: seven saved pages reproduce cell for cell over all 100 rows and both tracks, including guaranteed ubers computed through rerolls.
- Search, deviation from 5.4: pure superset dominance was far too weak (over ten minutes on a small case) because equal-value labels that differ only in which super rares they hold are incomparable, and hundreds of them appear at one node. Two exact tightenings were added: `last rare` is merged to 0 whenever no live banner can produce a duplicate at that offset, and dominance compares values, charging the dominating label only for units it holds that the other lacks and that can still reappear within the window the other label's remaining resources can reach. That is still exact but still not enough on real banners, so a beam caps labels per (node, resource vector), default 6, keeping the highest values and, among ties, the labels whose units are least likely to reappear. The GUI shows "exact" or "heuristic (beam)". Widening the beam five-fold on the test cases did not change the best value. The exact mode (beam 0) matches brute-force enumeration on eight random toy instances.
- Performance: 30 tickets, 4 draws, 3 platinum, 1 legend against six banners with nothing owned runs in about 14 seconds.
- Report: every unit of every pull is listed, rares included, with the site position, a NEW flag, bold ubers and legends, and a bc.godfat.org cross-check link after each step, per your later request.
- Self-test on fetch: every banner page is simulated and compared with its own table before use.
- GUI: Streamlit, run with `.venv/Scripts/streamlit run app.py`. Offline mode uses the saved pages.

2026-09-14. Second round, from your feedback.

- Owned units are ticked inside the app: an icon grid sorted by rarity then banner, with filters, search and
  "mark all shown" buttons, replacing the site's cats page. Unit portraits come from bc.godfat.org's own
  `/extract/en/uni{id-1}_f00.png` files, keyed by the same ids as everything else, cached locally.
  Export is a text block `BCPLANNER-OWNED v1` with a game version tag (default 15.6), the site's compact code
  and one id/name line per unit. Import accepts that block, the site's URL or a bare code; if an id's name
  no longer matches the catalog, the unit is re-resolved by name and the import reports what it repaired.
- Banner names: each uber's wiki page (battlecats.miraheze.org) states its gacha event in the first
  sentence and its game ID in the infobox (site id minus one, checked). A banner is named by the event title
  most of its ubers share, shortened through a small alias list (The Almighties, Dragon Emperors, Summer Gals).
  Collabs with no event on the wiki fall back to a cleaned version of the site's blurb ("Survive! Mola Mola!").
- Heatmaps and the efficiency map are gone. The Options tab shows the best plan for no cat food, one
  11-draw, two, and so on (only rows that add something), and a with/without comparison for platinum tickets,
  each with icons of the new ubers and legends and the full step list behind an expander.
- Rare ticket, cat food, platinum ticket and legend ticket icons are the game's item art from the wiki,
  bundled in `bcplanner/assets`. Unit icons sit beside unit names in plans and options.
- UI simplified: the sidebar holds only the URL, resources and two buttons; weights, rules, search depth,
  offline mode and the game version live under Advanced. "Beam" is now "Search depth" with a plain
  explanation. Inputs and the owned list persist in `data_cache/settings.json`.

2026-09-14, third round.

- Plan tables condense consecutive single tickets on one banner into one entry ("2 single draws (rare
  tickets) on Summer Gals", step "20-21") with the results listed under it and one checkpoint after the
  group; runs of platinum or legend tickets condense the same way. Markdown and CSV exports follow.
- Priority units: a fourth full-screen picker (default super rares and rares) for units wanted as extra
  copies. They never enter the search. After a plan is chosen, `priority.py` re-examines each single
  ticket: if another banner open at that moment gives a ticked unit at the same offset and the whole plan
  replays identically otherwise (every later result, all resources, no unit lost), the banner is swapped.
  A toggle allows inserting a one-day clock change around such a roll. Re-routed rolls are noted in the
  table and wanted copies are marked ★ in violet. Tests cover "nothing else changes" and the no-skip case.
- Per-banner guaranteed and 750 CF first-draw checkboxes moved to a Banner options block in the sidebar,
  persisted per event id; the Banners tab keeps include / 11-draw offered / counts-for-coverage.
- An icon-size slider at the bottom of the sidebar scales unit portraits in every table and summary
  (table row heights follow it).

2026-09-14, fourth round.

- The 750 CF offer is once per plan, not once per banner: a single plan-level checkbox; the search state
  carries one "first draw done" bit and the first 11-draw on any banner costs 1 unit (750 CF).
- The owned and priority pickers run as Streamlit fragments, so ticking or filtering reruns only the grid,
  not the whole page. The grid widget keeps a stable key across your own ticks (it used to be re-created
  after every tick, which dropped a second tick made during the refresh); the key changes only after
  bulk buttons or an import, where the underlying data changes from outside the widget.
- The owned-list export is generated on demand with a button instead of on every rerun.

2026-09-14, fifth round.

- A 🔀 marker on the group row and the roll row whenever a single ticket was moved to another banner only
  for a wanted copy; the Markdown and CSV exports carry it too.
- Tabs are stateful (`st.tabs(..., key=...)`), so buttons no longer bounce the page back to the Plan tab;
  the export/import blocks are fragments as well. Column widths are fixed in pixels: the tick column is
  thin, the icon column is the icon plus 18 px; user drag-resizing still resets when a grid is rebuilt
  after a bulk change, which Streamlit does not let us keep.
- Icon size slider 32–128, default 64. Download button removed; exports are text only.
- The wanted (priority) list has its own export/import with the header `BCPLANNER-WANTED v1`, the same
  id/name format and the same repair-by-name import.

2026-09-14, sixth round.

- Pickers can group by *home* banner: the gacha set a unit belongs to whether or not it is running, from
  the unit's own wiki page (the same lookup that names banners). Units whose page names no event are
  "Regular pool"; event titles shared by fewer than three units are lumped as "Single-banner exclusives"
  (Staal, Trixi, Empress, ...); known sets use their alias (Dark Heroes, Summer Gals, Uberfest, ...).
  The lookup is a one-time button per unit set, about 2 s per unit, cached in data_cache/home_map.json
  and per unit under data_cache/wiki.
- The sidebar block is now titled "Guaranteed uber in the 11-draw?" with a caption pointing to the
  Banners tab's *include* column for leaving a banner out.

2026-09-14, seventh round: a provable Exact mode.

- The beam search is a heuristic and cannot certify its answer. Exact mode adds a relaxed upper bound
  (`bounds.py`): a small exact dynamic programme over (offset, tickets, cat-food units, platinum,
  legend tickets, discount bit) in which every unowned unit counts each time it appears, both days'
  banners are always open, legend-slot rules are dropped and a single may take either its normal or its
  reroll outcome. Every relaxation only adds value, so the bound is never below any real continuation
  (tested against the unbounded full search).
- `search_exact` runs Thorough (beam 30) for incumbents best[t][c], then a full search with no beam
  that discards a partial plan only when, for every spend (t', c') it could end at, its value plus
  min(bound for the extra spend, value of not-yet-gained units still in its window) cannot exceed the
  incumbent. Surviving labels are merged with the incumbents; `proven_optimal` is set when the full run
  completed. Six random toy instances match brute force; a small real instance matches the unbounded
  full search on the entire frontier.
- Coverage is proven the same way through `coverage_problem`, a copy in which only today's target
  units carry value (one point each); the cheapest label reaching all targets is the certified
  cheapest full-coverage plan.
- Timings on the saved banners, nothing owned: 15 tickets / 2 draws / 2 platinum / 1 legend: beam-6
  0.6 s, exact 24 s (proved the beam value 22.2 optimal). 20 tickets / 3 draws / 2 platinum / 1 legend:
  exact 8.5 min, proved the beam value 32.2 optimal. 30 tickets / 4 draws / 3 platinum / 1 legend: exact
  did not finish in 30 min; and here beam 6 found 39.0 while beams 12 and 30 found 39.8 (52 s and 283 s
  standalone). The Normal default was therefore raised from 6 to 12. This is the first case where the
  narrow beam lost value, and it is recorded here rather than papered over.
- The GUI's Search depth reads Normal / Thorough / Exact; the plan caption says "proven optimal" when
  it is. The CLI flag is `--exact`.

2026-09-14, eighth round: Tracks tab.

- `tracks_view.py` renders the site's two-track table for any loaded banner from the sidebar seed,
  reusing `sim.site_table`. Colours and rules are copied from the site's tacit.css and cat.rb: cells
  take the score band of their position (rare white, fest-only super yellow, super gold, fest-only uber
  salmon, uber red, fest-only legend slate blue, legend violet); owned cats are light cyan with a 10%
  stripe of the original colour on the left; a name search paints matches lime like the site's Find;
  single-banner exclusives (from the home map) are aqua.
- Overlay toggle: the chosen plan (most value, full coverage, or any option row) is drawn over the
  table exactly as the site draws picked positions: 20% black for single, platinum and legend pulls,
  50% black for the rolls of an 11-draw and its guaranteed cell, stripes on the position after the last
  roll, and a badge with the step number (* when the roll is on another banner, P/L for platinum and
  legend tickets, G for the guaranteed uber). Positions consumed on other banners still show on the
  selected banner's table because the seed stream is shared.

2026-09-14, ninth round: Tracks refinements and metric fixes.

- Colour key moved below the table and laid out as a vertical list; guaranteed cells are white (they are
  always ubers); the plan path is shaded green (28% and 50%) with green stripes for the next position;
  the name-highlight box was removed; the default row count is the plan's rows plus 20.
- "Follow the plan's banners": positions spent on another banner show that banner's unit with an
  "on <banner>" tag, and a margin column notes banner changes (⇄) and track changes (↕, dupe reroll or
  after a guaranteed uber), without changing the grid.
- Legend-slot metric reworked: "used" counts every position where the plan obtained a legend (ticket
  or a banner's own legend rate); "passed" counts legend-ticket slots with an unowned legend that the plan
  spent on something else, whether or not legend tickets were entered (it used to stay 0/0 with no
  tickets). Plan rows at such positions now say which legend a ticket would give there.
- Banner changes within a day were already free of cost everywhere in the search; the caption now says
  "banner changes (free; only clock changes are limited)" to avoid the impression of a penalty.
- Plan tab: toggle to list new units in three columns by rarity instead of one row.
- Tracks margins: a banner or track note is shown only on the side of the track it applies to (A left,
  B right) and the margin cells have no borders. `app.py` now reloads the `bcplanner` modules when any
  of them changes on disk (the running app used to keep the old code until restarted).

2026-09-14, tenth round: unit coverage and home banners.

- Home banners: the wiki alias table had a catch-all "Busters" entry that turned *Colossus Busters* and
  *Red Busters* into "Busters". Every "... Busters" title now keeps its own name in title case, and
  "RoyalFest" and "Best of the Best" are recognised. The app reloads `data_cache/home_map.json`
  whenever it changes on disk, and a snapshot ships in `bcplanner/data/home_map.json` for fresh installs.
- Wiki parser (`wiki.classify`): the old regex only knew "[[X (Gacha Event)|...]]" links, so every
  collab unit (Evangelion, Street Fighter, Merc Storia, Fate, Madoka, Miku, Metal Slug, Demon Slayer …)
  came back "Unknown". Now: a unit is a gacha unit if its opening paragraph mentions the Rare (Cat)
  Capsule or the page carries [[Category:Gacha Cats]]; the home is the first event link in the opening
  paragraph, preferring the one right after the capsule mention; "[[X Collaboration Event]]" becomes
  "X collab"; sentences about The Battle Cats POP! (3DS) or Unite! (Switch) are ignored (the Crazed
  Cats come from the capsule there but not on phones); later sections are never searched (a regular
  super's page mentions any banner it was featured in). The cache keeps each page's opening paragraph,
  so a parser change is a re-parse, not a re-fetch.
- Result over the whole English cat list (593 gacha-rarity units after dropping 19 placeholder or
  Japanese-only names): 423 with a home event, 54 regular pool (29 supers, 25 rares), 116 not from the
  capsule (stage rewards such as the Crazed Cats and 84 rares; the only ubers are Evangelist Cat and
  Giga-Nyan Rex), 50 home groups, no unit of any saved banner pool marked non-gacha. Units the wiki
  says never came from the capsule are hidden from the every-unit picker unless a running banner
  lists them.

2026-09-14, eleventh round: owned units from Cat Guide screenshots (`bcplanner/guideimport.py`).

- What the screenshots showed (iPhone, 2556 × 1179): one rarity tab per page, a 6 × 4 grid of framed
  cells, grey "?" for units not owned, a star badge in the bottom-right corner of favourited units.
  The guide's order is *not* the unit number: on the Super Rare tab Valentine's Neneko (590) came
  before Cat Base Mini (145), Mummy Sumo (774) before the Brainwashed series (630–695), which is listed
  as a block; and collab units you do not own are not listed at all (the Legendary tab showed 17 cells
  for 20 legends: Akuma, Black Zeus and Moonshade Kaworu were missing). So "find the ? cells and take
  the complement" cannot name the missing units without the game's own ordering table and knowledge
  of which collab units are hidden.
- Instead each icon cell is identified by matching its picture against the icon library the planner
  already caches: the guide draws the same file the site serves (`uni###_f00.png`), showing the
  100 × 76 interior at (14, 26)–(114, 102) of the 128 × 128 file; normalised cross-correlation on
  grayscale, a coarse pass over all 724 icons then a fine pass with ±2 px shifts over the 15 best,
  the badge corner masked, and a full-resolution second look when the top two are within 0.15. Cells
  are found from the frames (pure black, long straight runs, so line art never confuses them), with
  all sizes relative to the screenshot height. Grey "?" cells have no white pixels at all.
- Result on the five sample pages: 99 of 99 cells found, 72 owned units read in 1.4 s, scores 0.69–0.97
  with margins ≥ 0.29 except the near-identical pairs (Summerluga vs Nekoluga: the flower; Brainwashed
  vs Crazed Cat: the belly hatching under the badge). Those are marked "check" and shown side by side
  in the review table; a unit matched twice on one page is resolved to its lookalike. The import only
  ever adds units. Synthetic-page tests cover frame detection, "?" cells, badges and a smaller phone.

2026-09-14, twelfth round: the whole Cat Guide (34 pages, every tab) and the review flow.

- Failure points found on the full set and fixed: (1) cells were found by pairing global frame lines,
  so a long black stroke inside an icon (the afro of a Special cat) or the black tab label shifted or
  merged rows and gave column-6 cells a neighbour's right edge; cells are now found from each frame's
  own left and right edges (vertical black runs one cell tall, one cell apart, joined by black top and
  bottom edges), which gave 745 of 745 cells at a uniform 190 × 147 px. (2) Ancient Eggs share one
  egg picture and the site serves no icon for them: an egg template ships in `bcplanner/assets`, egg
  cells are numbered in reading order per tab and offered as a guess (all 26 eggs matched at 0.89–1.0).
  (3) Icons that differ only in colour (Gold vs Metal Cat, Yuki vs Redhead Yuki) tied on grayscale:
  near ties are settled by the mean colour of the saturated pixels, with the yellow star badge masked
  out (it had made every badged cell look golden). (4) Cells scoring under 0.6 are "unknown" instead
  of a wrong pick; real matches score 0.69 or more.
- Result: 34 pages in 7 s, 583 owned units (10 normal, 120 special, 140 rare, 84 super, 223 uber,
  6 legend), 165 "?" cells, no unknown cells; only Crazed vs Brainwashed Cat and Summerluga vs
  Nekoluga still need a human eye. Only two catalog units never appeared on any page.
- GUI: the Owned tab's import now shows a confidence table plus a "What unit is this?" block for
  every doubtful cell (its picture, the candidates preselected, Skip, or any other unit). The Owned
  picker can show rare, special and normal units too, keeps ticked non-gacha units visible, and the
  app reloads owned/priority lists when `settings.json` changes on disk (so a script or another
  window can write them). The full list from the 34 pages is in `owned_from_cat_guide.txt` and was
  written to `data_cache/settings.json`.

2026-09-14, thirteenth round: duplicate values, wanted-copy counts, uber priority and platinum table.

- Value of a repeat (Advanced, "A repeat is worth"): `Problem.dupe_values` per rarity, default 0.
  `Problem.gain(cat_id, rarity, gained)` returns the first-copy value or the duplicate value; used by
  the search, the replay and the exact-mode bound (which takes the larger of the two per roll, so it
  stays an upper bound; the window cap adds `dupe_max` per remaining roll and the value-step cut
  includes the duplicate values). This is the "penalty for missing an uber slot": with a repeat uber
  worth 0.2, a plan that turns an uber slot into a super rare (an Uberfest-only slot spent on a normal
  banner) or passes one for a dupe elsewhere loses that much; the coverage copy keeps duplicates at 0.
  Brute-force and exact-mode tests were extended with duplicate values (74 tests).
- Plan header lists wanted copies once with "×n" instead of repeating the unit.
- New tab "Uber priority" (the old "Priority units" tab is now "Wanted copies"): tick the ubers you do
  not own that matter most; owned ubers are hidden; export/import with header BCPLANNER-UBERS v1.
  Options tab: "Where a platinum ticket could go" lists every position up to a little past the plan's
  end with the uber a platinum ticket gives there, ★ for priority ubers and ✓ for new ones (sorted to
  the top), and the plan step that starts at that position. Advanced "Uber priority multiplier"
  (default 1 = sorting only) lets the plan itself favour those ubers like the wishlist does.

2026-09-14, fourteenth round: opportunity cost of uber slots gone past on the other track.

- His model: the path visits one track; every uber slot on the other track it moves beyond is gone
  for good, and even a repeat would have been worth something, so passing one is a real loss:
  "fairly negative for a regular slot, mild for an Uberfest-only slot". `Problem.pass_penalties`
  (defaults uber 0.5, uber_fest 0.1; Advanced "Going past an uber slot on the other track costs";
  CLI `--pass-uber/--pass-fest`). A step from offset k0 to k1 passes every position in [k0, k1)
  no roll landed on: the other track's positions (one per plain roll, ten per guaranteed 11-draw)
  plus the position a dupe reroll jumps over. The band is the site's: 9470+ = uber on every banner,
  9070–9469 = Uberfest/Epicfest only. Charged identically in the search and the replay (Step.passed,
  Step.penalty; metrics uber_slots_skipped / fest_slots_skipped / pass_penalty; plan rows note
  "passes uber slot 7B"). The exact-mode bound ignores the penalties, which keeps it an upper bound.
  Consequence by design: a plan may leave tickets unspent rather than roll past ubers it cannot reach.
  Brute-force tests run with the default penalties and with none (76 tests). The coverage copy
  keeps penalties at 0.
- Plan header: in column view the wanted copies get their own column, listed once with ×n.
- Defaults set to his chosen values (2026-09-14): weights super 0.8 / uber 1 / legend 8; a repeat super
  0.05, uber 0.2, legend 0; passing a regular uber slot 0.8, an Uberfest-only slot 0.2; uber priority
  multiplier 1.5; wishlist multiplier 3; 30 tickets per 11-draw. His own settings file already held
  them; the defaults matter for a fresh install, the CLI and the stateless deployment.

2026-09-14, fifteenth round: when to stop spending and save for the next banner (`bcplanner/future.py`).

- Why the planner could not tell: its world ended tomorrow, so any roll with positive value was taken.
  The key fact: the seed only moves when you roll, so the positions a plan leaves unused are exactly
  the positions the next banner will use, and their rarity bands are known now. Only the units are
  unknown.
- `FutureValue.value(k, tickets, cf, plats, legends)` = expected value of arriving at position k with
  those resources unspent. Layer 1, flat: "a future 11-draw is worth V" (per ticket V/30). Layer 2,
  seed: each position ahead is scored by its band on a typical (non-fest) banner times the chance a
  unit of that rarity is new to you (estimated as the unowned share of the platinum pool / today's
  super rares / the legend list, editable in Advanced as "Next uber/super/legend new (%)"), times the
  weights, plus the repeat value otherwise; a future 11-draw ends with a guaranteed uber; rolls later
  pay the same pass penalties as rolls now; the best way to spend the leftovers on that virtual
  banner is a memoised dynamic programme over (position, tickets, cf, plats, legends); the whole
  estimate is scaled by a confidence factor (default 0.8).
- Choice of plan: `SearchResult.best_total` maximises value now + future value over every explored
  label (every prefix of every plan is a candidate, so stopping early is always available; the beam
  keeps labels per node, so every end position is represented). The Plan tab shows what is kept and
  why ("the next N positions on your track hold u uber, l legend and s super slots"), and an expander
  with the all-in plan for comparison when it differs; each Options row shows "later +x → total".
  Coverage plans ignore the future. Tests: flat arithmetic, band scoring, monotonicity, and that a
  huge future value makes the best plan keep everything (79 tests).
- What his own numbers say (19% of platinum-pool ubers unowned, pass penalty 0.8): a typical next
  banner is barely worth rolling, so spending now wins on today's banners; only the last two dozen
  tickets or so are worth keeping. Saving for a specific good banner means raising "Next uber new (%)"
  to that banner's share. Layer 3 (the site's published schedule, exact) is the next step.
- Metric fix (same day): "uber slots passed" had counted a still-unused platinum ticket as a missed
  alternative at every position whose platinum uber was unowned, so a plan holding its platinum
  ticket showed 9–17 "passed" slots. It now counts single tickets rolled where another open rare
  banner had a new uber or legend at that position (0 on the current plans: the search would have
  switched), and separately rolls inside an 11-draw with a new uber on another banner (no per-roll
  choice exists there). "Dupe ubers" are uber slots where no open banner had a new uber; they are
  taken because a repeat is worth 0.2 and the only alternative is to stop rolling.
- Floor and steering value (same day). His Tracks screenshot showed 23 single tickets rolled through a
  run of rares and repeats to place the second 11-draw's guaranteed uber on Seabreeze Coppermine
  (+1.6). The seed estimate priced those kept tickets at about 0.02 each, because from that position
  the next banner faces the same run of rare slots (rarity bands are fixed by the seed), so crossing
  it now looked free. His view of a kept ticket is different: on a future guaranteed banner every
  ticket rolled before the 11-draw moves its guaranteed slot one position, so kept tickets mean more
  candidate ubers to choose from. Two additions: (1) `selection()` adds that steering value, S kept
  guaranteed draws or platinum pulls times (new − repeat value) × (1 − p) × (1 − (1 − p)^(t/S)); (2) the
  flat number ("a future 11-draw, or 30 tickets, is worth at least", default 2) is now a floor under
  the seed estimate, so kept tickets are never priced below it. With the floor his plan stops after
  Gaia the Creator: 39 tickets and the platinum ticket spent, 44 tickets and 3000 CF kept (worth 6.9
  by the floor), total 15.1 against 11.25 for spending everything.

2026-09-15, sixteenth round: the banner list on an arbitrary date.

- With the plan date set to 2026-06-10 the list showed "Xmas Gals" twice. Cause 1: the game schedules
  the same gacha in back-to-back windows (2026-06-08_974 then 2026-06-11_974) and the app lists every
  window live today or tomorrow. `session.merge_repeats` now folds touching windows of one gacha with
  identical pools, rates and guaranteed flag into one banner spanning both. Cause 2: gacha 974 ("A
  chance to earn special units!") is a seasonal re-run holding two Halloween gals and three Xmas gals;
  the title vote took the majority set. `banner_title` now names every set holding at least a third of
  the ubers when no set has 70%, so it reads "Xmas Gals + Halloween Gals". The aliases "Halloweens" and
  "Valentines" became "Halloween Gals" and "Valentine Gals" (home maps regenerated). The dates are the
  site's: seasonal units do get re-run banners in June.
- On that date the plan spent nothing. That is the model's answer, not a bug: with the current seed
  the best spend on those banners earned 0.9 while the floor prices the held resources at 9.5. The
  Plan tab now says so explicitly and points at the two settings that change it.

2026-09-15, seventeenth round: less text.

- The next-banner block under Advanced is one toggle ("Weigh what you keep for the next banner") and
  one slider ("Outlook for the next banner", 0–100). `app.future_model` derives everything else: the
  chance that a next-banner unit is new starts from the unowned share of the shared pools and is
  pulled towards 0 (left) or 1 (right); the floor under the value of kept resources runs from 1 to 3
  per 11-draw's worth (2 at the middle); confidence stays 0.8. The flat mode and the three
  percentage inputs are gone from the screen (the model keeps them).
- Plan tab: titles "Max value" and "Spend everything"; the kept line is one line; the caption shows
  only counts that are non-zero; no Markdown/CSV downloads; when nothing on today's banners is
  missing the coverage block says so in one line instead of an empty heading; a merged repeat window
  is folded silently. Checks tab: one caption plus any load notes. Advanced captions shortened.

2026-09-15, eighteenth round: ticket cost, legends without rush, and the Exact-mode hang.

- The "hang": his saved depth was Exact. Its proof phase (bounded full search) has no progress
  callbacks and on an 83-ticket budget runs for hours, so the page dimmed and sat there. Two fixes:
  when the Thorough pass dropped no label the run was already exact, so `search_exact` returns it at
  once as proven (his case: 0.2 s); otherwise the proof phase has a deadline (120 s) checked in the
  search loop and inside the bound itself (which then returns infinity, i.e. stops pruning), after
  which the Thorough result is kept and the caption says "exact proof stopped after 120 s".
- Every rare ticket spent costs 0.02 value (`Problem.ticket_cost`, Advanced "Each rare ticket
  costs"), in the search, the replay and the future stage; coverage keeps it at 0. It is a small
  brake on spending that works even with the next-banner weighing off.
- Legends: his rule is "never miss a legend slot, but no rush to reach it". Two changes: legend slots
  (score 9970+) are their own pass band with a penalty of 5 by default (going past one on the other
  track is nearly as bad as losing a legend), and in the future stage a legend slot is worth the
  legend an open banner still holds there when that banner runs beyond the plan's two days
  (`FutureValue.legend_now`), so the plan is not forced to burn uber slots to reach it today; it can
  stop before and collect it in a later plan. In a direct choice the legend still wins (weight 8).

2026-09-15, nineteenth round: "there has to be a way", and a whole-program review.

- His Options screenshot showed the two-draw row with the same two new units as the one-draw row and
  asked how a second guaranteed uber could miss. Reproduced: before the ticket cost the search did
  place both guaranteed slots on new ubers (Tomoe at 79AG, Coppermine at 105BG) but needed all 83
  tickets; with 0.02 per ticket and the kept-ticket floor, walking 42 more tickets for one more uber
  scores lower, so the row keeps 41 tickets and its second guaranteed lands on a repeat. Options rows
  are now chosen by value now plus what is kept (the same rule as the Plan tab) and each row also shows
  "or, with N tickets: k new — …" from `options.most_new_tops`, the plan with the most new ubers at that
  spend, with its own steps, so the trade is visible instead of hidden.
- Sidebar: Uberfest and Epicfest banners can no longer be ticked as guaranteed (section 0 rule).
- Review against section 0 and the later rounds: every rule is enforced in the search and mirrored in
  the replay (no 150 CF singles; 11-draws at 1500 or one 750; legend tickets only on a new legend and
  mandatory when possible; shared uber pool; rares 0 / supers 0.8 / legends 8 / wishlist multiplier;
  30 tickets per draw; one-day clock changes capped at 4; 11-draw-over-legend toggle; per-banner
  guaranteed with fests locked off; repeat values, pass penalties, ticket cost and the next-banner
  value all in search, replay and, as relaxations, the bound; coverage copy keeps only the target
  values; priority units re-route singles only when the value does not drop). Timings on his budget:
  search 0.2 s (Thorough drops nothing, so Exact is proven at once), whole plan pipeline 0.3 s,
  34 Cat Guide pages 7 s, wiki lookups cached. Readings still compute the envelope, frontier and
  heatmap for the CLI; the GUI no longer shows them.
2026-09-15, twentieth round: "there are definitely closer Coppermines on guarantee".

- He was right. Enumerating every 11-draw start on the Summer banner from his seed: Jungle Gourmet Tomoe
  is the guaranteed uber at 14BG after three singles (draw from 4A), Seabreeze Coppermine at 22AG (the
  plan's own choice) and again at 35AG ten singles after the Tomoe draw. Both new ubers cost 13 tickets
  and the two draws, not 83. The search saw all of it (nothing truncated, Exact proven in 0.2 s) and
  still scored that plan at 0.68 against 2.53 for rolling through Mola King repeats to Gaia: the path
  to both guaranteed cells goes past 23B and 36A, uber slots on the other track that hold Mola King on
  every open banner, and the pass penalty charged the flat 0.8 for each of them, more than Tomoe is worth.
- Fix (`Problem.pass_cost`): a passed uber slot costs the band penalty only when a banner open today or
  tomorrow would give a new uber or legend there (not owned, not gained earlier in the plan, so a unit
  the plan already took is a repeat when passed later); when every open banner would only repeat an
  uber the slot costs that repeat's value; a fest-only band with no fest banner open costs nothing. Same
  rule in search (the penalty now takes the gained mask), replay (`Step.passed` carries "new" / "repeat",
  plan rows say "passes uber slot 23B (repeat)"), and the next-banner DP (band penalty weighted by the
  chance a next-banner uber is new, repeat value otherwise). The bound still ignores penalties, so it
  stays an upper bound. His "Spend everything" plan is now Tomoe at 14BG, Gaia at 41A and Coppermine at
  58AG for 36 tickets (value 3.5, three new); the 13-ticket two-uber plan scores 1.83 and sits in the
  Options rows as "1 eleven-draw … or, with 30 tickets: 2 new".
- Options rows are now one plan per exact cat-food level (0, 1 draw, 2 draws), best by total; the
  round-19 rule skipped every level whose total fell below the previous one, which under the kept-ticket
  floor collapsed the tab to the "Tickets only" row.
- Still open, on purpose: with his legend weight lowered to 2 and the outlook slider at 47, the floor
  values a future 11-draw's worth of tickets at 1.94, so "Max value" keeps everything (9.25 against 6.5 to
  7.9 for spending). The floor runs 1 to 3 per draw's worth across the slider; if the pessimistic end
  should mean "spend now", it needs to start at 0. His call.
- 89 tests (two new: the band penalty applies only while the uber there is new; replay marks repeats
  and agrees with the search when every uber is owned).

2026-09-16, twenty-first round: Options rows for every draw count, all plans on the tracks, 378,322 partial plans.

- Options rows: with a discounted first draw the cat-food amounts a plan can spend are 0, 1, 3, 5 units,
  but the rows were built for 0, 1, 2, 4, so the two- and three-draw rows vanished ("on current run there
  is nothing"). Rows now come from the amounts the candidate plans actually spend, one row per amount,
  titled by the number of 11-draws ("3 11-draws (3750 CF)"). Nothing is skipped any more.
- Tracks tab: the "Plan to overlay" list now holds every plan the other tabs show: Max value, Spend
  everything, Every missing unit on today's banners (the cheapest full-coverage plan), All but 1/2/3
  missing unit(s), every Options row and each row's "most new ubers" alternative. A stale selection
  from an earlier Plan press falls back to the first entry.
- The 378,322 partial plans: his run had a plan date whose next day adds banners (2026-09-17: three
  banners end that day, three start on the 18th). Then every label exists on both days and at up to
  five clock-change counts, and the beam is full at every position: 419,609 labels, 89 s at Thorough.
  Three changes to `search.py`, all exact (brute-force suites unchanged, 91 tests):
  1. Clock changes are folded into the roll that needs them (`other_day`): a roll on a banner only the
     other day has is created with the change as its parent; there are no standalone clock labels, and
     a change to tomorrow is only made when the plan can still come back within the cap.
  2. The beam groups labels by spend only (`BEAM_SKIPS = "none"`): plans that changed the date and plans
     that did not compete for the same slots (fewer clock changes wins ties). Same best value on the
     2026-09-17 case with 45 % fewer labels.
  3. Labels at a node are indexed by resource vector, so a dominance check only visits groups whose
     resources compare (2.5x faster inserts).
  Measured on the 2026-09-17 case, uncontended: Thorough 22.6 s / 230,681 labels (was 88.6 s / 419,609),
  Normal 6.7 s / 104,680; the 2026-09-16 case stays at 0.1 s / 5,358. Best value identical (12.91).
  What is left is inherent: the beam keeps up to 12 or 30 alternative partial plans per position and
  spend, on both days. The two remaining levers are the beam width and the clock-change cap (4 → 2
  halves the day-change states); an upper-bound prune inside the beam run was not added because the
  relaxed bound is loose on 40-unit cases (Exact mode shows it).
- README: the depth help mentions the folded day changes; Options caption says one row per draw count.

2026-09-16, twenty-second round: new rares count.

- Rule change (section 0): a new rare is worth as much as a new super rare; a repeat rare is worth
  nothing. The GUI and CLI tie the rare weight to the "New super" input (its help says so), so there is
  no new control; `DEFAULT_WEIGHTS["rare"]` is 0.8. Unowned rares are now valued units in the search,
  the replay, the bound (which takes its values from the same unit table, so it stays an upper bound),
  the coverage targets and the next-banner estimate (`estimate_p_new_from` reports the unowned share of
  the rares on today's banners; `FutureValue.expected` no longer zeroes the rare band). Plan headers
  and Options rows show "New rares" only when a plan gets one; the Banners tab's unowned column and
  the Owned picker caption no longer assume rares are owned.
- Effect today: none. He owns all 25 rares on the three open banners (22 unowned rares in the catalog
  are collab rares not running now), so the plan, the label count and the best value are identical
  with the rare weight at 0 or 0.8. It matters on collab banners with new rares.
- 92 tests (new: a new rare is worth the super weight, a repeat rare nothing, the estimate has a rare
  share).

2026-09-16, twenty-third round: legend tickets only as a stand-in.

- His rule (section 0, refined): a legend ticket may be used at a slot only when the plan must cross
  that slot anyway on its way to something better, the legend there is new, and every banner open
  today or tomorrow gives a repeat uber at that slot; if any open banner gives a new uber there, the
  rare ticket takes the uber and the legend ticket stays. Never spent just to grab a legend (a legend
  slot that is not crossed stays on the seed for later). Platinum tickets keep their freedom (his
  "*legend" correction).
- Implementation: `Problem.repeats_everywhere(k, gained)` (memoised per offset: every open rare banner
  gives an uber or legend at k that is owned or already gained), `legend_allowed` = new legend there
  and repeats everywhere, `legend_mandatory` and the 11-draw-over-legend-slot block use it. "Must be
  crossed on the way to something better" is `Label.pending`: set by a legend ticket, cleared by any
  later roll (single, 11-draw, platinum) that gains a new unit; a pending label is not a valid end of
  a plan and counts as a resource in dominance (a plan without the obligation dominates). The replay
  mirrors it: a legend ticket where the rule forbids it, or a plan whose last legend ticket is not
  followed by a new gain, is flagged; the brute-force tests treat that last flag as "unfinished"
  rather than illegal. `Problem.legend_substitute_only` (default on) keeps the old rule available.
- Effect on his plan (83 tickets, 3750 CF, 1 platinum, 4 legend tickets): Max value now takes Tomoe at
  14BG, a platinum Balaluga at 19A, a legend ticket at 36A (Mighty Kristul Muu, a Mola King repeat on
  every open banner) on the way to Gaia at 41A, total 13.4. Spend everything uses three legend tickets
  at 23B, 81B and 115B, all on repeat-uber slots the plan crosses, and rolls Tomoe at 118B with a rare
  ticket instead of a fourth legend ticket, since a new uber sits there.
- 93 tests.

2026-09-16, twenty-fourth round: plans as copy-pastable text.

- `report.plan_text(problem, replay, names, banner_names, title, keep)`: one numbered line per action
  group in his requested shape, "11-draw on Summer Gals [4A-14BG]. Receives Rocker Cat, ..., Jungle
  Gourmet Tomoe* (guaranteed)." and "Pull 7x on Survive! Mola Mola! collab [26A-32A]. Receives ...",
  platinum / legend tickets and date changes on their own lines, a header with the spend and value, a
  footer "Stop at 42A. Left: ... Kept for the next banner: about +7.4." and "* = new to you". Groups
  come from the same `_grouped_steps` the table uses, so the two views always agree.
- GUI: every plan table (`plan_table`) is now a Table / Text tab pair, so the Plan tab's plans, every
  Options row and its "most new ubers" alternative, the coverage plan, near misses and the pinned-unit
  plan all carry their own text with Streamlit's copy button (his "do this for each plan option").
- 94 tests (the text lists every group and every unit, one star per new unit).

2026-09-28, twenty-fifth round: "Could not load banners: Read timed out".

- The site was up (home page 0.4 s) but slow to build banner pages: 30.6 s for a tracks page, 67.9 s
  for a details page, against a 30 s read timeout; every saved page was 12 days old, so all were
  refetched. Fixes in `scrape.py` / `session.py`: timeouts (15 s connect, 180 s read), one retry on a
  timeout, dropped connection or 5xx; when the site still fails and a saved copy exists, the copy is
  used and a note says how old it is (the app shows a warning, details in Checks); a started event's
  details page is kept for 7 days instead of 24 h (its pools and rates do not change, and the page is
  expensive for the site); banner pages and the cat list load three at a time with a progress bar
  instead of a bare spinner. 95 tests (fallback to a saved copy, error when there is none).

2026-09-28, twenty-sixth round: other computers, and a short README.

- Portability check: no machine-specific paths in the code; dependencies need Python 3.10+
  (streamlit 1.63 needs 3.10, the pandas/numpy versions on his 3.11 need 3.11, pip picks older ones on
  3.10). The one trap was `.venv`: copied to another PC it points at his Python install. `run.bat` and
  `run.sh` now run the venv's python once and rebuild `.venv` when it fails ("No Python at ..."), try
  any Python 3 when 3.11 is missing, and say "needs Python 3.10 or newer and an internet connection"
  when pip fails. `.gitignore` keeps PLAN.md (its `plan*.md` rule matched PLAN.md on Windows).
- README.md is now a one-screen page of run commands (launchers, by hand on Windows and macOS/Linux,
  tests, copying to another computer); the full feature guide moved to GUIDE.md.

2026-10-27, twenty-eighth round: one app, named Wayfinder, with a Rare / Normal switch.

- The normal-capsule planner (built 2026-10-05 in a separate "Normal Seed Planner" folder) now lives here
  as the package `nsplanner`: bc-normal-seed-tracking's banners and roll rules (checked cell by cell
  against the site's own code), an exact grid search for the most blue orbs (Cat Capsule power-ups),
  Li'l Axe Cats and the Dark Catseye rule, the icon view, and its CLI (`python -m nsplanner`).
- app.py: page and sidebar title "Wayfinder"; a "Planner" radio (Rare / Normal) under it, saved with the
  other settings. Normal renders `nsplanner.ui.render` (its own sidebar inputs with "n_" keys, saved in
  data_cache/normal_settings.json, Pulls and Tracks tabs) and stops before the rare planner runs.
  The module reload helper covers both packages.
- Grid search tie-break: states also carry the last pull's capsule, and a capsule switch costs 1e-7,
  so equally good plans with fewer switches win (300 cat / 30 lucky: 66 operations instead of 82; the
  scores are unchanged).
- Tests: the normal planner's suite is here as test_normal_*.py with fixtures in tests/fixtures/normal;
  134 tests in all.

2026-10-27, twenty-ninth round: stop part-way and save progress (Normal planner).

- The Pulls list is a small Streamlit component (nsplanner/frontend/index.html, protocol v1, no build
  step) showing the same icon rows; clicking a pull, or a row number, returns its index. Single pulls
  can be stopped after any one; a 10x pull only after its last roll (data-stop). The chosen pull is
  marked STOP and everything after it fades.
- The sidebar then shows "Stopped after pull k of n": the last cell and the next one, what was gained so
  far, tickets left, the seed there and a tracker link (report.progress_after). "Save progress here"
  writes that URL and the remaining tickets into the inputs, saves them and re-plans from that point.
- Tests: from the saved seed and last result the rest of the plan comes out identical; every pull is
  numbered in order and 10x pulls stop at their end. 136 tests.

- Owned/priority pickers: the scope selectbox became a toggle, **Every gacha unit in the game**, on by
  default (off = today's banners and the platinum pool). Seasonal collab units such as the six Nenekos
  were always in the catalog; the old default scope hid them.
- Value, for the record: value = Σ rarity weight of NEW units (super 0.8, uber 1, legend 5, rare 0,
  wishlist × multiplier). Blind-draw baseline for the saved budget (83 tickets, 3000 CF, 1 platinum),
  expected new value with diminishing returns: 22.3 owning nothing, 8.1 owning every super; the seeded
  plan at Normal depth gives 37.0 and 13.0. A blind guaranteed 11-draw is worth 2.9–3.5 owning nothing
  and 1.0–1.6 owning the supers, so the planner often takes uber slots with singles and leaves the
  11-draw its guaranteed uber only.

2026-10-27, thirtieth round: improvement factor, an optimality check, and inputs lost on a planner switch.

- Normal: improvement = (blue orbs ÷ cat tickets spent, Catseye pulls included) ÷ 9/19, the long-run blue-orb
  share of pulling the Cat Capsule straight (a re-roll picks evenly among the other 18 units, so the share is
  unchanged; 200,000 simulated straight pulls gave 0.4755). The same line also gives the straight result from
  this seed. His run (300 cat, 30 lucky, dark 10): 168 orbs, 0.560 per cat ticket, ×1.18; 157 straight from
  this seed (0.523); 13 cat tickets go on Catseye pulls for the 3 Dark Catseyes.
- Rare: improvement = new-unit value of the plan ÷ the expected new-unit value of the same spend pulled straight:
  tickets and 11-draws on the one banner open today that does best that way (guaranteed draws: ordinary rolls,
  then one uber from the pool), platinum and legend tickets as they come; a unit counts once
  (value × chance of at least one copy). Within 0.3% of 1,500 simulated seeds (repeat-rare re-rolls, left out,
  add a little). Shown under every plan header, on each Options row and in the copyable text.
- Optimality: tests/normal_reference.py is an independent exact solver sharing only the roll simulation (its
  own state space with raw last results, no reachability window, the Dark Catseye penalty scored from the end
  state). It agrees with the planner on his run (174 = 168 orbs + 6 Li'l Axe Cats, 329 pulls), 40 random small
  cases, 6 large ones (300-500 cat, 30-60 lucky) and 6 with all six capsules open. Choice codes now leave 64 key
  slots per position (7 × 7 with six capsules would have overflowed 32; a step is at most 22, so int16 holds).
- Bug: Streamlit forgets the value of a widget a run does not draw, so after a visit to the Normal planner the
  rare inputs came back as zeros and the mode switch saved them (and the other way round, empty normal
  inputs once Plan was pressed). Every saved input of both planners is now re-assigned at the start of each run
  (app.keep_inputs, nsplanner.ui.keep_inputs); tests/test_app_inputs.py switches back and forth with AppTest.
  144 tests.

2026-10-29, thirty-first round: lucky tickets per cat ticket, and blue orbs as rare tickets.

- His question: is about one lucky ticket per cat ticket what it takes to use every Cat Capsule pull well?
  Sweep (his current values: Dark Catseye 5, Li'l Axe Cat 0) at 300 / 500 / 1000 cat tickets, lucky:cat
  0 to 1.5: the share of cat tickets that become blue orbs rises from 53-54% to 96-97% and stops at
  0.90 / 0.96 / 0.98 lucky per cat ticket, where the plan leaves the rest unused; by then 99.7% of Cat
  Capsule pulls are blue orbs (the remaining cat tickets go on Catseye pulls for Dark Catseyes).
- nsplanner/sweep.py: one plan per lucky count (0 to 1.2 per cat ticket, 13 plans, spawned processes,
  one at a time if processes cannot start; 2.3 s for 335 cat); advise() picks the fewest lucky tickets
  reaching the best plan and reports what that plan uses as "aim for".
- Lucky tickets tab (button "Work it out", result kept per seed / cat tickets / values): cards for now
  (×factor, orbs over pulling straight), with the recommended count (more orbs, orbs per extra lucky
  ticket) and the recommendation itself; Altair chart, improvement factor 0 to ×2.5, reference lines at
  ×1 (straight) and ×2.11 (every cat ticket a blue orb), your point and the "enough" point marked.
  His case (335 cat, 128 lucky): ×1.57, +90 orbs (+18.1 rare tickets) over straight; with 302 lucky ×2.05,
  +76 more orbs (+15.2 rare tickets), about 0.44 orbs per extra lucky ticket; aim for 0.90 per cat ticket.
- Blue orbs as rare tickets at his rate, 5 orbs = 1 (report.ORBS_PER_RARE_TICKET), with the rare
  planner's ticket icon (nsplanner/assets/rare_ticket.png): summary bar, improvement line, stop panel,
  copyable text. 148 tests.

2026-10-29, thirty-second round: fewest lucky tickets on a tie; the lucky-ticket chart, finished.

- His question: does a plan ever spend a lucky ticket it does not need (e.g. on a cell where the Cat Capsule
  has a blue orb)? Ties were broken on fewest pulls in total, not on lucky tickets. Now the order is: score,
  then fewest lucky tickets (plan.SPARE), then fewest pulls, then fewest capsule changes, in the grid search,
  plan_slow and the independent reference (tests/normal_reference.py). On 9 settings (his included) the old
  rule had already found the fewest; 60 random cases (many with spare lucky tickets) agree with the reference
  on score, lucky tickets and pulls.
- Lucky pulls on a cell where the Cat Capsule shows a blue orb remain (3 in his 335/128 plan), each needed for
  the dupe rule: 28B avoids a repeat Cat Cannon Charge at 29B that would re-roll into a Cat and switch track;
  69A is a Li'l Axe Cat repeat that switches to 70B (Research) instead of 70A (Superfeline); 399B avoids a
  Cat Capsule repeat that would switch track.
- Lucky tickets tab: worked out without a button up to 600 cat tickets (2-3 s for 335); the "Now" card shows
  blue orbs per cat ticket against 0.474; reference lines labelled "×1 = 0.474 blue orbs per cat ticket
  (pulling straight)" and "×2.11 = every cat ticket a blue orb", drawn heavier than the gridlines; axes with
  solid lines, ticks and larger labels; a hollow marker shows where the sidebar's lucky-ticket input lies
  (before Plan is pressed again); marker labels sit right of and below their points, clear of the curve.
- The code-reload notice no longer asks for Fetch banners in the Normal planner. 148 tests.
- Helper processes for the sweep are started as `python -m nsplanner.sweep` (job on stdin, one JSON point per
  line). multiprocessing's spawn re-ran app.py in every helper under Streamlit on Windows (they crashed, and
  the sweep fell back to one plan at a time: 7.7 s instead of 2.9 s for 335 cat tickets).

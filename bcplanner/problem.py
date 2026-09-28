"""Everything the search and the replay checker share: banners, values, resources, rules.

See PLAN.md sections 5.1 and 5.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .actions import CF_UNIT, TODAY, TOMORROW
from .model import DEFAULT_DUPE_VALUES, DEFAULT_PASS_PENALTIES, DEFAULT_TICKET_COST, DEFAULT_WEIGHTS, Banner
from .sim import Tables


@dataclass
class Problem:
    tables: Tables
    banners: dict[str, Banner]            # every banner the user included, by event_id
    owned: frozenset[int]
    today: date
    last_id: int = 0                      # last cat rolled (the `last` URL parameter)
    tickets: int = 0
    cat_food: int = 0
    plats: int = 0
    legends: int = 0
    tickets_per_draw: float = 30.0
    forbid_eleven_over_legend_slot: bool = True
    legend_substitute_only: bool = True      # a legend ticket only stands in for a rare ticket on a must-cross repeat slot
    max_clock_changes: int = 4
    skip_penalty: float = 0.02            # draw-equivalents per clock change, tie-break only
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    multipliers: dict[int, float] = field(default_factory=dict)   # cat id -> value multiplier (wishlist)
    dupe_values: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_DUPE_VALUES))  # rarity -> value of a repeat
    pass_penalties: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PASS_PENALTIES))  # passed uber slots
    ticket_cost: float = DEFAULT_TICKET_COST   # value charged per rare ticket spent
    discount_first_draw: bool = False        # the first 11-draw of the plan costs 750 CF (any banner)
    priority: frozenset[int] = frozenset()   # units wanted as extra copies; only steer single-ticket banner choice
    priority_allow_skip: bool = False        # a one-day clock change may be inserted to reach a priority unit

    # derived
    rare_banners: list[Banner] = field(init=False)
    plat: Banner | None = field(init=False, default=None)
    legend: Banner | None = field(init=False, default=None)
    live: dict[str, tuple[bool, bool]] = field(init=False)
    unit_ids: list[int] = field(init=False)
    unit_index: dict[int, int] = field(init=False)
    unit_value: list[float] = field(init=False)
    unit_rarity: dict[int, str] = field(init=False)
    tomorrow_adds_banners: bool = field(init=False)
    targets_mask: int = field(init=False)
    cf_units: int = field(init=False)
    _pass_memo: dict = field(init=False, default_factory=dict, repr=False)
    _slot_memo: dict = field(init=False, default_factory=dict, repr=False)

    def __post_init__(self):
        tomorrow = self.today + timedelta(days=1)
        self.rare_banners = [b for b in self.banners.values() if b.include and b.kind == "rare"]
        for b in self.banners.values():
            if not b.include:
                continue
            if b.kind == "platinum":
                self.plat = b
            elif b.kind == "legend":
                self.legend = b
        self.live = {b.event_id: (b.live_on(self.today), b.live_on(tomorrow)) for b in self.banners.values()}
        # platinum and legend banners run for years; treat them as always live
        for b in (self.plat, self.legend):
            if b is not None:
                self.live[b.event_id] = (True, True)
        self.tomorrow_adds_banners = any(
            self.live[b.event_id][1] and not self.live[b.event_id][0] for b in self.rare_banners
        )
        # unit table: every unowned unit with positive value reachable from any included banner
        rarity: dict[int, str] = {}
        for b in self.banners.values():
            if not b.include:
                continue
            for r, pool in b.pools.items():
                for cid in pool:
                    rarity.setdefault(cid, r)
        self.unit_rarity = rarity
        ids = sorted(cid for cid, r in rarity.items()
                     if cid not in self.owned and self.value_of(cid) > 0)
        self.unit_ids = ids
        self.unit_index = {cid: i for i, cid in enumerate(ids)}
        self.unit_value = [self.value_of(cid) for cid in ids]
        self.cf_units = self.cat_food // CF_UNIT
        mask = 0
        for b in self.rare_banners:
            if b.counts_for_coverage and self.live[b.event_id][0]:
                for pool in b.pools.values():
                    for cid in pool:
                        i = self.unit_index.get(cid)
                        if i is not None:
                            mask |= 1 << i
        self.targets_mask = mask

    # --- values -----------------------------------------------------------------------
    # --- uber slots gone past on the other track ---------------------------------------
    def slot_band(self, p: int) -> str:
        """'legend' when the score at position p is a legend on any banner with a legend rate (9970+), 'uber'
        when it is an uber on every banner (9470+), 'uber_fest' when it is an uber on Uberfest/Epicfest only
        (9070-9469), '' otherwise (the site's colour bands)."""
        self.tables.ensure(p)
        s = self.tables.score[p]
        return "legend" if s >= 9970 else ("uber" if s >= 9470 else ("uber_fest" if s >= 9070 else ""))

    def passed(self, k0: int, k1: int, landed) -> list[int]:
        """Positions the path goes past between offsets k0 and k1 with no roll landing on them: the other
        track's positions, plus the position a dupe reroll jumps over. Once passed they are gone for good."""
        return [p for p in range(k0, k1) if p not in landed]

    def _pass_info(self, p: int) -> tuple[float, tuple[tuple[int, float], ...], float]:
        """(band penalty, new ubers/legends an open banner gives at p as (bit, repeat value), best repeat
        value there). Memoised per position; the band is known to be an uber band."""
        hit = self._pass_memo.get(p)
        if hit is None:
            tops: list[tuple[int, float]] = []
            repeat = 0.0
            for b in self.rare_banners:
                if not (self.live[b.event_id][0] or self.live[b.event_id][1]):
                    continue
                rarity, _, cid = self.tables.cat_at(b, p)
                if rarity not in ("uber", "legend") or cid < 0:
                    continue
                bit = self.bit(cid)
                if bit:
                    tops.append((bit, self.dupe_value(rarity)))
                else:
                    repeat = max(repeat, self.dupe_value(rarity))
            hit = (self.pass_penalties.get(self.slot_band(p), 0.0), tuple(tops), repeat)
            self._pass_memo[p] = hit
        return hit

    def pass_cost(self, p: int, gained: int = 0) -> float:
        """What going past position p on the other track costs. The band penalty (see DEFAULT_PASS_PENALTIES)
        applies when a rare banner open today or tomorrow would give a new uber or legend there, one that is
        not owned and was not gained earlier in the plan. When every open banner would only repeat an uber
        the slot costs that repeat's value, because a repeat is all that was lost; a fest-only band with
        no fest banner open holds no uber and costs nothing."""
        if not self.pass_penalties or not self.slot_band(p):
            return 0.0
        pen, tops, repeat = self._pass_info(p)
        for bit, dv in tops:
            if not gained & bit:
                return pen
            repeat = max(repeat, dv)
        return repeat

    def passed_new_top(self, p: int, gained: int = 0) -> bool:
        """True when an open banner would give a new uber or legend at position p."""
        if not self.slot_band(p):
            return False
        return any(not gained & bit for bit, _ in self._pass_info(p)[1])

    def pass_penalty(self, k0: int, k1: int, landed, gained: int = 0) -> float:
        """Opportunity cost of the uber slots passed between k0 and k1 (see pass_cost)."""
        if not self.pass_penalties:
            return 0.0
        return sum(self.pass_cost(p, gained) for p in range(k0, k1) if p not in landed)

    def dupe_value(self, rarity: str) -> float:
        return self.dupe_values.get(rarity, 0.0)

    def gain(self, cat_id: int, rarity: str, gained: int) -> tuple[int, float]:
        """(bit to add to `gained`, value credited) for rolling `cat_id` with `gained` already collected.

        A first copy of a valued unit earns its value; a copy of something owned or already gained
        earns the duplicate value of its rarity, 0 by default. Tunable so that landing on an uber
        slot still counts for something when the uber repeats."""
        bit = self.bit(cat_id)
        if bit and not gained & bit:
            return bit, self.unit_value[self.unit_index[cat_id]]
        if bit or cat_id in self.owned:
            return 0, self.dupe_values.get(rarity, 0.0)
        return 0, 0.0

    def value_of(self, cat_id: int) -> float:
        r = self.unit_rarity.get(cat_id, "rare")
        return self.weights.get(r, 0.0) * self.multipliers.get(cat_id, 1.0)

    def bit(self, cat_id: int) -> int:
        i = self.unit_index.get(cat_id)
        return 0 if i is None else (1 << i)

    def mask_value(self, mask: int) -> float:
        total = 0.0
        values = self.unit_value
        while mask:
            low = mask & -mask
            total += values[low.bit_length() - 1]
            mask ^= low
        return total

    # --- search helpers ---------------------------------------------------------------
    def unit_masks_per_offset(self, horizon: int) -> list[int]:
        """per_offset[j] = units that some single action starting at offset j could yield.

        Normal rolls on every included banner (any rarity), guaranteed ubers, platinum
        and legend pulls. Rerolled rares are worth 0 and are ignored.
        """
        from .sim import guaranteed_at

        n = horizon + 64
        self.tables.ensure(n + 4)
        included = [b for b in self.banners.values() if b.include]
        per_offset = [0] * (n + 2)
        for j in range(n + 1):
            m = 0
            for b in included:
                _, _, cid = self.tables.cat_at(b, j)
                m |= self.bit(cid)
                if b.kind == "rare" and b.guaranteed_rolls and b.offers_eleven:
                    m |= self.bit(guaranteed_at(self.tables, b, j).cat_id)
            per_offset[j] = m
        self._per_offset = per_offset
        self._window_cache = {}
        return per_offset

    def window_mask(self, k: int, kmax: int) -> int:
        """Units that could still be gained by actions starting in offsets [k, kmax]."""
        per = self._per_offset
        kmax = min(kmax, len(per) - 1)
        key = (k, kmax)
        m = self._window_cache.get(key)
        if m is None:
            m = 0
            for j in range(k, kmax + 1):
                m |= per[j]
            self._window_cache[key] = m
        return m

    def reach(self, t: int, c: int, p: int, l: int) -> int:
        """Upper bound on steps a label can still consume with its remaining resources."""
        draws = (self.cf_units - c + 1) // 2 + (1 if self.discount_first_draw else 0)
        per_draw = 0
        for b in self.rare_banners:
            if b.offers_eleven:
                n = b.guaranteed_rolls if b.guaranteed_rolls else 11
                steps = 3 * (n - 1) + 1 if b.guaranteed_rolls else 3 * 11   # every roll may reroll
                per_draw = max(per_draw, steps)
        return 3 * (self.tickets - t) + per_draw * draws + 2 * (self.plats - p) + 2 * (self.legends - l)

    def canonical_last(self, k: int, last: int) -> int:
        """`last` only matters if a rare roll at offset k on some included banner equals it."""
        if last <= 0:
            return 0
        for b in self.rare_banners:
            rarity, _, cid = self.tables.cat_at(b, k)
            if rarity == "rare" and cid == last:
                return last
        return 0

    def mask_ids(self, mask: int) -> list[int]:
        out = []
        i = 0
        while mask:
            if mask & 1:
                out.append(self.unit_ids[i])
            mask >>= 1
            i += 1
        return out

    # --- rules ------------------------------------------------------------------------
    def new_legend_at(self, k: int, gained: int) -> int:
        """Legend cat id if offset k is a legend slot on the legend banner yielding an
        unowned, not-yet-gained legend; else 0."""
        b = self.legend
        if b is None:
            return 0
        if not self.tables.is_legend_slot(b, k):
            return 0
        _, _, cid = self.tables.cat_at(b, k)
        if cid in self.owned or (self.bit(cid) and (gained & self.bit(cid))):
            return 0
        if cid < 0:
            return 0
        return cid

    def repeats_everywhere(self, k: int, gained: int = 0) -> bool:
        """True when every rare banner open today or tomorrow gives an uber or legend at offset k that is
        owned or already gained: a rare ticket spent there could only fetch a repeat."""
        hit = self._slot_memo.get(k)
        if hit is None:
            all_top, any_open, new_bits = True, False, 0
            for b in self.rare_banners:
                if not (self.live[b.event_id][0] or self.live[b.event_id][1]):
                    continue
                any_open = True
                rarity, _, cid = self.tables.cat_at(b, k)
                if rarity not in ("uber", "legend") or cid < 0:
                    all_top = False
                    break
                new_bits |= self.bit(cid)
            hit = (all_top and any_open, new_bits)
            self._slot_memo[k] = hit
        all_top, new_bits = hit
        return all_top and not (new_bits & ~gained)

    def legend_allowed(self, k: int, gained: int) -> int:
        """The new legend a legend ticket may take at offset k, or 0. With `legend_substitute_only` the slot
        must also give a repeat uber on every open banner, so the ticket only ever replaces a rare ticket
        that would have fetched a repeat on the way to something better; the search and the replay also
        require a later roll to gain something new (Label.pending)."""
        cid = self.new_legend_at(k, gained)
        if not cid:
            return 0
        if self.legend_substitute_only and not self.repeats_everywhere(k, gained):
            return 0
        return cid

    def legend_mandatory(self, k: int, gained: int, legends_used: int) -> int:
        """The legend you must take here with a legend ticket, or 0."""
        if legends_used >= self.legends:
            return 0
        return self.legend_allowed(k, gained)

    def banner_live(self, event_id: str, clock: int) -> bool:
        return self.live[event_id][1 if clock == TOMORROW else 0]

    def eleven_cost_units(self, banner: Banner, dmask: int) -> int:
        """Cat food units (750 each) for an 11-draw; dmask == 1 once the plan's first draw is done."""
        if self.discount_first_draw and dmask == 0:
            return 1
        return 2

    def dmask_after_eleven(self, dmask: int) -> int:
        return 1 if self.discount_first_draw else dmask

    def scalar_cost(self, tickets: int, cf_units: int, plats: int, skips: int) -> float:
        return tickets / self.tickets_per_draw + cf_units / 2 + skips * self.skip_penalty + plats * 1e-6

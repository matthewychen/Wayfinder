"""Exact simulation of Battle Cats gacha rolls on a known seed.

Everything here is a pure function of (seed stream, banner, offset, last rare cat).
No resources, no plans: those live in search.py. See PLAN.md section 2 for the
mechanics and section 4 for the design.

Offset convention (see prng.py): a roll at offset k uses S[k+1] for rarity and
S[k+2] for the slot, then k becomes k+2 (plus one per duplicate-rare reroll).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import BASE, Banner
from .prng import site_label, stream


@dataclass(frozen=True)
class Roll:
    """One cat obtained by a normal roll (rare ticket, or one of the rolls inside an 11-draw)."""
    banner: str          # event_id
    offset_before: int
    offset_after: int
    rarity_seed: int
    slot_seed: int
    score: int
    rarity: str
    slot: int            # final slot in the banner's pool for that rarity
    cat_id: int          # final cat obtained
    rerolled: bool = False
    reroll_steps: int = 0
    duped_cat_id: int = 0    # the duplicate rare that was replaced, if rerolled
    duped_slot: int = -1
    reroll_seed: int = 0     # the seed value used for the (last) reroll pick

    @property
    def label(self) -> str:
        return site_label(self.offset_before)


@dataclass(frozen=True)
class Guaranteed:
    """The guaranteed uber at the end of an 11-draw or step-up: one step only."""
    banner: str
    offset_before: int   # offset of the position the last roll would have used
    offset_after: int    # offset_before + 1
    seed_used: int       # S[offset_before + 1]
    slot: int
    cat_id: int

    @property
    def label(self) -> str:
        return site_label(self.offset_before) + "G"


@dataclass
class Tables:
    """Seed stream and per-banner lookups for one starting seed."""
    url_seed: int
    horizon: int
    S: list[int] = field(default_factory=list)
    score: list[int] = field(default_factory=list)   # score[k] = S[k+1] % 10000

    def __post_init__(self):
        self.S = stream(self.url_seed, self.horizon + 4)
        self.score = [s % BASE for s in self.S[1:]]

    def ensure(self, offset: int) -> None:
        """Grow the stream if a simulation runs past the precomputed horizon."""
        if offset + 4 >= len(self.S):
            extra = offset + 4 - len(self.S) + 64
            s = self.S[-1]
            for _ in range(extra):
                s = (s ^ ((s << 13) & 0xFFFFFFFF))
                s ^= s >> 17
                s ^= (s << 15) & 0xFFFFFFFF
                self.S.append(s)
                self.score.append(s % BASE)
            self.horizon = len(self.S) - 4

    # --- rarity / slot helpers -------------------------------------------------------
    def rarity_at(self, banner: Banner, k: int) -> str:
        self.ensure(k)
        return banner.rarity_for_score(self.score[k])

    def is_legend_slot(self, banner: Banner, k: int) -> bool:
        """True when a roll at offset k on this banner yields a legend."""
        thr = banner.legend_threshold
        if thr is None:
            return False
        self.ensure(k)
        return self.score[k] >= thr

    def cat_at(self, banner: Banner, k: int) -> tuple[str, int, int]:
        """(rarity, slot, cat_id) for a roll at offset k, before any dupe reroll. Memoised."""
        cache = self.__dict__.setdefault("_cat_cache", {})
        key = (banner.event_id, k)
        hit = cache.get(key)
        if hit is not None:
            return hit
        self.ensure(k)
        rarity = banner.rarity_for_score(self.score[k])
        pool = banner.pool(rarity)
        if not pool:
            result = (rarity, -1, -1)
        else:
            slot = self.S[k + 2] % len(pool)
            result = (rarity, slot, pool[slot])
        cache[key] = result
        return result


def reroll(tables: Tables, banner: Banner, k: int, slot: int, cat_id: int) -> tuple[int, int, int, int]:
    """Replace a consecutive duplicate rare, exactly as gacha.rb#reroll_cat.

    Returns (new_cat_id, new_slot_in_original_pool, steps, seed_used).
    Each step advances the seed once, deletes the duplicate's slot from a working
    copy of the rare list, and picks seed % (remaining size). Repeats only if the
    pool contains the same cat more than once.
    """
    pool = list(banner.pool("rare"))
    remaining = list(pool)
    steps = 0
    seed = tables.S[k + 2]          # the slot seed of the duplicate; next advance is S[k+3]
    new_id = cat_id
    working_slot = slot
    max_steps = remaining.count(cat_id)
    while steps < max_steps:
        steps += 1
        tables.ensure(k + 2 + steps)
        seed = tables.S[k + 2 + steps]
        del remaining[working_slot]
        working_slot = seed % len(remaining)
        new_id = remaining[working_slot]
        if new_id != cat_id:
            break
    # map the index in the reduced list back to the original pool position:
    # the reduced list is the original with `steps` entries removed before/at this point,
    # so recover by matching identity on the original list order.
    original_slot = _original_slot(pool, remaining, working_slot)
    return new_id, original_slot, steps, seed


def _original_slot(pool: list[int], remaining: list[int], idx: int) -> int:
    """Index in the original pool of the element at `idx` in `remaining` (a subsequence of pool)."""
    pi = 0
    for ri, value in enumerate(remaining):
        while pool[pi] != value:
            pi += 1
        if ri == idx:
            return pi
        pi += 1
    return -1


def single(tables: Tables, banner: Banner, k: int, last_rare: int) -> Roll:
    """One normal roll at offset k. `last_rare` is the last cat's id if it was rare, else 0."""
    tables.ensure(k)
    rarity, slot, cat_id = tables.cat_at(banner, k)
    rarity_seed = tables.S[k + 1]
    slot_seed = tables.S[k + 2]
    if rarity == "rare" and cat_id > 0 and cat_id == last_rare:
        new_id, new_slot, steps, seed_used = reroll(tables, banner, k, slot, cat_id)
        return Roll(
            banner=banner.event_id, offset_before=k, offset_after=k + 2 + steps,
            rarity_seed=rarity_seed, slot_seed=slot_seed, score=tables.score[k],
            rarity=rarity, slot=new_slot, cat_id=new_id,
            rerolled=True, reroll_steps=steps, duped_cat_id=cat_id, duped_slot=slot,
            reroll_seed=seed_used,
        )
    return Roll(
        banner=banner.event_id, offset_before=k, offset_after=k + 2,
        rarity_seed=rarity_seed, slot_seed=slot_seed, score=tables.score[k],
        rarity=rarity, slot=slot, cat_id=cat_id,
    )


def next_last_rare(roll: Roll) -> int:
    return roll.cat_id if roll.rarity == "rare" else 0


def sequence(tables: Tables, banner: Banner, k: int, last_rare: int, n_rolls: int) -> tuple[list[Roll], int, int]:
    """n normal rolls in a row on one banner. Returns (rolls, offset_after, last_rare_after)."""
    rolls = []
    for _ in range(n_rolls):
        r = single(tables, banner, k, last_rare)
        rolls.append(r)
        k = r.offset_after
        last_rare = next_last_rare(r)
    return rolls, k, last_rare


def guaranteed_at(tables: Tables, banner: Banner, k: int) -> Guaranteed:
    """The guaranteed uber when the last roll of a guaranteed draw would start at offset k."""
    tables.ensure(k)
    ubers = banner.pool("uber")
    seed_used = tables.S[k + 1]
    slot = seed_used % len(ubers) if ubers else -1
    cat_id = ubers[slot] if ubers else -1
    return Guaranteed(banner=banner.event_id, offset_before=k, offset_after=k + 1,
                      seed_used=seed_used, slot=slot, cat_id=cat_id)


def eleven(tables: Tables, banner: Banner, k: int, last_rare: int,
           guaranteed_rolls: int) -> tuple[list[Roll], Guaranteed | None, int, int]:
    """A multi-draw. With guaranteed_rolls 11 or 15: that many minus one normal rolls,
    then the one-step guaranteed uber, landing on the other parity. With 0: eleven
    plain rolls (assumption A5). Returns (rolls, guaranteed, offset_after, last_rare_after)."""
    if guaranteed_rolls in (11, 15):
        rolls, k2, last2 = sequence(tables, banner, k, last_rare, guaranteed_rolls - 1)
        g = guaranteed_at(tables, banner, k2)
        return rolls, g, g.offset_after, 0     # an uber clears dupe memory
    rolls, k2, last2 = sequence(tables, banner, k, last_rare, 11)
    return rolls, None, k2, last2


# ---------------------------------------------------------------------------------------
# Site-table reproduction, used by the golden tests and the scrape self-test.
# ---------------------------------------------------------------------------------------

@dataclass
class SitePosition:
    label: str
    rarity_seed: int
    slot_seed: int
    score: int
    slot: int
    cat_id: int
    rerolled_id: int | None = None
    rerolled_next: str | None = None
    guaranteed_id: int | None = None
    guaranteed_next: str | None = None
    rerolled_guaranteed_id: int | None = None
    rerolled_guaranteed_next: str | None = None


def site_table(tables: Tables, banner: Banner, last_id: int, rows: int,
               guaranteed_rolls: int) -> list[tuple[SitePosition, SitePosition]]:
    """Reproduce bc.godfat.org's table: per row, positions A and B.

    Dupe checks use the same-track predecessor as displayed (the site's convention),
    and `last_id` for 1A. Guaranteed cells are computed by sequential simulation from
    the position, which is exactly what the site's chain of `next` links resolves to.
    """
    out: list[tuple[SitePosition, SitePosition]] = []
    displayed: dict[tuple[int, int], int] = {}   # (row index, track) -> displayed cat id
    for n in range(rows):
        pair = []
        for track in (0, 1):
            k = 2 * n + track
            if n == 0:
                prev = last_id if track == 0 else 0
            else:
                prev = displayed[(n - 1, track)]
            base = single(tables, banner, k, 0)          # displayed (non-rerolled) cat
            displayed[(n, track)] = base.cat_id
            pos = SitePosition(label=site_label(k), rarity_seed=base.rarity_seed,
                               slot_seed=base.slot_seed, score=base.score,
                               slot=base.slot, cat_id=base.cat_id)
            actual = single(tables, banner, k, prev)      # what you get arriving on this track
            if actual.rerolled:
                pos.rerolled_id = actual.cat_id
                pos.rerolled_next = site_label(actual.offset_after)
            if guaranteed_rolls:
                # arriving on this track, the displayed cat is roll 1 if it is not a dupe;
                # otherwise the rerolled cat is roll 1 (that case is the rerolled guaranteed).
                if not actual.rerolled:
                    _, g, _, _ = eleven(tables, banner, k, prev, guaranteed_rolls)
                    if g is not None and g.offset_after < 2 * rows:
                        pos.guaranteed_id, pos.guaranteed_next = g.cat_id, site_label(g.offset_after)
                else:
                    # the non-rerolled variant: arriving from elsewhere with a different last cat
                    _, g, _, _ = eleven(tables, banner, k, 0, guaranteed_rolls)
                    if g is not None and g.offset_after < 2 * rows:
                        pos.guaranteed_id, pos.guaranteed_next = g.cat_id, site_label(g.offset_after)
                    # the rerolled variant: roll 1 is the rerolled cat, then the rest
                    _, k2, last2 = sequence(tables, banner, actual.offset_after, actual.cat_id, guaranteed_rolls - 2)
                    g2 = guaranteed_at(tables, banner, k2)
                    if g2.offset_after < 2 * rows:
                        pos.rerolled_guaranteed_id = g2.cat_id
                        pos.rerolled_guaranteed_next = site_label(g2.offset_after)
            pair.append(pos)
        out.append((pair[0], pair[1]))
    return out

"""The Battle Cats gacha generator: xorshift32 with shifts 13, 17, 15.

Verified against godfat/battle-cats-rolls (GitLab master):
  * lib/battle-cats-rolls/gacha.rb  advance_seed / retreat_seed
  * Seeker/Seeker-VampireFlower.c   xorshift32 / reverse_xorshift32 (compiled and run)
on 200k random seeds plus edge cases. See tests/test_prng.py.

Conventions used everywhere in this package
-------------------------------------------
S[0] is the seed shown in a bc.godfat.org URL (the slot seed of the last cat rolled).
S[i+1] = advance(S[i]).
An "offset" k counts steps consumed since S[0]. The next roll at offset k uses
S[k+1] for rarity and S[k+2] for the slot, and leaves you at k+2.
"""

from __future__ import annotations

MASK = 0xFFFFFFFF


def advance(seed: int) -> int:
    """One generator step (the game's roll of the dice)."""
    seed ^= (seed << 13) & MASK
    seed ^= seed >> 17
    seed ^= (seed << 15) & MASK
    return seed


def retreat(seed: int) -> int:
    """Exact inverse of advance(). Two retreats undo one normal roll."""
    seed ^= (seed << 15) & MASK
    seed ^= (seed << 30) & MASK
    seed ^= seed >> 17
    seed ^= (seed << 13) & MASK
    seed ^= (seed << 26) & MASK
    return seed


def stream(seed: int, steps: int) -> list[int]:
    """Return [S[0], S[1], ..., S[steps]] starting from the URL seed."""
    out = [seed]
    s = seed
    for _ in range(steps):
        s = advance(s)
        out.append(s)
    return out


def site_label(offset: int) -> str:
    """bc.godfat.org position label for an offset: row k//2+1, track A/B by parity."""
    return f"{offset // 2 + 1}{'AB'[offset % 2]}"

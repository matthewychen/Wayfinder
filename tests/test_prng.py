import random

from bcplanner.prng import advance, retreat, site_label, stream

MASK = 0xFFFFFFFF


# Literal port of gacha.rb: shift(direction, bits, seed) => seed ^= (seed op bits) % 0x100000000
def _rb_shift(op, bits, s):
    v = (s << bits) if op == "<<" else (s >> bits)
    return s ^ (v % 0x100000000)


def _rb_advance(s):
    s = _rb_shift("<<", 13, s)
    s = _rb_shift(">>", 17, s)
    s = _rb_shift("<<", 15, s)
    return s


def _rb_retreat(s):
    s = _rb_shift("<<", 15, s)
    s = _rb_shift("<<", 30, s)
    s = _rb_shift(">>", 17, s)
    s = _rb_shift("<<", 13, s)
    s = _rb_shift("<<", 26, s)
    return s


SEEDS = [random.Random(7).getrandbits(32) for _ in range(20000)] + [
    1, 2, 3, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 3163852999, 491579265,
]


def test_matches_literal_ruby_port():
    for s in SEEDS:
        assert advance(s) == _rb_advance(s)
        assert retreat(s) == _rb_retreat(s)


def test_retreat_inverts_advance_both_ways():
    for s in SEEDS:
        assert retreat(advance(s)) == s
        assert advance(retreat(s)) == s


def test_known_vector_from_live_site():
    # https://bc.godfat.org/?seed=3163852999&last=689&event=2026-09-11_1076&details=true shows 1A seed 491579265
    assert advance(3163852999) == 491579265


def test_stream_and_labels():
    S = stream(3163852999, 3)
    assert S[0] == 3163852999 and S[1] == 491579265 and len(S) == 4
    assert [site_label(k) for k in range(5)] == ["1A", "1B", "2A", "2B", "3A"]

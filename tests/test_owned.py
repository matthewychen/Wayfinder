import pytest

from bcplanner.owned import decode, encode, parse_owned_input


def test_roundtrip_small_and_large_ids():
    ids = [1, 689, 873, 5, 800]
    assert decode(encode(ids)) == sorted(ids)


def test_known_vector_verified_on_live_site():
    # This code, put in bc.godfat.org/cats?o=..., checked exactly cats 1, 689 and 873.
    code = ("cSIgc7uUS1JghmTVymoxbN1klSa2AIdRkfzOLB6JFMdBVt5HTcHFPukz8mK0eaCjnTAFEvrud3hmkYDXrJSSEwL56KDMaLxz2swAdBdp8AzRH3sbV8XluRG8CmqZFMDne2dLUFGuHRGMRCFT0Uq")
    assert decode(code) == [1, 689, 873]
    assert encode([689, 1, 873]) == code


def test_empty_and_invalid():
    assert encode([]) == ""
    assert decode("") == []
    assert decode("not-valid!") == []


def test_parse_owned_input_forms():
    code = encode([10, 20])
    assert parse_owned_input(f"https://bc.godfat.org/cats?lang=en&o={code}") == [10, 20]
    assert parse_owned_input(f"o={code}&lang=en") == [10, 20]
    assert parse_owned_input(code) == [10, 20]
    assert parse_owned_input("https://bc.godfat.org/cats?lang=en&x=1&o=") == []  # present but empty: nothing owned
    with pytest.raises(ValueError):
        parse_owned_input("https://bc.godfat.org/cats?lang=en&owned=abc")  # old form or no o= at all

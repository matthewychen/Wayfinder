"""Owned-units codec, ported from lib/battle-cats-rolls/owned.rb.

The site's cats page carries the owned set in the `o` query parameter as a
base-62 integer whose bit `id` is set when cat `id` is owned. Digit order is
0-9, a-z, A-Z (lowercase before uppercase), most significant digit first.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_INDEX = {c: i for i, c in enumerate(DIGITS)}
_VALID = re.compile(r"\A[0-9A-Za-z]+\Z")


def encode(cat_ids) -> str:
    """Owned ids -> `o` string. Empty input gives ''."""
    ids = set(int(i) for i in cat_ids)
    if not ids:
        return ""
    value = 0
    for i in ids:
        value |= 1 << i
    if value == 0:
        return "0"
    digits = []
    while value:
        value, rem = divmod(value, 62)
        digits.append(DIGITS[rem])
    return "".join(reversed(digits))


def decode(code: str) -> list[int]:
    """`o` string -> sorted owned ids. Invalid or empty input gives []."""
    if not code or not _VALID.match(code):
        return []
    value = 0
    for ch in code:
        value = value * 62 + _INDEX[ch]
    if value == 0:
        return []
    ids = []
    bit = 0
    while value:
        if value & 1:
            ids.append(bit)
        value >>= 1
        bit += 1
    return ids


def parse_owned_input(text: str) -> list[int]:
    """Accept a full cats-page URL, a query string, or a bare `o` value."""
    text = text.strip()
    if not text:
        return []
    looks_like_url = "://" in text or text.startswith("/") or "?" in text or "&" in text or "=" in text
    if looks_like_url:
        query = urlsplit(text).query if ("://" in text or text.startswith("/")) else text
        params = parse_qs(query.lstrip("?"), keep_blank_values=True)
        if "o" in params:
            return decode(params["o"][0])
        raise ValueError("The URL has no o= parameter. Tick your cats on the site, press 'Own all ticked', then copy the URL.")
    return decode(text)

"""Parse Portuguese and English formatted prices into integer euros."""

from __future__ import annotations

import re

# A grouped integer such as 12.500, 12 500, 12,500 or an ungrouped run of digits,
# optionally followed by a two-digit decimal part which we discard.
_AMOUNT = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,3}(?:[.,\s\u00a0\u202f]\d{3})+|\d+)"
    r"(?:[.,](\d{1,2}))?"
    r"(?!\d)"
)
_SEPARATORS = re.compile(r"[.,\s\u00a0\u202f]")

MIN_PRICE_EUR = 1
MAX_PRICE_EUR = 10_000_000


def parse_price(text: str | None) -> int | None:
    """Return the first plausible amount in ``text`` as whole euros, or None.

    Cents are dropped. Zero and absurd values are treated as unparsed so a
    "Grátis" or placeholder price never masquerades as a bargain.
    """
    if not text:
        return None
    for match in _AMOUNT.finditer(text):
        digits = _SEPARATORS.sub("", match.group(1))
        if not digits:
            continue
        value = int(digits)
        if MIN_PRICE_EUR <= value <= MAX_PRICE_EUR:
            return value
    return None

"""Find odometer readings in free text (seller descriptions, detail lines, OCR output)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# 150.000 / 150 000 / 150000, optionally "150 mil", followed by a km unit and
# not by "/h" (a speedometer scale or a top speed is not mileage).
_KM = re.compile(
    r"(?<![\d.,])"
    r"(\d{1,3}(?:[.\s\u00a0\u202f]\d{3})+|\d+)"
    r"(?:,\d+)?"
    r"\s*(?P<mil>mil\s*)?"
    r"(?:km|kms|kil[oó]metros|quil[oó]metros)\b"
    r"(?!\s*/\s*h)",
    re.IGNORECASE,
)
_SEPARATORS = re.compile(r"[.\s\u00a0\u202f]")

# Anything above this is not a car odometer.
MAX_KM = 1_500_000
# OCR of a dashboard photo needs at least four digits to be believable; a "180 km"
# reading is a speedometer dial, not mileage.
OCR_MIN_KM = 1_000


@dataclass(frozen=True, slots=True)
class KmMatch:
    value: int
    text: str


def find_km_values(text: str | None, *, minimum: int = 0) -> list[KmMatch]:
    """All plausible km readings in ``text``, in order of appearance."""
    if not text:
        return []
    found: list[KmMatch] = []
    for match in _KM.finditer(text):
        digits = _SEPARATORS.sub("", match.group(1))
        if not digits:
            continue
        value = int(digits)
        if match.group("mil"):
            value *= 1_000
        if minimum <= value <= MAX_KM:
            found.append(KmMatch(value=value, text=match.group(0).strip()))
    return found


def first_km(text: str | None, *, minimum: int = 0) -> int | None:
    """The first plausible reading, which is almost always the odometer in prose."""
    matches = find_km_values(text, minimum=minimum)
    return matches[0].value if matches else None


def largest_km(text: str | None, *, minimum: int = OCR_MIN_KM) -> int | None:
    """The largest plausible reading: on a dashboard photo that is the total, not the trip."""
    matches = find_km_values(text, minimum=minimum)
    return max((m.value for m in matches), default=None)

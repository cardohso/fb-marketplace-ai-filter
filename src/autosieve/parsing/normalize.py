"""Map the many spellings of fuel and gearbox types onto a small vocabulary."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal, get_args

Fuel = Literal["gasolina", "gasoleo", "hibrido", "eletrico", "gpl", "outro"]
Gearbox = Literal["manual", "automatica"]

FUELS: tuple[str, ...] = get_args(Fuel)
GEARBOXES: tuple[str, ...] = get_args(Gearbox)

_FUEL_PATTERNS: tuple[tuple[re.Pattern[str], Fuel], ...] = (
    # Order matters: "hibrido plug-in (gasolina)" must be hybrid, not petrol.
    (re.compile(r"h[iy]brid"), "hibrido"),
    (re.compile(r"\bel[eé]tric|\belectric|\bev\b"), "eletrico"),
    (re.compile(r"\bgpl\b|\blpg\b|\bgas natural|\bgnc\b"), "gpl"),
    (re.compile(r"gasoleo|diesel|\btdi\b|\bhdi\b|\bdci\b|\bcdti\b|\bcrdi\b|\bd-4d\b"), "gasoleo"),
    (re.compile(r"gasolina|petrol|\btsi\b|\btfsi\b|\bvti\b|\bmpi\b"), "gasolina"),
)
_GEARBOX_PATTERNS: tuple[tuple[re.Pattern[str], Gearbox], ...] = (
    (re.compile(r"autom|\bdsg\b|\bcvt\b|\btiptronic|\bs-?tronic|\bedc\b|\bpdk\b"), "automatica"),
    (re.compile(r"manual"), "manual"),
)


def fold(text: str) -> str:
    """Lowercase and strip accents so 'Gasóleo' and 'gasoleo' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


def normalize_fuel(text: str | None) -> Fuel | None:
    if not text:
        return None
    folded = fold(text)
    if folded in FUELS:
        return folded  # type: ignore[return-value]
    for pattern, fuel in _FUEL_PATTERNS:
        if pattern.search(folded):
            return fuel
    return None


def normalize_gearbox(text: str | None) -> Gearbox | None:
    if not text:
        return None
    folded = fold(text)
    if folded in GEARBOXES:
        return folded  # type: ignore[return-value]
    for pattern, gearbox in _GEARBOX_PATTERNS:
        if pattern.search(folded):
            return gearbox
    return None

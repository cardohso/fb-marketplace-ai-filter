"""Resolve one canonical vehicle identity from the page facts and the LLM.

The scraper reads year, fuel and gearbox deterministically from the details
block; the LLM supplies make, model and engine, and fills the rest when the
page did not. Deterministic page data wins wherever both exist. The result is a
:class:`VehicleKey` the benchmark layer can look a car up by, plus a coverage
score that says how much of the identity is actually known.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel

from autosieve.models import Analysis, Listing
from autosieve.parsing.normalize import Fuel, Gearbox

# Model names are noisy: strip engine displacement, power and fuel words so
# "Clio 1.5 dCi Dynamique" and "clio" resolve to the same benchmark key. Bare
# integers (208, 500, Série 3) are model identifiers and are kept.
_MODEL_NOISE = re.compile(
    r"\b("
    r"\d+[.,]\d+"  # engine displacement: 1.5, 1.9, 2.0
    r"|\d+\s*(?:cv|hp|kw|cc)"  # power or displacement with a unit
    r"|tdi|tdci|hdi|dci|cdti|crdi|tsi|tfsi|vti|mpi|gti|gtd"
    r"|automatic[oa]?|manual|diesel|gasolina|gasoleo|hibrido|eletric[oa]?"
    r")\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

# Model families whose name is genuinely two tokens (Mercedes "Classe C",
# BMW "Serie 3"); for everything else the family is the first token, so trims
# and body styles ("Dynamique", "Variant", "cabrio") drop away.
_TWO_TOKEN_FAMILIES = frozenset({"classe", "class", "serie", "series"})


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def canonical_make(make: str) -> str:
    folded = _PUNCT.sub(" ", _fold(make))
    return _WS.sub(" ", folded).strip()


def canonical_model(model: str) -> str:
    # Strip noise before punctuation, so "1.5" is removed as a unit and not first
    # split into "1 5" by the punctuation pass.
    folded = _MODEL_NOISE.sub(" ", _fold(model))
    folded = _PUNCT.sub(" ", folded)
    tokens = [t for t in _WS.sub(" ", folded).strip().split(" ") if t]
    if not tokens:
        return ""
    # The family is the first token, plus its discriminator for "Classe C" /
    # "Serie 3"; trims and body styles after it are dropped.
    if tokens[0] in _TWO_TOKEN_FAMILIES and len(tokens) > 1:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]


class VehicleKey(BaseModel, frozen=True):
    """The minimum identity needed to match a market benchmark."""

    make: str
    model: str
    fuel: Fuel | None = None

    def __str__(self) -> str:
        parts = [self.make, self.model]
        if self.fuel:
            parts.append(self.fuel)
        return " / ".join(parts)


class ResolvedVehicle(BaseModel):
    """A listing's identity after merging deterministic and LLM sources."""

    make: str | None = None
    model: str | None = None
    year: int | None = None
    fuel: Fuel | None = None
    gearbox: Gearbox | None = None
    engine: str | None = None

    @property
    def key(self) -> VehicleKey | None:
        """A benchmark key, or None when make or model is unknown."""
        if not self.make or not self.model:
            return None
        model = canonical_model(self.model)
        if not model:
            return None
        return VehicleKey(make=canonical_make(self.make), model=model, fuel=self.fuel)

    @property
    def coverage(self) -> float:
        """Fraction of make, model, year and fuel that are known (0.0 to 1.0)."""
        known = sum(x is not None for x in (self.make, self.model, self.year, self.fuel))
        return known / 4

    @property
    def is_identified(self) -> bool:
        return self.key is not None


def _first[T](*values: T | None) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def resolve_identity(listing: Listing, analysis: Analysis | None) -> ResolvedVehicle:
    """Merge page facts and LLM output, preferring deterministic page data."""
    vehicle = analysis.vehicle if analysis else None
    return ResolvedVehicle(
        make=vehicle.make if vehicle else None,
        model=vehicle.model if vehicle else None,
        # The parser reads these straight off the page, so they beat the model.
        year=_first(listing.year, vehicle.year if vehicle else None),
        fuel=_first(listing.fuel, vehicle.fuel if vehicle else None),
        gearbox=_first(listing.gearbox, vehicle.gearbox if vehicle else None),
        engine=vehicle.engine if vehicle else None,
    )

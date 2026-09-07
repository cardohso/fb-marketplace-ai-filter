"""Decide whether a listing matches a watch.

Rule of thumb: a set criterion excludes a listing only when the listing's value
is known and fails it. Unknown numeric data (a missing mileage) does not exclude
a car, so a lookout does not silently hide new listings. The exception is make
and model: when a watch names them, the listing's identity must be known and
match, otherwise it is not the car you asked to watch.
"""

from __future__ import annotations

from dataclasses import dataclass

from autosieve.identity import canonical_make, canonical_model, resolve_identity
from autosieve.models import Analysis, Listing, resolve_kms
from autosieve.scoring import DealScore
from autosieve.watch.models import Watch


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: bool
    reason: str = ""


def _identity_matches(watch: Watch, listing: Listing, analysis: Analysis | None) -> MatchResult:
    resolved = resolve_identity(listing, analysis)
    if watch.make is not None:
        if resolved.make is None:
            return MatchResult(False, "make unknown")
        if canonical_make(resolved.make) != canonical_make(watch.make):
            return MatchResult(False, "make differs")
    if watch.model is not None:
        if resolved.model is None:
            return MatchResult(False, "model unknown")
        if canonical_model(resolved.model) != canonical_model(watch.model):
            return MatchResult(False, "model differs")
    return MatchResult(True)


def watch_matches(
    watch: Watch,
    listing: Listing,
    analysis: Analysis | None,
    score: DealScore | None = None,
) -> MatchResult:
    """Whether ``listing`` satisfies ``watch``. ``score`` is only needed for min_score."""
    if not watch.enabled:
        return MatchResult(False, "watch disabled")

    # A listing the model classified as parts or an accessory is never a match,
    # even for a broad watch that names no make or model.
    if analysis is not None and not analysis.is_vehicle:
        return MatchResult(False, "not a vehicle")

    identity = _identity_matches(watch, listing, analysis)
    if not identity.matched:
        return identity

    resolved = resolve_identity(listing, analysis)
    year = resolved.year
    if year is not None:
        if watch.year_min is not None and year < watch.year_min:
            return MatchResult(False, "older than year_min")
        if watch.year_max is not None and year > watch.year_max:
            return MatchResult(False, "newer than year_max")

    price = listing.price_eur
    if price is not None:
        if watch.price_max is not None and price > watch.price_max:
            return MatchResult(False, "over price_max")
        if watch.price_min is not None and price < watch.price_min:
            return MatchResult(False, "under price_min")

    kms, _ = resolve_kms(listing, analysis, None)
    if kms is not None and watch.km_max is not None and kms > watch.km_max:
        return MatchResult(False, "over km_max")

    if watch.fuel is not None and resolved.fuel is not None and resolved.fuel != watch.fuel:
        return MatchResult(False, "fuel differs")
    if (
        watch.gearbox is not None
        and resolved.gearbox is not None
        and resolved.gearbox != watch.gearbox
    ):
        return MatchResult(False, "gearbox differs")

    if watch.private_only and analysis is not None and analysis.is_dealer:
        return MatchResult(False, "dealer excluded")

    if (
        watch.min_score is not None
        and score is not None
        and score.score is not None
        and score.score < watch.min_score
    ):
        return MatchResult(False, "below min_score")

    return MatchResult(True, "matched")

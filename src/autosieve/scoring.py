"""The deal score: how good a listing is versus its market benchmark.

    score = (benchmark median / asking price) x condition_multiplier

A score above 1.0 means the car is priced below what its identity normally
fetches, adjusted for what the listing says about condition. Every adjustment
carries a human-readable reason, because an unexplained score is not actionable.
Listings that cannot be scored (no price, placeholder price, unknown identity,
not a vehicle) are reported with a status instead of a misleading number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from autosieve.benchmark import Benchmark, BenchmarkProvider
from autosieve.identity import ResolvedVehicle, resolve_identity
from autosieve.models import Analysis, Listing, resolve_kms

# Assumed annual mileage for the age-vs-mileage adjustment.
KM_PER_YEAR = 15_000
# A price below this share of the benchmark median is a placeholder, not an offer.
PLACEHOLDER_PRICE_RATIO = 0.15
PLACEHOLDER_PRICE_FLOOR = 200
# A ratio above this is almost always a mismatch (wrong variant, salvage, bad
# data), not a genuine bargain, so it is flagged and its confidence is capped.
SUSPICIOUS_RATIO = 2.2
SUSPICIOUS_CONFIDENCE_CAP = 0.35
# Distance from the origin (Faro) below which a car carries no travel penalty.
FREE_DISTANCE_KM = 60.0
# Penalty per 100 km beyond the free radius, and the most it can ever take off.
DISTANCE_PENALTY_PER_100KM = 0.05
MAX_DISTANCE_PENALTY = 0.15


class ScoreStatus(StrEnum):
    SCORED = "scored"
    NON_VEHICLE = "non_vehicle"
    NO_PRICE = "no_price"
    NO_BENCHMARK = "no_benchmark"


class DealScore(BaseModel):
    listing_id: str
    status: ScoreStatus
    score: float | None = Field(default=None, description="Higher is a better deal; ~1.0 is fair")
    price_eur: int | None = None
    benchmark_median: int | None = None
    base_ratio: float | None = None
    condition_multiplier: float = 1.0
    confidence: float = Field(default=0.0, ge=0, le=1)
    is_dealer: bool | None = None
    kms: int | None = None
    distance_km: float | None = Field(default=None, description="Distance from the origin (Faro)")
    reasons: list[str] = Field(default_factory=list)

    @property
    def is_scored(self) -> bool:
        return self.status is ScoreStatus.SCORED


def _reference_year() -> int:
    return datetime.now(UTC).year


def _mileage_factor(
    kms: int | None, year: int | None, reference_year: int
) -> tuple[float, str | None]:
    """A gentle, capped adjustment for mileage that is high or low for the car's age."""
    if kms is None or year is None:
        return 1.0, None
    age = max(reference_year - year, 1)
    expected = age * KM_PER_YEAR
    ratio = kms / expected
    if ratio > 1.25:
        factor = max(0.80, 1 - (ratio - 1.25) * 0.15)
        return factor, f"high mileage ({kms:,} km, ~{expected:,} expected): {factor - 1:+.0%}"
    if ratio < 0.75:
        factor = min(1.10, 1 + (0.75 - ratio) * 0.15)
        return factor, f"low mileage ({kms:,} km, ~{expected:,} expected): {factor - 1:+.0%}"
    return 1.0, None


def _distance_factor(distance_km: float | None) -> tuple[float, str | None]:
    """Weight a deal down the further the car is from the origin (travel cost)."""
    if distance_km is None or distance_km <= FREE_DISTANCE_KM:
        return 1.0, None
    over = distance_km - FREE_DISTANCE_KM
    factor = max(1 - MAX_DISTANCE_PENALTY, 1 - (over / 100) * DISTANCE_PENALTY_PER_100KM)
    return factor, f"{distance_km:.0f} km away: {factor - 1:+.0%}"


def _condition_multiplier(
    analysis: Analysis | None,
    kms: int | None,
    year: int | None,
    reference_year: int,
    distance_km: float | None,
) -> tuple[float, list[str]]:
    """Multiplicative, explainable adjustments from the grounded analysis fields."""
    multiplier = 1.0
    reasons: list[str] = []

    def apply(factor: float, reason: str) -> None:
        nonlocal multiplier
        multiplier *= factor
        reasons.append(reason)

    if analysis is not None:
        # The mission targets private sellers, so a dealer is penalised.
        if analysis.is_dealer:
            apply(0.90, "dealer, not a private seller: -10%")
        if analysis.condition.accident_history:
            apply(0.85, "accident or bodywork history: -15%")
        if analysis.condition.paint_issues:
            apply(0.96, "paint issues mentioned: -4%")
        if analysis.iuc_status == "pending":
            apply(0.98, "IUC road tax pending: -2%")
        # Belt and inspection are advisory (the model is least reliable here).
        if analysis.maintenance.timing_belt_done:
            apply(1.03, "timing belt done: +3%")
        if analysis.maintenance.ipo_ok:
            apply(1.02, "inspection valid: +2%")

    factor, reason = _mileage_factor(kms, year, reference_year)
    if reason is not None:
        apply(factor, reason)

    distance_f, distance_reason = _distance_factor(distance_km)
    if distance_reason is not None:
        apply(distance_f, distance_reason)

    return multiplier, reasons


def _confidence(benchmark: Benchmark, resolved: ResolvedVehicle) -> float:
    sample = min(benchmark.sample_size, 50) / 50
    return round(sample * (0.5 + 0.5 * resolved.coverage), 2)


def score_from_parts(
    listing: Listing,
    analysis: Analysis | None,
    resolved: ResolvedVehicle,
    benchmark: Benchmark | None,
    *,
    kms: int | None,
    reference_year: int,
    distance_km: float | None = None,
) -> DealScore:
    """Compute a :class:`DealScore` from already-resolved parts (no provider call).

    ``kms`` is the authoritative mileage after all sources (details, prose, LLM,
    OCR); the caller resolves it so the score matches what was stored.
    ``distance_km`` is the distance from the origin, used to weight the deal.
    """
    base = DealScore(
        listing_id=listing.id,
        status=ScoreStatus.SCORED,
        price_eur=listing.price_eur,
        is_dealer=analysis.is_dealer if analysis else None,
        kms=kms,
        distance_km=distance_km,
    )

    if analysis is not None and not analysis.is_vehicle:
        return base.model_copy(update={"status": ScoreStatus.NON_VEHICLE})
    if benchmark is None:
        return base.model_copy(update={"status": ScoreStatus.NO_BENCHMARK})
    if listing.price_eur is None:
        return base.model_copy(update={"status": ScoreStatus.NO_PRICE})

    placeholder_ceiling = max(
        PLACEHOLDER_PRICE_FLOOR, benchmark.median_eur * PLACEHOLDER_PRICE_RATIO
    )
    if listing.price_eur < placeholder_ceiling:
        return base.model_copy(
            update={
                "status": ScoreStatus.NO_PRICE,
                "benchmark_median": benchmark.median_eur,
                "reasons": [f"price {listing.price_eur} looks like a placeholder, not an offer"],
            }
        )

    base_ratio = benchmark.median_eur / listing.price_eur
    multiplier, reasons = _condition_multiplier(
        analysis, kms, resolved.year, reference_year, distance_km
    )
    confidence = _confidence(benchmark, resolved)
    if base_ratio > SUSPICIOUS_RATIO:
        confidence = min(confidence, SUSPICIOUS_CONFIDENCE_CAP)
        reasons.insert(0, "far below market — verify (salvage, wrong variant, or missing detail)")
    return base.model_copy(
        update={
            "benchmark_median": benchmark.median_eur,
            "base_ratio": round(base_ratio, 3),
            "condition_multiplier": round(multiplier, 3),
            "score": round(base_ratio * multiplier, 3),
            "confidence": confidence,
            "reasons": reasons,
        }
    )


def score_listing(
    listing: Listing,
    analysis: Analysis | None,
    provider: BenchmarkProvider,
    *,
    reference_year: int | None = None,
    distance_km: float | None = None,
) -> DealScore:
    """Resolve identity, look up a benchmark, and score one listing."""
    ref = reference_year if reference_year is not None else _reference_year()
    resolved = resolve_identity(listing, analysis)
    key = resolved.key
    benchmark = provider.lookup(key, resolved.year) if key is not None else None
    kms, _ = resolve_kms(listing, analysis, None)
    return score_from_parts(
        listing, analysis, resolved, benchmark, kms=kms, reference_year=ref, distance_km=distance_km
    )

from __future__ import annotations

from autosieve.benchmark import Benchmark, SeedBenchmarkProvider
from autosieve.identity import resolve_identity
from autosieve.models import Analysis, Condition, Listing, Maintenance, VehicleIdentity, resolve_kms
from autosieve.scoring import ScoreStatus, score_from_parts, score_listing

REF = 2026


def listing(**overrides: object) -> Listing:
    base: dict[str, object] = {
        "id": "1234567890",
        "url": "https://www.facebook.com/marketplace/item/1234567890/",
        "title": "Renault Clio",
        "price_eur": 8000,
        "year": 2016,
        "fuel": "gasoleo",
    }
    base.update(overrides)
    return Listing.model_validate(base)


def analysis(**vehicle: object) -> Analysis:
    return Analysis(
        is_vehicle=True, vehicle=VehicleIdentity(make="Renault", model="Clio", **vehicle)
    )


def bench(**overrides: object) -> Benchmark:
    base: dict[str, object] = {
        "make": "Renault",
        "model": "Clio",
        "fuel": "gasoleo",
        "year_from": 2013,
        "year_to": 2019,
        "median_eur": 9500,
        "sample_size": 50,
    }
    base.update(overrides)
    return Benchmark.model_validate(base)


def score(lst: Listing, a: Analysis | None, b: Benchmark | None, **kw: object):
    resolved = resolve_identity(lst, a)
    kms, _ = resolve_kms(lst, a, None)
    return score_from_parts(lst, a, resolved, b, kms=kms, reference_year=REF)


def test_below_market_scores_above_one() -> None:
    # 9500 median / 8000 price = 1.19; mileage unknown, no condition flags.
    result = score(listing(kms=None), analysis(), bench())
    assert result.status is ScoreStatus.SCORED
    assert result.base_ratio == 1.188
    assert result.condition_multiplier == 1.0
    assert result.score == 1.188
    assert result.confidence > 0
    assert result.is_scored


def test_dealer_penalty_and_reason() -> None:
    a = Analysis(
        is_vehicle=True, is_dealer=True, vehicle=VehicleIdentity(make="Renault", model="Clio")
    )
    result = score(listing(kms=None), a, bench())
    assert result.condition_multiplier == 0.90
    assert result.score == round(1.188 * 0.90, 3)
    assert any("dealer" in r for r in result.reasons)


def test_accident_and_paint_stack() -> None:
    a = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio"),
        condition=Condition(accident_history=True, paint_issues=True),
    )
    result = score(listing(kms=None), a, bench())
    assert result.condition_multiplier == round(0.85 * 0.96, 3)
    assert len(result.reasons) == 2


def test_high_mileage_penalty() -> None:
    # 2016 car at reference 2026 = 10 years, ~150k expected; 260k is high.
    result = score(listing(kms=260_000), analysis(), bench())
    assert result.condition_multiplier < 1.0
    assert any("high mileage" in r for r in result.reasons)


def test_low_mileage_bonus() -> None:
    result = score(listing(kms=60_000), analysis(), bench())
    assert result.condition_multiplier > 1.0
    assert any("low mileage" in r for r in result.reasons)


def test_belt_and_inspection_are_small_bonuses() -> None:
    a = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio"),
        maintenance=Maintenance(timing_belt_done=True, ipo_ok=True),
    )
    result = score(listing(kms=None), a, bench())
    assert result.condition_multiplier == round(1.03 * 1.02, 3)


def test_non_vehicle_is_not_scored() -> None:
    a = Analysis(is_vehicle=False, vehicle=VehicleIdentity(make="Renault", model="Clio"))
    result = score(listing(), a, bench())
    assert result.status is ScoreStatus.NON_VEHICLE
    assert result.score is None


def test_placeholder_price_is_not_scored() -> None:
    # 10 EUR against a 9500 median is a placeholder, not a real offer.
    result = score(listing(price_eur=10), analysis(), bench())
    assert result.status is ScoreStatus.NO_PRICE
    assert result.score is None
    assert any("placeholder" in r for r in result.reasons)


def test_missing_price_is_not_scored() -> None:
    result = score(listing(price_eur=None), analysis(), bench())
    assert result.status is ScoreStatus.NO_PRICE


def test_no_benchmark_is_not_scored() -> None:
    result = score(listing(), analysis(), None)
    assert result.status is ScoreStatus.NO_BENCHMARK
    assert result.score is None


def test_confidence_reflects_sample_and_coverage() -> None:
    full = score(listing(kms=None), analysis(year=2016, fuel="gasoleo"), bench(sample_size=50))
    thin = score(listing(kms=None), analysis(), bench(sample_size=5))
    assert full.confidence > thin.confidence
    assert 0 <= thin.confidence <= 1


def test_score_listing_end_to_end_with_provider() -> None:
    provider = SeedBenchmarkProvider([bench()])
    result = score_listing(listing(kms=None), analysis(), provider, reference_year=REF)
    assert result.is_scored
    assert result.benchmark_median == 9500


def test_score_listing_unknown_model_has_no_benchmark() -> None:
    provider = SeedBenchmarkProvider([bench()])
    unknown = Analysis(is_vehicle=True, vehicle=VehicleIdentity(make="Lada", model="Niva"))
    result = score_listing(listing(title="Lada Niva"), unknown, provider, reference_year=REF)
    assert result.status is ScoreStatus.NO_BENCHMARK


def test_unknown_year_is_not_scored_against_a_band() -> None:
    # No year on the page or from the model: valuing against a specific age band
    # would produce a wild ratio, so there is effectively no benchmark.
    provider = SeedBenchmarkProvider([bench()])
    no_year = Listing(
        id="9999999999",
        url="https://www.facebook.com/marketplace/item/9999999999/",
        title="Renault Clio",
        price_eur=2750,
    )
    a = Analysis(is_vehicle=True, vehicle=VehicleIdentity(make="Renault", model="Clio"))
    result = score_listing(no_year, a, provider, reference_year=REF)
    assert result.status is ScoreStatus.NO_BENCHMARK


def test_suspicious_ratio_is_flagged_and_confidence_capped() -> None:
    # An in-band match priced far below market: kept but flagged, not trusted.
    result = score(listing(price_eur=2500), analysis(), bench(median_eur=9500, sample_size=50))
    assert result.base_ratio > 2.2
    assert result.confidence <= 0.35
    assert any("far below market" in r for r in result.reasons)

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autosieve.benchmark import Benchmark, SeedBenchmarkProvider
from autosieve.identity import VehicleKey


def bench(**overrides: object) -> Benchmark:
    base: dict[str, object] = {
        "make": "Renault",
        "model": "Clio",
        "fuel": "gasoleo",
        "year_from": 2013,
        "year_to": 2019,
        "median_eur": 9500,
        "sample_size": 60,
    }
    base.update(overrides)
    return Benchmark.model_validate(base)


def test_benchmark_key_is_canonical() -> None:
    b = bench(make="Renault", model="Clio 1.5 dCi")
    assert b.key == VehicleKey(make="renault", model="clio", fuel="gasoleo")


def test_benchmark_rejects_reversed_years_and_percentiles() -> None:
    with pytest.raises(ValidationError, match="year_from"):
        bench(year_from=2019, year_to=2013)
    with pytest.raises(ValidationError, match="p25_eur"):
        bench(p25_eur=12000, p75_eur=8000)


def test_covers_year() -> None:
    b = bench()
    assert b.covers_year(2015)
    assert not b.covers_year(2011)
    assert not b.covers_year(None)  # unknown year is not valued against a band


def test_lookup_matches_make_model_year() -> None:
    provider = SeedBenchmarkProvider([bench()])
    key = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    assert provider.lookup(key, 2015) is not None
    assert provider.lookup(key, 2005) is None  # outside the band
    assert provider.lookup(VehicleKey(make="ford", model="focus"), 2015) is None


def test_lookup_prefers_exact_fuel() -> None:
    diesel = bench(fuel="gasoleo", median_eur=9500)
    petrol = bench(fuel="gasolina", median_eur=9000)
    agnostic = bench(fuel=None, median_eur=9200)
    provider = SeedBenchmarkProvider([petrol, agnostic, diesel])

    key = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    assert provider.lookup(key, 2015).median_eur == 9500  # the diesel one


def test_lookup_excludes_wrong_fuel_but_allows_agnostic() -> None:
    petrol = bench(fuel="gasolina", median_eur=9000)
    agnostic = bench(fuel=None, median_eur=9200)
    provider = SeedBenchmarkProvider([petrol, agnostic])

    key = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    # No diesel benchmark exists, so the fuel-agnostic one is used, not the petrol one.
    assert provider.lookup(key, 2015).median_eur == 9200


def test_lookup_unknown_fuel_key_takes_best_sampled() -> None:
    small = bench(fuel="gasoleo", median_eur=9500, sample_size=10)
    big = bench(fuel="gasolina", median_eur=9000, sample_size=80)
    provider = SeedBenchmarkProvider([small, big])
    key = VehicleKey(make="renault", model="clio", fuel=None)
    assert provider.lookup(key, 2015).median_eur == 9000  # larger sample wins


def test_packaged_seed_loads_and_matches_a_known_model() -> None:
    provider = SeedBenchmarkProvider.default()
    assert provider.size > 10
    key = VehicleKey(make="peugeot", model="5008", fuel="gasoleo")
    result = provider.lookup(key, 2023)
    assert result is not None
    assert result.median_eur > 0
    assert result.source == "seed"

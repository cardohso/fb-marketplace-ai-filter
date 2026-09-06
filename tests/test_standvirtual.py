from __future__ import annotations

import pytest

from autosieve.benchmark.standvirtual import (
    STANDVIRTUAL_SAMPLE,
    StandvirtualBenchmarkProvider,
    Valuation,
    expected_kms,
    map_fuel,
    parse_valuation,
)
from autosieve.identity import VehicleKey


@pytest.mark.parametrize(
    ("fuel", "expected"),
    [
        ("gasoleo", "Diesel"),
        ("gasolina", "Gasolina"),
        ("eletrico", "Elétrico"),
        ("hibrido", "Gasolina/Elétrico"),
        ("gpl", "GPL"),
        (None, None),
        ("outro", None),
    ],
)
def test_map_fuel(fuel: str | None, expected: str | None) -> None:
    assert map_fuel(fuel) == expected


def test_expected_kms() -> None:
    assert expected_kms(2016, 2026) == 150_000
    assert expected_kms(2026, 2026) == 15_000  # age floored at 1 year
    assert expected_kms(2030, 2026) == 15_000


def test_parse_valuation_space_separated() -> None:
    v = parse_valuation("A sua avaliação: 12 550 EUR - 15 350 EUR para este carro")
    assert v == Valuation(price_min=12_550, price_max=15_350)
    assert v.avg == 13_950


def test_parse_valuation_ignores_the_example_price() -> None:
    # The page prints "EUR 26,140 - EUR 31,050" as a static example; the real
    # result follows. Only the real one must be returned.
    text = "Exemplo: EUR 26,140 - EUR 31,050. Resultado: 9 000 EUR - 11 000 EUR"
    assert parse_valuation(text) == Valuation(9_000, 11_000)


def test_parse_valuation_none_when_absent_or_invalid() -> None:
    assert parse_valuation("Sem resultado disponível") is None
    assert parse_valuation("EUR 26,140 - EUR 31,050") is None  # only the example


class FakeValuator:
    def __init__(self, result: Valuation | None) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def valuate(
        self,
        *,
        make: str,
        model: str,
        year: int,
        fuel: str | None,
        gearbox: str | None,
        kms: int,
    ) -> Valuation | None:
        self.calls.append({"make": make, "model": model, "year": year, "fuel": fuel, "kms": kms})
        return self.result


def test_provider_wraps_a_valuation_into_a_benchmark() -> None:
    valuator = FakeValuator(Valuation(9_000, 11_000))
    provider = StandvirtualBenchmarkProvider(valuator, reference_year=2026)
    key = VehicleKey(make="renault", model="clio", fuel="gasoleo")

    benchmark = provider.lookup(key, 2016)

    assert benchmark is not None
    assert benchmark.median_eur == 10_000
    assert benchmark.p25_eur == 9_000
    assert benchmark.p75_eur == 11_000
    assert benchmark.source == "standvirtual"
    assert benchmark.sample_size == STANDVIRTUAL_SAMPLE
    assert benchmark.year_from == benchmark.year_to == 2016
    # It queried at the mileage expected for a 10-year-old car, not the default.
    assert valuator.calls[0]["kms"] == 150_000


def test_provider_returns_none_without_year_or_valuation() -> None:
    key = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    assert (
        StandvirtualBenchmarkProvider(FakeValuator(Valuation(1, 2)), reference_year=2026).lookup(
            key, None
        )
        is None
    )
    assert (
        StandvirtualBenchmarkProvider(FakeValuator(None), reference_year=2026).lookup(key, 2016)
        is None
    )

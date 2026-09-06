from __future__ import annotations

import pytest

from autosieve.parsing.km import find_km_values, first_km, largest_km


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Percorreu 150.000 km", 150_000),
        ("com 150 000 km", 150_000),
        ("150000km", 150_000),
        ("150.000 kms reais", 150_000),
        ("apenas 87 mil km", 87_000),
        ("120 mil kms", 120_000),
        ("Conduzido 223.184 km", 223_184),
        ("12.000 quilómetros", 12_000),
    ],
)
def test_first_km(text: str, expected: int) -> None:
    assert first_km(text) == expected


def test_english_thousands_comma_is_a_known_limitation() -> None:
    # Comma-grouped English numbers are ambiguous with Portuguese decimals and
    # Marketplace PT never renders them, so "45,000 km" reads as 45 km.
    assert first_km("Driven 45,000 km") == 45


def test_year_before_mileage_is_not_swallowed() -> None:
    # Regression: the old pattern allowed whitespace inside the number and read
    # "2019 12.000" as 201912000, then rejected it.
    assert first_km("Renault Clio 2019 12.000 km") == 12_000


def test_speed_is_not_mileage() -> None:
    assert find_km_values("velocidade máxima 180 km/h") == []
    assert first_km("180 km/h, 90.000 km") == 90_000


def test_engine_size_is_not_mileage() -> None:
    assert first_km("1.6 TDI 150.000 km") == 150_000


def test_rejects_beyond_maximum() -> None:
    assert first_km("2.000.000 km") is None


def test_ocr_largest_requires_four_digits() -> None:
    # A dashboard photo: the dial reads up to 180 km, the trip shows 312 km,
    # the odometer shows 187.432 km. Only the odometer is acceptable.
    text = "0 20 40 180 km 312 km 187.432 km"
    assert largest_km(text) == 187_432
    assert largest_km("180 km") is None


def test_empty_inputs() -> None:
    assert first_km(None) is None
    assert first_km("") is None
    assert largest_km("sem quilómetros indicados") is None

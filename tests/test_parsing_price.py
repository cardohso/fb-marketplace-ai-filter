from __future__ import annotations

import pytest

from autosieve.parsing.price import parse_price


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.500 €", 12_500),
        ("€12,500", 12_500),
        ("12 500 €", 12_500),
        ("1.250€", 1_250),
        ("12.500,00 €", 12_500),
        ("Preço: 9.900 €", 9_900),
        ("950 €", 950),
        ("150000€", 150_000),
        ("€ 4.990 · Lisboa", 4_990),
    ],
)
def test_parses_common_formats(text: str, expected: int) -> None:
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["Grátis", "", None, "0 €", "Preço a combinar", "€"])
def test_unparseable_is_none(text: str | None) -> None:
    assert parse_price(text) is None


def test_absurd_values_are_rejected() -> None:
    assert parse_price("99.999.999.999 €") is None


def test_no_break_space_thousands_separator() -> None:
    # Facebook renders "12 500 €" with U+00A0 between the groups.
    assert parse_price("12\u00a0500\u00a0€") == 12_500
    assert parse_price("12\u202f500 €") == 12_500

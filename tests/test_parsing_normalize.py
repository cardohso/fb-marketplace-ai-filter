from __future__ import annotations

import pytest

from autosieve.parsing.normalize import fold, normalize_fuel, normalize_gearbox


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Gasóleo", "gasoleo"),
        ("Diesel", "gasoleo"),
        ("1.6 TDI", "gasoleo"),
        ("Gasolina", "gasolina"),
        ("Petrol", "gasolina"),
        ("Híbrido Plug-in (Gasolina)", "hibrido"),
        ("Elétrico", "eletrico"),
        ("Electric", "eletrico"),
        ("GPL", "gpl"),
        ("gasoleo", "gasoleo"),
        ("Madeira", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_fuel(text: str | None, expected: str | None) -> None:
    assert normalize_fuel(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Transmissão manual", "manual"),
        ("Transmissão automática", "automatica"),
        ("Automatic transmission", "automatica"),
        ("DSG", "automatica"),
        ("caixa manual de 6 velocidades", "manual"),
        ("Pele", None),
    ],
)
def test_normalize_gearbox(text: str, expected: str | None) -> None:
    assert normalize_gearbox(text) == expected


def test_fold_strips_accents_and_case() -> None:
    assert fold("  Descrição do Vendedor ") == "descricao do vendedor"

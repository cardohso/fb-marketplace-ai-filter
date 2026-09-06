from __future__ import annotations

import pytest

from autosieve.identity import (
    ResolvedVehicle,
    VehicleKey,
    canonical_make,
    canonical_model,
    resolve_identity,
)
from autosieve.models import Analysis, Listing, VehicleIdentity


def make_listing(**overrides: object) -> Listing:
    base: dict[str, object] = {
        "id": "1234567890",
        "url": "https://www.facebook.com/marketplace/item/1234567890/",
        "title": "Renault Clio",
    }
    base.update(overrides)
    return Listing.model_validate(base)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Renault", "renault"),
        ("Mercedes-Benz", "mercedes benz"),
        ("CITROËN", "citroen"),
        ("  BMW  ", "bmw"),
    ],
)
def test_canonical_make(raw: str, expected: str) -> None:
    assert canonical_make(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Clio", "clio"),
        ("Clio 1.5 dCi Dynamique", "clio dynamique"),
        ("Mégane", "megane"),
        ("Série 3", "serie 3"),
        ("208 1.2 PureTech", "208 puretech"),
        ("A3 1.9 TDI", "a3"),
    ],
)
def test_canonical_model_strips_trim_and_engine(raw: str, expected: str) -> None:
    assert canonical_model(raw) == expected


def test_deterministic_page_facts_beat_the_model() -> None:
    listing = make_listing(year=2015, fuel="gasoleo", gearbox="manual")
    analysis = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(
            make="Renault", model="Clio", year=2011, fuel="gasolina", gearbox="automatica"
        ),
    )
    resolved = resolve_identity(listing, analysis)
    assert resolved.make == "Renault"
    assert resolved.year == 2015  # from the page, not the model's 2011
    assert resolved.fuel == "gasoleo"
    assert resolved.gearbox == "manual"


def test_model_fills_what_the_page_lacks() -> None:
    listing = make_listing()  # no year/fuel/gearbox on the page
    analysis = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio", year=2018, fuel="gasoleo"),
    )
    resolved = resolve_identity(listing, analysis)
    assert (resolved.year, resolved.fuel) == (2018, "gasoleo")


def test_key_requires_make_and_model() -> None:
    assert ResolvedVehicle(make="Renault", model=None).key is None
    assert ResolvedVehicle(make=None, model="Clio").key is None
    key = ResolvedVehicle(make="Renault", model="Clio 1.5 dCi", fuel="gasoleo").key
    assert key == VehicleKey(make="renault", model="clio", fuel="gasoleo")
    assert str(key) == "renault / clio / gasoleo"


def test_coverage_and_identified() -> None:
    full = ResolvedVehicle(make="Renault", model="Clio", year=2018, fuel="gasoleo")
    assert full.coverage == 1.0
    assert full.is_identified

    partial = ResolvedVehicle(make="Renault", model="Clio")
    assert partial.coverage == 0.5
    assert partial.is_identified

    empty = ResolvedVehicle()
    assert empty.coverage == 0.0
    assert not empty.is_identified


def test_resolve_without_analysis() -> None:
    listing = make_listing(year=2015, fuel="gasoleo")
    resolved = resolve_identity(listing, None)
    assert resolved.make is None
    assert resolved.year == 2015
    assert not resolved.is_identified


def test_vehicle_key_is_hashable() -> None:
    a = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    b = VehicleKey(make="renault", model="clio", fuel="gasoleo")
    assert a == b
    assert len({a, b}) == 1

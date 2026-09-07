from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autosieve.models import Analysis, Listing, VehicleIdentity
from autosieve.watch import Watch, load_watches, save_watches, watch_matches


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


def analysis(is_dealer: bool | None = None, **vehicle: object) -> Analysis:
    return Analysis(
        is_vehicle=True,
        is_dealer=is_dealer,
        vehicle=VehicleIdentity(make="Renault", model="Clio", **vehicle),
    )


def clio_watch(**overrides: object) -> Watch:
    base: dict[str, object] = {"name": "clio", "make": "Renault", "model": "Clio"}
    base.update(overrides)
    return Watch.model_validate(base)


# ── model ────────────────────────────────────────────────────────────────────


def test_watch_rejects_reversed_bounds() -> None:
    with pytest.raises(ValidationError, match="year_min"):
        clio_watch(year_min=2018, year_max=2013)
    with pytest.raises(ValidationError, match="price_min"):
        clio_watch(price_min=10000, price_max=5000)


def test_watch_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Watch.model_validate({"name": "x", "colour": "red"})


def test_describe() -> None:
    w = clio_watch(year_min=2013, year_max=2018, price_max=11000, km_max=120000, private_only=True)
    text = w.describe()
    assert "Renault Clio" in text
    assert "2013-2018" in text
    assert "private" in text


# ── matching ─────────────────────────────────────────────────────────────────


def test_matches_when_all_criteria_hold() -> None:
    w = clio_watch(year_min=2013, year_max=2018, price_max=11000, km_max=150000, fuel="gasoleo")
    assert watch_matches(w, listing(kms=90000), analysis()).matched


def test_make_and_model_must_match() -> None:
    assert not watch_matches(clio_watch(model="Megane"), listing(), analysis()).matched
    assert not watch_matches(clio_watch(make="Peugeot"), listing(), analysis()).matched


def test_unknown_identity_does_not_match_a_named_model() -> None:
    bare = Analysis(is_vehicle=True, vehicle=VehicleIdentity())
    result = watch_matches(clio_watch(), listing(title="Carro"), bare)
    assert not result.matched
    assert "unknown" in result.reason


def test_price_and_year_bounds_exclude() -> None:
    assert not watch_matches(
        clio_watch(price_max=7000), listing(price_eur=8000), analysis()
    ).matched
    assert not watch_matches(clio_watch(year_min=2018), listing(year=2016), analysis()).matched


def test_unknown_numeric_data_does_not_exclude() -> None:
    # No km on the listing, but km_max is set: it should still match (forgiving).
    w = clio_watch(km_max=100000)
    assert watch_matches(
        w,
        listing(kms=None),
        Analysis(is_vehicle=True, vehicle=VehicleIdentity(make="Renault", model="Clio")),
    ).matched
    # No price, but price_max set: still matches.
    assert watch_matches(clio_watch(price_max=5000), listing(price_eur=None), analysis()).matched


def test_private_only_excludes_dealers() -> None:
    w = clio_watch(private_only=True)
    assert not watch_matches(w, listing(), analysis(is_dealer=True)).matched
    assert watch_matches(w, listing(), analysis(is_dealer=False)).matched
    assert watch_matches(w, listing(), analysis(is_dealer=None)).matched  # unknown is kept


def test_disabled_watch_never_matches() -> None:
    assert not watch_matches(clio_watch(enabled=False), listing(), analysis()).matched


def test_fuel_and_gearbox_filter() -> None:
    assert not watch_matches(
        clio_watch(fuel="gasolina"), listing(fuel="gasoleo"), analysis()
    ).matched
    assert watch_matches(clio_watch(fuel="gasoleo"), listing(fuel="gasoleo"), analysis()).matched


# ── config file ──────────────────────────────────────────────────────────────


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "watches.json"
    watches = [clio_watch(year_min=2013, price_max=11000), Watch(name="golf", model="Golf")]
    save_watches(watches, path)
    loaded = load_watches(path)
    assert [w.name for w in loaded] == ["clio", "golf"]
    assert loaded[0].price_max == 11000
    assert loaded[1].model == "Golf"


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_watches(tmp_path / "nope.json") == []


def test_load_rejects_duplicate_names(tmp_path: Path) -> None:
    path = tmp_path / "watches.json"
    save_watches([clio_watch(), Watch(name="clio", model="Golf")], path)
    with pytest.raises(ValueError, match="duplicate"):
        load_watches(path)


def test_non_vehicle_never_matches() -> None:
    # A listing classified as parts/accessory must not match, even a broad watch.
    parts = Analysis(is_vehicle=False, vehicle=VehicleIdentity(make="Renault", model="Clio"))
    assert not watch_matches(clio_watch(), listing(), parts).matched
    assert not watch_matches(Watch(name="any"), listing(), parts).matched

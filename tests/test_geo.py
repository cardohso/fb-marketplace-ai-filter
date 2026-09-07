from __future__ import annotations

import pytest

from autosieve.geo import FARO, default_gazetteer, geocode, haversine_km
from autosieve.geo.gazetteer import Gazetteer


def test_haversine_known_distances() -> None:
    lisboa = (38.7223, -9.1393)
    # Lisbon to Faro is about 217 km as the crow flies (road distance is longer).
    assert 200 < haversine_km(lisboa, FARO) < 230
    assert haversine_km(FARO, FARO) == pytest.approx(0.0, abs=1e-6)


def test_geocode_town_first_then_district() -> None:
    # A known town resolves precisely.
    assert geocode("Loulé, Faro") == pytest.approx((37.1378, -8.0227))
    # An unknown town falls back to its district centroid.
    coords = geocode("Aldeia Desconhecida, Santarém")
    assert coords == pytest.approx((39.2362, -8.6859))


def test_geocode_handles_accents_and_case() -> None:
    assert geocode("ODIVELAS, lisboa") == pytest.approx((38.7929, -9.1836))
    assert geocode("Setúbal, Portugal") == pytest.approx((38.5244, -8.8882))


def test_geocode_unknown_is_none() -> None:
    assert geocode("Nowhere, Atlantis") is None
    assert geocode(None) is None
    assert geocode("") is None


def test_distance_to_faro_for_a_local_and_a_far_listing() -> None:
    loule = geocode("Loulé, Faro")
    lisboa = geocode("Lisboa, Lisboa")
    assert loule is not None and lisboa is not None
    assert haversine_km(loule, FARO) < 25  # Loulé is very close to Faro
    assert haversine_km(lisboa, FARO) > 200


def test_packaged_gazetteer_covers_all_districts() -> None:
    g = default_gazetteer()
    assert len(g.districts) >= 18
    assert "faro" in g.districts
    assert g.towns  # and has towns


def test_custom_gazetteer() -> None:
    g = Gazetteer(towns={"x": (0.0, 0.0)}, districts={})
    assert g.resolve("X") == (0.0, 0.0)
    assert g.resolve("y") is None

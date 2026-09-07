from __future__ import annotations

import pytest

from autosieve.models import Analysis, AnalysisRecord, Listing, VehicleIdentity
from autosieve.storage import Store
from autosieve.watch import Watch
from autosieve.watch.events import AlertKind, detect_events


def add(store: Store, listing_id: str, price: int, model: str = "Clio") -> Listing:
    listing = Listing(
        id=listing_id,
        url=f"https://www.facebook.com/marketplace/item/{listing_id}/",
        title=f"Renault {model}",
        price_eur=price,
        year=2016,
        fuel="gasoleo",
    )
    store.upsert_listing(listing)
    store.save_analysis(
        AnalysisRecord(
            listing_id=listing_id,
            model="test",
            analysis=Analysis(
                is_vehicle=True, vehicle=VehicleIdentity(make="Renault", model=model)
            ),
        )
    )
    return listing


@pytest.fixture
def store() -> Store:
    with Store(":memory:") as s:
        yield s


CLIO = Watch(name="clio", make="Renault", model="Clio", price_max=15000)


def test_new_listing_fires_a_new_event(store: Store) -> None:
    add(store, "1111111111", 9000)
    events = detect_events(store, [CLIO], new_ids={"1111111111"})
    assert len(events) == 1
    assert events[0].kind is AlertKind.NEW
    assert events[0].price_eur == 9000


def test_new_event_does_not_repeat(store: Store) -> None:
    add(store, "1111111111", 9000)
    detect_events(store, [CLIO], new_ids={"1111111111"})
    # A later run where the listing is no longer new and unchanged: no event.
    again = detect_events(store, [CLIO], new_ids=set())
    assert again == []


def test_pre_existing_match_is_baselined_not_alerted(store: Store) -> None:
    # The listing is already in the store (not new this run) when the watch runs.
    add(store, "1111111111", 9000)
    events = detect_events(store, [CLIO], new_ids=set())
    assert events == []
    # It is now baselined, so a later real drop is detected.
    add(store, "1111111111", 8000)
    dropped = detect_events(store, [CLIO], new_ids=set())
    assert len(dropped) == 1
    assert dropped[0].kind is AlertKind.PRICE_DROP


def test_material_price_drop_fires_once(store: Store) -> None:
    add(store, "1111111111", 10000)
    detect_events(store, [CLIO], new_ids={"1111111111"})  # baseline via new event
    add(store, "1111111111", 9000)  # 1000 EUR drop, material
    events = detect_events(store, [CLIO], new_ids=set())
    assert len(events) == 1
    assert events[0].kind is AlertKind.PRICE_DROP
    assert events[0].previous_price == 10000
    assert events[0].drop_eur == 1000
    # Same price again: no repeat.
    assert detect_events(store, [CLIO], new_ids=set()) == []


def test_immaterial_drop_does_not_fire(store: Store) -> None:
    add(store, "1111111111", 10000)
    detect_events(store, [CLIO], new_ids={"1111111111"})
    add(store, "1111111111", 9950)  # 50 EUR, below the floor
    assert detect_events(store, [CLIO], new_ids=set()) == []


def test_price_rise_does_not_fire_but_updates_baseline(store: Store) -> None:
    add(store, "1111111111", 9000)
    detect_events(store, [CLIO], new_ids={"1111111111"})
    add(store, "1111111111", 9500)  # rise
    assert detect_events(store, [CLIO], new_ids=set()) == []
    # From the new higher baseline, a drop back to 9000 is now material.
    add(store, "1111111111", 9000)
    events = detect_events(store, [CLIO], new_ids=set())
    assert len(events) == 1 and events[0].previous_price == 9500


def test_non_matching_listing_is_ignored(store: Store) -> None:
    add(store, "2222222222", 9000, model="Megane")
    assert detect_events(store, [CLIO], new_ids={"2222222222"}) == []


def test_dry_run_persists_nothing(store: Store) -> None:
    add(store, "1111111111", 9000)
    first = detect_events(store, [CLIO], new_ids={"1111111111"}, persist=False)
    assert len(first) == 1
    # Nothing was written, so the same event is found again.
    second = detect_events(store, [CLIO], new_ids={"1111111111"}, persist=False)
    assert len(second) == 1

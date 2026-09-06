from __future__ import annotations

import csv
from pathlib import Path

import pytest

from autosieve.models import Analysis, AnalysisRecord, Listing
from autosieve.storage import EXPORT_COLUMNS, Store, UpsertOutcome, export_csv, sanitize_cell


def make_listing(listing_id: str = "1234567890", **overrides: object) -> Listing:
    base: dict[str, object] = {
        "id": listing_id,
        "url": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        "title": "Renault Clio 1.5 dCi 2019",
        "price_eur": 12_500,
        "price_raw": "12.500 €",
        "description": "Carro de particular.",
        "details": ("Percorreu 87.000 km", "Gasóleo"),
        "kms": 87_000,
        "fuel": "gasoleo",
        "year": 2019,
        "image_urls": ("https://scontent.fbcdn.net/a.jpg", "https://scontent.fbcdn.net/b.jpg"),
        "city": "lisbon",
    }
    base.update(overrides)
    return Listing.model_validate(base)


@pytest.fixture
def store() -> Store:
    with Store(":memory:") as s:
        yield s


def test_upsert_new_then_unchanged_then_price_change(store: Store) -> None:
    listing = make_listing()
    assert store.upsert_listing(listing) is UpsertOutcome.NEW
    assert store.upsert_listing(listing) is UpsertOutcome.UNCHANGED
    cheaper = make_listing(price_eur=11_900, price_raw="11.900 €")
    assert store.upsert_listing(cheaper) is UpsertOutcome.UPDATED

    history = [price for _, price in store.price_history(listing.id)]
    assert history == [12_500, 11_900]
    assert store.counts()["listings"] == 1


def test_listing_round_trips(store: Store) -> None:
    listing = make_listing()
    store.upsert_listing(listing)
    loaded = store.get_listing(listing.id)
    assert loaded is not None
    assert loaded.details == listing.details
    assert loaded.image_urls == listing.image_urls
    assert loaded.kms == 87_000
    assert loaded.scraped_at == listing.scraped_at
    assert store.get_listing("0000000000") is None


def test_pending_analysis_logic(store: Store) -> None:
    a, b = make_listing("1111111111"), make_listing("2222222222")
    store.upsert_listing(a)
    store.upsert_listing(b)
    assert [x.id for x in store.listings_pending_analysis("llama3.1")] == [a.id, b.id]

    store.save_analysis(
        AnalysisRecord(listing_id=a.id, model="llama3.1", analysis=Analysis(is_vehicle=True))
    )
    store.save_analysis(AnalysisRecord(listing_id=b.id, model="llama3.1", error="Ollama down"))

    assert [x.id for x in store.listings_pending_analysis("llama3.1")] == []
    assert [x.id for x in store.listings_pending_analysis("llama3.1", retry_failed=True)] == [b.id]
    # A different model means every listing needs a fresh analysis.
    assert len(store.listings_pending_analysis("qwen2.5")) == 2


def test_analysis_round_trip_and_counts(store: Store) -> None:
    listing = make_listing()
    store.upsert_listing(listing)
    analysis = Analysis.model_validate(
        {
            "is_vehicle": True,
            "is_dealer": True,
            "vehicle": {"make": "Renault", "model": "Clio", "fuel": "gasoleo"},
            "iuc_status": "ok",
            "notes": "Dealer stock.",
        }
    )
    record = AnalysisRecord(
        listing_id=listing.id, model="llama3.1", analysis=analysis, kms=87_000, kms_source="details"
    )
    store.save_analysis(record)

    loaded = store.get_analysis(listing.id)
    assert loaded is not None and loaded.ok
    assert loaded.analysis == analysis
    assert loaded.kms_source == "details"
    counts = store.counts()
    assert counts == {"listings": 1, "analysed": 1, "failed": 0, "non_vehicles": 0, "dealers": 1}


def test_sanitize_cell() -> None:
    assert sanitize_cell(None) == ""
    assert sanitize_cell(True) == "true"
    assert sanitize_cell(87_000) == "87000"
    assert sanitize_cell('=HYPERLINK("http://evil")') == '\'=HYPERLINK("http://evil")'
    assert sanitize_cell("@SUM(1)") == "'@SUM(1)"
    assert sanitize_cell("-5 km") == "'-5 km"
    assert sanitize_cell("Carro impecável") == "Carro impecável"


def test_export_csv(store: Store, tmp_path: Path) -> None:
    car = make_listing("1111111111", description="=CMD()|' /C calc'!A0 carro impecável")
    parts = make_listing("2222222222", title="Jantes 17", kms=None, description="4 jantes")
    pending = make_listing("3333333333", kms=None)
    for listing in (car, parts, pending):
        store.upsert_listing(listing)
    store.save_analysis(
        AnalysisRecord(
            listing_id=car.id,
            model="llama3.1",
            analysis=Analysis.model_validate(
                {"is_vehicle": True, "is_dealer": False, "vehicle": {"make": "Renault"}}
            ),
            kms=87_000,
            kms_source="details",
        )
    )
    store.save_analysis(
        AnalysisRecord(listing_id=parts.id, model="llama3.1", analysis=Analysis(is_vehicle=False))
    )

    out = tmp_path / "out" / "vehicles.csv"
    assert export_csv(store, out) == 2  # the parts listing is excluded by default

    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == list(EXPORT_COLUMNS)
    by_id = {row["id"]: row for row in rows}
    assert by_id[car.id]["description"].startswith("'=CMD()")
    assert by_id[car.id]["kms"] == "87000"
    assert by_id[car.id]["llm_is_dealer"] == "false"
    assert by_id[car.id]["llm_make"] == "Renault"
    assert by_id[pending.id]["kms"] == ""  # unknown is empty, never the word "unknown"
    assert by_id[pending.id]["llm_is_vehicle"] == ""

    assert export_csv(store, out, include_non_vehicles=True) == 3

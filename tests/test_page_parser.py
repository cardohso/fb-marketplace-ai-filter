from __future__ import annotations

from pathlib import Path

import pytest

from autosieve.scraper import ListingUnavailableError, parse_listing_html

URL = "https://www.facebook.com/marketplace/item/1234567890/"


def load(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / name).read_text(encoding="utf-8")


def test_full_listing(fixtures_dir: Path) -> None:
    listing = parse_listing_html(load(fixtures_dir, "listing_full.html"), url=URL, city="lisbon")

    assert listing.id == "1234567890"
    assert listing.title == "Renault Clio 1.5 dCi 90cv 2019"
    # The sidebar shows another car's 7.900 € before the title; the real price comes after it.
    assert listing.price_raw == "12.500 €"
    assert listing.price_eur == 12_500
    assert listing.details[:3] == ("Percorreu 87.000 km", "Gasóleo", "Transmissão manual")
    assert listing.kms == 87_000
    assert listing.fuel == "gasoleo"
    assert listing.gearbox == "manual"
    assert listing.year == 2019
    assert listing.description is not None
    assert listing.description.startswith("Carro de particular")
    assert "Ver mais" not in listing.description
    assert "Descrição do vendedor" not in listing.description
    assert listing.city == "lisbon"
    assert listing.location == "Lisboa, Portugal"
    assert listing.is_complete


def test_full_listing_images_are_product_photos_only_and_deduplicated(fixtures_dir: Path) -> None:
    listing = parse_listing_html(load(fixtures_dir, "listing_full.html"), url=URL)
    assert len(listing.image_urls) == 2
    assert all("photo" in url for url in listing.image_urls)
    assert not any("avatar" in url for url in listing.image_urls)


def test_parts_listing_has_no_vehicle_facts(fixtures_dir: Path) -> None:
    listing = parse_listing_html(load(fixtures_dir, "listing_parts.html"), url=URL)
    assert listing.title == "Jantes 17 BMW originais"
    assert listing.price_eur == 350
    # "180 km/h" in the prose is a speed, not mileage, and there is no driven line.
    assert listing.kms is None
    assert listing.fuel is None
    assert listing.gearbox is None
    assert listing.year is None
    assert listing.is_complete


def test_unavailable_listing_raises(fixtures_dir: Path) -> None:
    with pytest.raises(ListingUnavailableError):
        parse_listing_html(load(fixtures_dir, "listing_unavailable.html"), url=URL)


def test_minimal_listing_is_incomplete_but_parsed(fixtures_dir: Path) -> None:
    listing = parse_listing_html(load(fixtures_dir, "listing_minimal.html"), url=URL)
    assert listing.title == "Peugeot 208 1.2 PureTech 2021"
    assert listing.price_eur is None
    assert listing.description is None
    assert listing.kms == 32_000
    assert listing.fuel == "gasolina"
    assert listing.gearbox == "automatica"
    assert listing.year == 2021
    assert not listing.is_complete


def test_requires_item_url() -> None:
    with pytest.raises(ValueError, match="not a Marketplace item URL"):
        parse_listing_html("<html></html>", url="https://www.facebook.com/marketplace/lisbon/")


def test_blank_page_is_incomplete_not_unavailable() -> None:
    listing = parse_listing_html("<html><body></body></html>", url=URL)
    assert listing.title is None
    assert not listing.is_complete

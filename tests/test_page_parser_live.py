"""Parser tests against reduced copies of real Marketplace pages (September 2026).

These fixtures were produced by ``scripts/make_fixture.py`` from pages saved with
``autosieve scrape --debug-html``. They preserve the exact visible text lines of
the live pages, including the sidebar of other listings whose prices used to be
mistaken for the listing's own price.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autosieve.models import Listing
from autosieve.parsing.km import first_km
from autosieve.scraper import parse_listing_html


def parse(fixtures_dir: Path, name: str, listing_id: str) -> Listing:
    html = (fixtures_dir / name).read_text(encoding="utf-8")
    url = f"https://www.facebook.com/marketplace/item/{listing_id}/"
    return parse_listing_html(html, url=url, city="lisbon")


def test_motorcycle_with_bulleted_description(fixtures_dir: Path) -> None:
    listing = parse(fixtures_dir, "live_moto_honda_hornet.html", "1399097965553501")

    assert listing.title == "2004 Honda hornet"
    assert listing.price_eur == 3_600
    assert listing.price_raw is not None and "3600" in listing.price_raw
    assert listing.location == "Odivelas, Lisboa"
    assert listing.year == 2004
    # No details block on this page: the mileage is only in the seller's prose.
    assert listing.details == ()
    assert listing.kms is None
    assert listing.description is not None
    assert listing.description.startswith("- 38000km")
    assert listing.description.endswith("Revisão em dias")
    assert "Ver menos" not in listing.description
    assert "localização" not in listing.description
    assert first_km(listing.description) == 38_000
    assert len(listing.image_urls) == 7
    assert all("fbcdn" in url for url in listing.image_urls)
    assert listing.is_complete


def test_car_with_plain_description(fixtures_dir: Path) -> None:
    listing = parse(fixtures_dir, "live_car_opel_corsa.html", "1084635340778112")

    assert listing.title is not None and listing.title.startswith("Boas vendo Opel corsa")
    assert listing.price_eur == 1_250
    assert listing.location == "Setúbal, Portugal"
    assert listing.year is None
    assert listing.description is not None
    assert listing.description.startswith("O veículo só não funciona")
    assert listing.description.endswith("negócio")
    assert len(listing.image_urls) == 9
    assert listing.is_complete


def test_free_listing_with_condition_attribute(fixtures_dir: Path) -> None:
    listing = parse(fixtures_dir, "live_free_scooter.html", "987318411034619")

    # "GRÁTIS" is recorded as the raw price; the sidebar's "9 €" must not be picked up.
    assert listing.price_raw == "GRÁTIS"
    assert listing.price_eur is None
    assert listing.location == "Salvaterra de Magos, Santarém"
    assert listing.year == 2025
    # The "Estado" / "Usado - Como novo" pair sits between the heading and the prose.
    assert len(listing.details) == 1
    assert listing.details[0].startswith("Estado: Usado")
    assert listing.details[0].endswith("Como novo")
    assert listing.description is not None
    assert listing.description.startswith("Troco kukirin g2 de 2025 praticamente nova")
    assert "Estado" not in listing.description
    assert first_km(listing.description) == 850
    assert len(listing.image_urls) == 1
    assert listing.is_complete


def test_details_block_without_description_heading(fixtures_dir: Path) -> None:
    # Regression: this page has a "Detalhes" block but no "Descrição do vendedor"
    # heading, so the description text used to land in the details tuple and the
    # listing came out incomplete.
    listing = parse(fixtures_dir, "live_moped_details_only.html", "4001983143444871")

    assert listing.title == "Vendo ou troco"
    assert listing.price_eur == 10  # a genuine placeholder price, not a sidebar leak
    assert listing.location == "Cadaval, Lisboa"
    assert len(listing.details) == 1
    assert listing.details[0].startswith("Estado: Usado")
    assert listing.details[0].endswith("Aceitável")
    assert listing.description is not None
    assert listing.description.startswith("Zundapp 4 turbina efs")
    assert "Mora sem documentos" in listing.description
    assert "Ver menos" not in listing.description
    assert listing.is_complete


@pytest.mark.parametrize(
    "name",
    [
        "live_moto_honda_hornet.html",
        "live_car_opel_corsa.html",
        "live_free_scooter.html",
        "live_moped_details_only.html",
    ],
)
def test_live_fixtures_never_pick_sidebar_prices(fixtures_dir: Path, name: str) -> None:
    listing = parse(fixtures_dir, name, "1000000000")
    # Every live page has a "9 €" sidebar item; none of these listings costs 9 €.
    assert listing.price_eur != 9

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autosieve.models import Analysis, AnalysisRecord, Listing, resolve_kms


def make_listing(**overrides: object) -> Listing:
    base: dict[str, object] = {
        "id": "1234567890",
        "url": "https://www.facebook.com/marketplace/item/1234567890/",
        "title": "Renault Clio 1.5 dCi",
        "description": "Carro impecável, 150.000 km, IPO até 2027.",
    }
    base.update(overrides)
    return Listing.model_validate(base)


def test_listing_requires_numeric_id() -> None:
    with pytest.raises(ValidationError):
        make_listing(id="abc")


def test_listing_blank_strings_become_none() -> None:
    listing = make_listing(title="   ", price_raw="")
    assert listing.title is None
    assert listing.price_raw is None
    assert not listing.is_complete


def test_listing_normalises_fuel_and_gearbox() -> None:
    listing = make_listing(fuel="Gasóleo", gearbox="Transmissão automática")
    assert listing.fuel == "gasoleo"
    assert listing.gearbox == "automatica"


def test_listing_implausible_year_and_kms_become_none() -> None:
    listing = make_listing(year=1899, kms=9_999_999)
    assert listing.year is None
    assert listing.kms is None


def test_analysis_is_lenient_on_bad_numbers() -> None:
    analysis = Analysis.model_validate(
        {
            "is_vehicle": True,
            "kms": 99_999_999,
            "vehicle": {"make": " Renault ", "year": 3001, "fuel": "Diesel"},
            "notes": None,
        }
    )
    assert analysis.kms is None
    assert analysis.vehicle.make == "Renault"
    assert analysis.vehicle.year is None
    assert analysis.vehicle.fuel == "gasoleo"
    assert analysis.notes == ""


def test_analysis_requires_is_vehicle() -> None:
    with pytest.raises(ValidationError):
        Analysis.model_validate({})


def test_ollama_schema_constrains_enums() -> None:
    schema = Analysis.ollama_schema()
    assert schema["type"] == "object"
    assert "is_vehicle" in schema["required"]
    fuel = schema["$defs"]["VehicleIdentity"]["properties"]["fuel"]
    enums = [branch for branch in fuel["anyOf"] if "enum" in branch]
    assert enums and "gasoleo" in enums[0]["enum"]


def test_resolve_kms_precedence() -> None:
    llm = Analysis(is_vehicle=True, kms=111_111)
    details = make_listing(kms=150_000, description="sem kms")
    assert resolve_kms(details, llm, 222_222) == (150_000, "details")

    prose = make_listing(description="Tem 98.000 km reais")
    assert resolve_kms(prose, llm, 222_222) == (98_000, "description")

    nothing = make_listing(description="Carro em bom estado")
    assert resolve_kms(nothing, llm, 222_222) == (111_111, "llm")
    assert resolve_kms(nothing, Analysis(is_vehicle=True), 222_222) == (222_222, "ocr")
    assert resolve_kms(nothing, None, None) == (None, None)


def test_record_ok_flag() -> None:
    good = AnalysisRecord(listing_id="1", model="m", analysis=Analysis(is_vehicle=True))
    bad = AnalysisRecord(listing_id="1", model="m", error="boom")
    assert good.ok and not bad.ok

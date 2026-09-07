from __future__ import annotations

from autosieve.duediligence import build_due_diligence
from autosieve.models import Analysis, Condition, Listing, Maintenance, VehicleIdentity

REF = 2026


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


def questions(card: object) -> str:
    return " ".join(i.question for i in card.items)  # type: ignore[attr-defined]


def test_always_includes_history_and_in_person_checks() -> None:
    card = build_due_diligence(listing(), None, reference_year=REF)
    text = questions(card)
    assert "service history" in text
    assert "in person" in text


def test_unconfirmed_maintenance_raises_questions_with_costs() -> None:
    card = build_due_diligence(listing(kms=None), Analysis(is_vehicle=True), reference_year=REF)
    belt = next(i for i in card.items if "timing belt" in i.question)
    assert belt.cost_hint is not None
    assert any("IPO" in i.question for i in card.items)


def test_confirmed_maintenance_is_not_re_asked() -> None:
    analysis = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio"),
        maintenance=Maintenance(timing_belt_done=True, ipo_ok=True),
        iuc_status="ok",
    )
    card = build_due_diligence(listing(), analysis, reference_year=REF)
    text = questions(card)
    assert "timing belt" not in text
    assert "IPO" not in text
    assert "IUC" not in text


def test_diesel_and_automatic_specifics() -> None:
    analysis = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio", gearbox="automatica"),
    )
    card = build_due_diligence(listing(fuel="gasoleo"), analysis, reference_year=REF)
    text = questions(card)
    assert "diesel" in text
    assert "gearbox" in text


def test_accident_flag_adds_inspection_item() -> None:
    analysis = Analysis(
        is_vehicle=True,
        vehicle=VehicleIdentity(make="Renault", model="Clio"),
        condition=Condition(accident_history=True),
    )
    card = build_due_diligence(listing(), analysis, reference_year=REF)
    assert any("inspection" in i.question.lower() for i in card.items)


def test_high_mileage_and_old_car_notes() -> None:
    card = build_due_diligence(listing(year=2005, kms=500_000), None, reference_year=REF)
    text = questions(card)
    assert "Older car" in text
    assert "High mileage" in text

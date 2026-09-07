"""Turn a listing's analysis into a "before you buy" checklist.

Rule-based and deterministic: each item is a question to ask the seller or a
check to make, some with a rough euro cost, driven by what the analysis does and
does not say. It surfaces the risks a low price might be hiding, so a high deal
score comes with the homework attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from autosieve.models import Analysis, Listing
from autosieve.scoring import KM_PER_YEAR


@dataclass(frozen=True, slots=True)
class DueDiligenceItem:
    question: str
    cost_hint: str | None = None


@dataclass
class DueDiligence:
    items: list[DueDiligenceItem] = field(default_factory=list)

    def add(self, question: str, cost_hint: str | None = None) -> None:
        self.items.append(DueDiligenceItem(question, cost_hint))


def _reference_year() -> int:
    return datetime.now(UTC).year


def build_due_diligence(
    listing: Listing,
    analysis: Analysis | None,
    *,
    kms: int | None = None,
    reference_year: int | None = None,
) -> DueDiligence:
    """Build the checklist. ``kms`` is the resolved mileage; falls back to the listing's."""
    ref = reference_year if reference_year is not None else _reference_year()
    mileage = kms if kms is not None else listing.kms
    card = DueDiligence()
    maintenance = analysis.maintenance if analysis else None
    condition = analysis.condition if analysis else None
    fuel = listing.fuel or (analysis.vehicle.fuel if analysis else None)
    gearbox = listing.gearbox or (analysis.vehicle.gearbox if analysis else None)
    year = listing.year or (analysis.vehicle.year if analysis else None)

    # Maintenance the listing did not confirm.
    if maintenance is None or not maintenance.timing_belt_done:
        card.add(
            "When was the timing belt or chain last replaced? Ask for the invoice.",
            "~350-600 EUR if overdue",
        )
    if maintenance is None or not maintenance.ipo_ok:
        card.add(
            "Is the IPO inspection valid? Ask to see the current sticker.",
            "~35 EUR plus any repairs to pass",
        )
    if analysis is None or analysis.iuc_status != "ok":
        card.add("Is the IUC road tax paid and up to date?", "annual IUC, varies by car")

    # Condition flags worth confirming in person.
    if condition is not None and condition.accident_history:
        card.add(
            "Accidents or bodywork are mentioned — get an independent inspection.",
            "inspection ~60-120 EUR",
        )
    if condition is not None and condition.paint_issues:
        card.add("Inspect the reported paint or body defects in person.")

    # Powertrain-specific checks.
    if fuel == "gasoleo":
        card.add("On a diesel, check the DPF/EGR and watch for smoke on a cold start.")
    if gearbox == "automatica":
        card.add(
            "Confirm the automatic/DSG gearbox oil service history.", "DSG service ~250-400 EUR"
        )

    # Age and mileage.
    if year is not None and ref - year >= 15:
        card.add("Older car — check for rust and that spare parts are still available.")
    if mileage is not None and year is not None:
        expected = max(ref - year, 1) * KM_PER_YEAR
        if mileage > expected * 1.25:
            card.add("High mileage for the age — budget for clutch, suspension and service items.")

    if analysis is not None and analysis.is_dealer:
        card.add("Seller looks commercial despite a private listing — ask about IVA and warranty.")

    # Always.
    card.add("Ask for the full service history and the number of previous owners.")
    card.add("See it in person; check the VIN matches the documents and the seller is the owner.")
    return card

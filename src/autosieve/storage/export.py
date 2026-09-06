"""Flat CSV export of listings joined with their analyses.

Cells are sanitised against spreadsheet formula injection: a seller whose
description starts with ``=`` or ``@`` must not execute anything when the CSV
is opened in Excel. Unknown values are written as empty cells, not the word
"unknown", so numeric columns stay numeric in whatever reads the file.
"""

from __future__ import annotations

import csv
from pathlib import Path

from autosieve.models import AnalysisRecord, Listing
from autosieve.storage.db import Store

EXPORT_COLUMNS: tuple[str, ...] = (
    "id",
    "url",
    "title",
    "price_eur",
    "price_raw",
    "year",
    "fuel",
    "gearbox",
    "kms",
    "kms_source",
    "city",
    "scraped_at",
    "llm_is_vehicle",
    "llm_is_dealer",
    "llm_make",
    "llm_model",
    "llm_year",
    "llm_fuel",
    "llm_gearbox",
    "llm_engine",
    "llm_timing_belt_done",
    "llm_ipo_ok",
    "llm_iuc_status",
    "llm_accident_history",
    "llm_paint_issues",
    "llm_notes",
    "llm_model_name",
    "llm_error",
    "description",
    "image_urls",
)

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def build_row(listing: Listing, record: AnalysisRecord | None) -> dict[str, object]:
    analysis = record.analysis if record else None
    vehicle = analysis.vehicle if analysis else None
    maintenance = analysis.maintenance if analysis else None
    condition = analysis.condition if analysis else None
    return {
        "id": listing.id,
        "url": listing.url,
        "title": listing.title,
        "price_eur": listing.price_eur,
        "price_raw": listing.price_raw,
        "year": listing.year if listing.year is not None else (vehicle.year if vehicle else None),
        "fuel": listing.fuel or (vehicle.fuel if vehicle else None),
        "gearbox": listing.gearbox or (vehicle.gearbox if vehicle else None),
        "kms": record.kms if record else listing.kms,
        "kms_source": record.kms_source if record else ("details" if listing.kms else None),
        "city": listing.city,
        "scraped_at": listing.scraped_at.isoformat(),
        "llm_is_vehicle": analysis.is_vehicle if analysis else None,
        "llm_is_dealer": analysis.is_dealer if analysis else None,
        "llm_make": vehicle.make if vehicle else None,
        "llm_model": vehicle.model if vehicle else None,
        "llm_year": vehicle.year if vehicle else None,
        "llm_fuel": vehicle.fuel if vehicle else None,
        "llm_gearbox": vehicle.gearbox if vehicle else None,
        "llm_engine": vehicle.engine if vehicle else None,
        "llm_timing_belt_done": maintenance.timing_belt_done if maintenance else None,
        "llm_ipo_ok": maintenance.ipo_ok if maintenance else None,
        "llm_iuc_status": analysis.iuc_status if analysis else None,
        "llm_accident_history": condition.accident_history if condition else None,
        "llm_paint_issues": condition.paint_issues if condition else None,
        "llm_notes": analysis.notes if analysis else None,
        "llm_model_name": record.model if record else None,
        "llm_error": record.error if record else None,
        "description": listing.description,
        "image_urls": "|".join(listing.image_urls),
    }


def export_csv(store: Store, path: Path, *, include_non_vehicles: bool = False) -> int:
    """Write every listing (joined with its analysis) to ``path``. Returns rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for listing, record in store.iter_listings_with_analysis():
            analysis = record.analysis if record else None
            if not include_non_vehicles and analysis is not None and not analysis.is_vehicle:
                continue
            row = build_row(listing, record)
            writer.writerow({key: sanitize_cell(row[key]) for key in EXPORT_COLUMNS})
            written += 1
    return written

"""Domain models shared by the scraper, the LLM layer, storage and export.

Two rules keep the data honest:

* Unknown is ``None``, never the string "unknown". Rendering happens at export.
* Fields the LLM fills are validated leniently: an out-of-range number becomes
  ``None`` instead of failing the whole listing, because one bad field from an
  8B model should not throw away the nine good ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autosieve.parsing.km import MAX_KM, first_km
from autosieve.parsing.normalize import Fuel, Gearbox, normalize_fuel, normalize_gearbox

IucStatus = Literal["ok", "pending", "unknown"]
KmsSource = Literal["details", "description", "llm", "ocr"]

MIN_YEAR = 1950


def utcnow() -> datetime:
    return datetime.now(UTC)


def max_plausible_year() -> int:
    """Next year's models are already on sale in the autumn."""
    return utcnow().year + 1


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _plausible_year(value: int | None) -> int | None:
    if value is None:
        return None
    return value if MIN_YEAR <= value <= max_plausible_year() else None


def _plausible_kms(value: int | None) -> int | None:
    if value is None:
        return None
    return value if 0 <= value <= MAX_KM else None


# ── Scraped data ─────────────────────────────────────────────────────────────


class Listing(BaseModel):
    """What the scraper extracted deterministically from one listing page."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r"^\d{6,}$", description="Facebook Marketplace item id")
    url: str = Field(description="Canonical, tracking-free listing URL")
    title: str | None = None
    price_eur: int | None = Field(default=None, ge=1)
    price_raw: str | None = Field(default=None, description="Price text exactly as shown")
    description: str | None = None
    details: tuple[str, ...] = Field(default=(), description="Lines of the 'Detalhes' block")
    kms: int | None = Field(default=None, description="Mileage read from the details block")
    fuel: Fuel | None = None
    gearbox: Gearbox | None = None
    year: int | None = None
    image_urls: tuple[str, ...] = ()
    city: str | None = Field(default=None, description="Marketplace city slug used for the run")
    location: str | None = Field(default=None, description="Location text shown under the title")
    scraped_at: datetime = Field(default_factory=utcnow)

    @field_validator("title", "price_raw", "description", "location", mode="after")
    @classmethod
    def _strip_blank(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("year", mode="after")
    @classmethod
    def _year(cls, value: int | None) -> int | None:
        return _plausible_year(value)

    @field_validator("kms", mode="after")
    @classmethod
    def _kms(cls, value: int | None) -> int | None:
        return _plausible_kms(value)

    @field_validator("fuel", mode="before")
    @classmethod
    def _fuel(cls, value: object) -> object:
        return normalize_fuel(value) if isinstance(value, str) else value

    @field_validator("gearbox", mode="before")
    @classmethod
    def _gearbox(cls, value: object) -> object:
        return normalize_gearbox(value) if isinstance(value, str) else value

    @property
    def is_complete(self) -> bool:
        """True when the page yielded the fields the rest of the pipeline needs."""
        return self.title is not None and self.description is not None


# ── LLM output ───────────────────────────────────────────────────────────────
#
# These models double as the JSON schema handed to Ollama, so the field
# descriptions are instructions to the model. Keep them short and concrete.


class VehicleIdentity(BaseModel):
    make: str | None = Field(default=None, description="Brand, e.g. Renault. null if unknown")
    model: str | None = Field(default=None, description="Model, e.g. Clio. null if unknown")
    year: int | None = Field(default=None, description="Model year as 4 digits. null if unknown")
    fuel: Fuel | None = Field(
        default=None,
        description="gasolina, gasoleo (diesel), hibrido, eletrico, gpl, outro. null if unknown",
    )
    gearbox: Gearbox | None = Field(
        default=None, description="manual or automatica. null if unknown"
    )
    engine: str | None = Field(
        default=None, description="Engine designation as written, e.g. '1.5 dCi 90cv'"
    )

    @field_validator("make", "model", "engine", mode="after")
    @classmethod
    def _strip_blank(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("year", mode="after")
    @classmethod
    def _year(cls, value: int | None) -> int | None:
        return _plausible_year(value)

    @field_validator("fuel", mode="before")
    @classmethod
    def _fuel(cls, value: object) -> object:
        return normalize_fuel(value) if isinstance(value, str) else value

    @field_validator("gearbox", mode="before")
    @classmethod
    def _gearbox(cls, value: object) -> object:
        return normalize_gearbox(value) if isinstance(value, str) else value


class Maintenance(BaseModel):
    timing_belt_done: bool | None = Field(
        default=None, description="true if a timing belt/chain replacement is mentioned"
    )
    ipo_ok: bool | None = Field(
        default=None, description="true if the IPO inspection is described as valid or recent"
    )


class Condition(BaseModel):
    accident_history: bool | None = Field(
        default=None, description="true if accidents or bodywork repairs are mentioned"
    )
    paint_issues: bool | None = Field(
        default=None, description="true if paint defects, scratches or dents are mentioned"
    )


class Analysis(BaseModel):
    """Structured reading of one listing by the LLM."""

    is_vehicle: bool = Field(
        description=(
            "true if the listing sells a whole vehicle (car, van, motorcycle, truck). "
            "false only for parts, accessories, tyres, audio, tools. When in doubt, true"
        )
    )
    is_dealer: bool | None = Field(
        default=None,
        description=(
            "true if the seller looks commercial: IVA dedutível, garantia, stand, empresa, "
            "NIPC, retoma, financiamento. null if there is no signal"
        ),
    )
    kms: int | None = Field(
        default=None, description="Odometer mileage as a plain integer (87000). null if absent"
    )
    vehicle: VehicleIdentity = Field(default_factory=VehicleIdentity)
    maintenance: Maintenance = Field(default_factory=Maintenance)
    condition: Condition = Field(default_factory=Condition)
    iuc_status: IucStatus = Field(
        default="unknown", description="IUC road tax: ok, pending, unknown"
    )
    notes: str = Field(
        default="", description="One sentence on the standout positive or negative points"
    )

    @field_validator("kms", mode="after")
    @classmethod
    def _kms(cls, value: int | None) -> int | None:
        return _plausible_kms(value)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, value: object) -> object:
        return "" if value is None else value

    @classmethod
    def ollama_schema(cls) -> dict[str, object]:
        """JSON schema for Ollama's ``format`` parameter."""
        return cls.model_json_schema()


# ── Enrichment record ────────────────────────────────────────────────────────


class AnalysisRecord(BaseModel):
    """One enrichment attempt for one listing, successful or not.

    Failures are stored too, so a rerun can skip them or retry them on request
    instead of silently redoing the same work.
    """

    listing_id: str
    model: str
    analysed_at: datetime = Field(default_factory=utcnow)
    analysis: Analysis | None = None
    kms: int | None = Field(default=None, description="Resolved mileage after all sources")
    kms_source: KmsSource | None = None
    ocr_kms: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.analysis is not None and self.error is None


def resolve_kms(
    listing: Listing, analysis: Analysis | None, ocr_kms: int | None
) -> tuple[int | None, KmsSource | None]:
    """Pick the mileage from the most trustworthy source that has one.

    Deterministic page data beats a regex over the seller's prose, which beats
    the LLM's reading of that prose, which beats OCR on photos.
    """
    if listing.kms is not None:
        return listing.kms, "details"
    from_description = first_km(listing.description, minimum=1)
    if from_description is not None:
        return from_description, "description"
    if analysis is not None and analysis.kms is not None:
        return analysis.kms, "llm"
    if ocr_kms is not None:
        return ocr_kms, "ocr"
    return None, None

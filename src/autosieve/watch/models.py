"""A Watch: a named saved search for a specific car you want to keep an eye on."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from autosieve.parsing.normalize import Fuel, Gearbox


class Watch(BaseModel):
    """Criteria for one lookout. Every field except ``name`` is optional; a set
    field narrows the search, an unset one does not.

    Matching is forgiving on missing listing data (an unknown mileage does not
    exclude a car), but the make and model, when set, must be known and match.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, description="Unique label for this watch")
    enabled: bool = True

    make: str | None = Field(default=None, description="e.g. Renault")
    model: str | None = Field(default=None, description="e.g. Clio")
    year_min: int | None = Field(default=None, ge=1950, le=2100)
    year_max: int | None = Field(default=None, ge=1950, le=2100)
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    km_max: int | None = Field(default=None, ge=0)
    max_distance_km: int | None = Field(
        default=None, ge=0, description="Exclude listings farther than this from the origin (Faro)"
    )
    fuel: Fuel | None = None
    gearbox: Gearbox | None = None
    private_only: bool = Field(default=False, description="Exclude sellers flagged as dealers")
    min_score: float | None = Field(
        default=None, description="Only alert when the deal score is at least this"
    )
    city: str | None = Field(
        default=None, description="Informational: which Marketplace city this watch is for"
    )

    @model_validator(mode="after")
    def _ordered_bounds(self) -> Watch:
        if (
            self.year_min is not None
            and self.year_max is not None
            and self.year_min > self.year_max
        ):
            raise ValueError("year_min must be <= year_max")
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must be <= price_max")
        return self

    def describe(self) -> str:
        """A short human summary for listing watches and labelling alerts."""
        parts: list[str] = []
        if self.make or self.model:
            parts.append(" ".join(filter(None, [self.make, self.model])))
        if self.year_min or self.year_max:
            parts.append(f"{self.year_min or ''}-{self.year_max or ''}")
        if self.price_max:
            parts.append(f"<={self.price_max}€")
        if self.km_max:
            parts.append(f"<={self.km_max:,}km".replace(",", "."))
        if self.max_distance_km:
            parts.append(f"<={self.max_distance_km}km away")
        if self.fuel:
            parts.append(self.fuel)
        if self.private_only:
            parts.append("private")
        return ", ".join(parts) or "any vehicle"

"""The benchmark record and the seed-file entry it is loaded from."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from autosieve.identity import VehicleKey, canonical_make, canonical_model
from autosieve.parsing.normalize import Fuel


class Benchmark(BaseModel):
    """A market price summary for one vehicle identity and age band."""

    make: str
    model: str
    fuel: Fuel | None = None
    year_from: int = Field(ge=1950, le=2100)
    year_to: int = Field(ge=1950, le=2100)
    median_eur: int = Field(gt=0)
    p25_eur: int | None = Field(default=None, gt=0)
    p75_eur: int | None = Field(default=None, gt=0)
    sample_size: int = Field(default=0, ge=0)
    source: str = "seed"
    as_of: str | None = None

    @model_validator(mode="after")
    def _order(self) -> Benchmark:
        if self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        if self.p25_eur and self.p75_eur and self.p25_eur > self.p75_eur:
            raise ValueError("p25_eur must be <= p75_eur")
        return self

    @property
    def key(self) -> VehicleKey:
        return VehicleKey(
            make=canonical_make(self.make),
            model=canonical_model(self.model),
            fuel=self.fuel,
        )

    def covers_year(self, year: int | None) -> bool:
        """A benchmark with no year filter (open band) matches any year."""
        if year is None:
            return True
        return self.year_from <= year <= self.year_to

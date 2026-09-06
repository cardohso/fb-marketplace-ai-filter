"""Typed, validated runtime configuration.

Values come from environment variables, then from a ``.env`` file in the
working directory (read as UTF-8), then from the defaults below. Every value
is validated at load time so a typo fails with a readable message instead of
a traceback deep inside a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Approximate city centres for the Facebook Marketplace city slugs we know.
# Used only to make the browser's geolocation agree with the requested city.
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "lisbon": (38.7223, -9.1393),
    "porto": (41.1579, -8.6291),
    "braga": (41.5454, -8.4265),
    "coimbra": (40.2033, -8.4103),
    "faro": (37.0194, -7.9322),
    "aveiro": (40.6405, -8.6538),
    "setubal": (38.5244, -8.8882),
    "leiria": (39.7436, -8.8071),
    "funchal": (32.6669, -16.9241),
}


class Settings(BaseSettings):
    """All tunables for a run. Construct with ``Settings()`` to read the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Scraper ──────────────────────────────────────────────────────────────
    num_vehicles: int = Field(default=5, ge=1, le=500, description="Listings to scrape per run")
    marketplace_city: str = Field(default="lisbon", min_length=2, pattern=r"^[a-z0-9\-]+$")
    currency_symbol: str = Field(default="€", min_length=1, max_length=3)
    headless: bool = Field(
        default=False,
        description=(
            "Headless Chromium is detected more aggressively by Facebook; "
            "keep off unless you know why"
        ),
    )
    geo_latitude: float | None = Field(default=None, ge=-90, le=90)
    geo_longitude: float | None = Field(default=None, ge=-180, le=180)
    page_timeout_ms: int = Field(default=30_000, ge=1_000, le=300_000)
    listing_timeout_ms: int = Field(default=15_000, ge=1_000, le=300_000)
    debug_html_dir: Path | None = Field(
        default=None, description="Save the HTML of every fetched listing here (also on failure)"
    )
    browser_channel: str = Field(
        default="",
        description="Empty for bundled Chromium; 'chrome' or 'msedge' to drive a system browser",
    )
    fb_state_path: Path | None = Field(
        default=Path("fb_state.json"),
        description="Saved Facebook session (Playwright storage_state) from `autosieve login`",
    )

    # ── Ollama ───────────────────────────────────────────────────────────────
    ollama_model: str = Field(default="llama3.1", min_length=1)
    ollama_host: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "OLLAMA_URL"),
        description=(
            "Base URL of the Ollama server (a legacy OLLAMA_URL with /api/... path is accepted)"
        ),
    )
    llm_timeout_s: float = Field(default=120.0, gt=0)
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_s: float = Field(
        default=2.0, ge=0, validation_alias=AliasChoices("RETRY_DELAY_S", "RETRY_DELAY")
    )

    # ── OCR ──────────────────────────────────────────────────────────────────
    ocr_enabled: bool = True
    ocr_gpu: bool = False
    ocr_max_images: int = Field(default=6, ge=1, le=50)
    image_max_bytes: int = Field(default=10_000_000, ge=10_000)
    image_allowed_host_suffixes: tuple[str, ...] = ("fbcdn.net", "facebook.com")
    image_timeout_s: float = Field(default=15.0, gt=0)

    # ── Storage ──────────────────────────────────────────────────────────────
    db_path: Path = Path("autosieve.db")
    export_dir: Path = Path()

    @field_validator("ollama_host", mode="before")
    @classmethod
    def _strip_api_path(cls, value: object) -> object:
        """Accept the legacy ``OLLAMA_URL=http://host:11434/api/chat`` form."""
        if not isinstance(value, str):
            return value
        parts = urlsplit(value.strip())
        if not parts.scheme or not parts.netloc:
            raise ValueError("ollama_host must be an absolute URL like http://localhost:11434")
        return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")

    @field_validator("marketplace_city", mode="before")
    @classmethod
    def _normalise_city(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _geo_pair(self) -> Self:
        if (self.geo_latitude is None) != (self.geo_longitude is None):
            raise ValueError("geo_latitude and geo_longitude must be set together")
        return self

    @property
    def marketplace_url(self) -> str:
        return (
            f"https://www.facebook.com/marketplace/{self.marketplace_city}/vehicles"
            "?exact=0&sortBy=creation_time_descend"
        )

    @property
    def geolocation(self) -> tuple[float, float] | None:
        """Explicit override wins; otherwise a known city; otherwise no geolocation."""
        if self.geo_latitude is not None and self.geo_longitude is not None:
            return (self.geo_latitude, self.geo_longitude)
        return CITY_COORDINATES.get(self.marketplace_city)


def load_settings(**overrides: object) -> Settings:
    """Read settings from the environment and ``.env``, applying explicit overrides last."""
    return Settings(**overrides)  # type: ignore[arg-type]

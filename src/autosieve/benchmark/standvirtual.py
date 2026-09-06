"""Live market benchmarks from Standvirtual's Avaliador.

Ported from the project's standalone ``benchmarker.py`` into the
:class:`BenchmarkProvider` interface. The pure parts (price parsing, fuel
mapping, expected mileage) are separated from the Playwright form-filling so
they can be tested without a browser, and the browser valuator is injected so
the provider itself is testable with a fake.

The valuation is queried at the mileage a car of that age would normally have,
so the returned figure is the typical price for the identity. The listing's own
mileage is then handled by the deal score's condition multiplier, which avoids
counting mileage twice.

The form-filling is browser- and site-specific and cannot be verified here; it
needs validation against the live site and will need updates when Standvirtual
changes its markup.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Protocol, Self

from autosieve.benchmark.models import Benchmark
from autosieve.identity import VehicleKey
from autosieve.scoring import KM_PER_YEAR

log = logging.getLogger(__name__)

AVALIADOR_URL = "https://www.standvirtual.com/avaliacao-do-carro"
# Standvirtual is a single authoritative estimate, not a sample; this nominal
# sample size gives its benchmarks solid (not maximal) confidence in the score.
STANDVIRTUAL_SAMPLE = 40
DEFAULT_KMS = 150_000

# AutoSieve fuel enum -> Standvirtual dropdown label.
FUEL_MAP: dict[str, str] = {
    "gasoleo": "Diesel",
    "gasolina": "Gasolina",
    "eletrico": "Elétrico",
    "hibrido": "Gasolina/Elétrico",
    "gpl": "GPL",
}

# "12 550 EUR - 15 350 EUR" and "EUR 26,140 - EUR 31,050" seen on the page.
# The range separator may be a hyphen or an en dash (U+2013).
_DASH = "[-\u2013]"  # hyphen or en dash
_PRICE_PATTERNS = (
    re.compile(
        rf"(\d{{1,3}}(?:\s\d{{3}})*)\s*EUR\s*{_DASH}\s*(\d{{1,3}}(?:\s\d{{3}})*)\s*EUR",
        re.IGNORECASE,
    ),
    re.compile(
        rf"EUR\s*(\d{{1,3}}(?:[.,]\d{{3}})*)\s*{_DASH}\s*EUR\s*(\d{{1,3}}(?:[.,]\d{{3}})*)",
        re.IGNORECASE,
    ),
)
# The static example price printed on the form page; never a real result.
_EXAMPLE = ("26140", "31050")


@dataclass(frozen=True, slots=True)
class Valuation:
    price_min: int
    price_max: int

    @property
    def avg(self) -> int:
        return (self.price_min + self.price_max) // 2


def map_fuel(fuel: str | None) -> str | None:
    return FUEL_MAP.get(fuel) if fuel else None


def expected_kms(year: int, reference_year: int) -> int:
    age = max(reference_year - year, 1)
    return age * KM_PER_YEAR


def parse_valuation(body_text: str) -> Valuation | None:
    """Extract the price range from the result page, ignoring the example price."""
    matches: list[tuple[str, str]] = []
    for pattern in _PRICE_PATTERNS:
        matches.extend(pattern.findall(body_text))
    real = [
        m for m in matches if (re.sub(r"[\s.,]", "", m[0]), re.sub(r"[\s.,]", "", m[1])) != _EXAMPLE
    ]
    if not real:
        return None
    lo_raw, hi_raw = real[-1]
    lo = int(re.sub(r"[\s.,]", "", lo_raw))
    hi = int(re.sub(r"[\s.,]", "", hi_raw))
    if lo <= 0 or hi < lo:
        return None
    return Valuation(price_min=lo, price_max=hi)


class Valuator(Protocol):
    def valuate(
        self,
        *,
        make: str,
        model: str,
        year: int,
        fuel: str | None,
        gearbox: str | None,
        kms: int,
    ) -> Valuation | None:
        """A market valuation for one vehicle, or None if it could not be obtained."""
        ...


class StandvirtualBenchmarkProvider:
    """A :class:`BenchmarkProvider` backed by a :class:`Valuator`.

    Use inside a ``with`` block when the valuator drives a browser::

        with StandvirtualBenchmarker(settings) as valuator:
            provider = StandvirtualBenchmarkProvider(valuator, reference_year=2026)
            benchmark = provider.lookup(key, 2018)
    """

    def __init__(self, valuator: Valuator, *, reference_year: int) -> None:
        self._valuator = valuator
        self._reference_year = reference_year

    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        if year is None:
            return None
        kms = expected_kms(year, self._reference_year)
        valuation = self._valuator.valuate(
            make=key.make, model=key.model, year=year, fuel=key.fuel, gearbox=None, kms=kms
        )
        if valuation is None:
            return None
        return Benchmark(
            make=key.make,
            model=key.model,
            fuel=key.fuel,
            year_from=year,
            year_to=year,
            median_eur=valuation.avg,
            p25_eur=valuation.price_min,
            p75_eur=valuation.price_max,
            sample_size=STANDVIRTUAL_SAMPLE,
            source="standvirtual",
            as_of=datetime.now(UTC).strftime("%Y-%m-%d"),
        )


class StandvirtualBenchmarker:
    """Drives the Standvirtual Avaliador form to value one car at a time.

    Browser-bound; open it as a context manager so one browser serves many
    valuations. This is a faithful port of the standalone benchmarker and is
    not verified against the live site.
    """

    def __init__(self, settings: object) -> None:
        self._settings = settings
        # Playwright objects are dynamically typed; keep them as Any.
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        headless = bool(getattr(self._settings, "headless", True))
        channel = getattr(self._settings, "browser_channel", "") or ""
        self._playwright = sync_playwright().start()
        launch_options: dict[str, Any] = {"headless": headless}
        if channel:
            launch_options["channel"] = channel
        self._browser = self._playwright.chromium.launch(**launch_options)
        context = self._browser.new_context(locale="pt-PT")
        self._page = context.new_page()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        from playwright.sync_api import Error as PlaywrightError

        try:
            if self._browser is not None:
                self._browser.close()
        except PlaywrightError:
            log.debug("ignoring error closing Standvirtual browser", exc_info=True)
        if self._playwright is not None:
            self._playwright.stop()

    def valuate(
        self,
        *,
        make: str,
        model: str,
        year: int,
        fuel: str | None,
        gearbox: str | None,
        kms: int,
    ) -> Valuation | None:
        from autosieve.benchmark._standvirtual_form import fill_valuation_form

        if self._page is None:
            raise RuntimeError("StandvirtualBenchmarker must be used as a context manager")
        return fill_valuation_form(
            self._page,
            make=make.title(),
            model=model.title(),
            year=year,
            fuel=map_fuel(fuel),
            gearbox=(gearbox.title() if gearbox else None),
            kms=kms,
        )

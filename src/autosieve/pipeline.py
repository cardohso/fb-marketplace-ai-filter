"""Orchestration with per-item error boundaries and run summaries.

``scrape`` moves listings from Marketplace into the store; ``enrich`` moves
listings from the store through the LLM (and optionally OCR) and back. Each
listing is its own unit of work: one broken page or one bad model answer is
recorded and skipped, never allowed to take the rest of the run down with it.
Only conditions that make further work pointless (a login wall, Ollama being
down) abort the run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Protocol, Self

from playwright.sync_api import Error as PlaywrightError

from autosieve.config import Settings
from autosieve.llm import LlmError, ModelNotFoundError, OllamaUnavailableError
from autosieve.models import Analysis, AnalysisRecord, Listing, resolve_kms
from autosieve.ocr import OcrUnavailableError
from autosieve.parsing.urls import canonical_listing_url
from autosieve.scraper import (
    ListingUnavailableError,
    LoginWallError,
    ScrapeError,
    parse_listing_html,
)
from autosieve.scraper.browser import MarketplaceBrowser
from autosieve.storage import Store, UpsertOutcome

log = logging.getLogger(__name__)


# ── Collaborator protocols (so tests can substitute fakes) ───────────────────


class ListingSource(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def open_marketplace(self) -> None: ...

    def collect_listing_ids(self, limit: int) -> list[str]: ...

    def fetch_listing_html(self, listing_id: str) -> str: ...


class Analyzer(Protocol):
    @property
    def model(self) -> str: ...

    def analyse(self, listing: Listing) -> Analysis: ...


class KmsReader(Protocol):
    def read_kms(
        self,
        image_urls: Iterable[str],
        *,
        fetch: Callable[[str], bytes],
        max_images: int = ...,
    ) -> int | None: ...


# ── Summaries ────────────────────────────────────────────────────────────────


@dataclass
class ScrapeSummary:
    requested: int = 0
    found: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    incomplete: int = 0
    unavailable: int = 0
    failed: int = 0
    duration_s: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def stored(self) -> int:
        return self.new + self.updated + self.unchanged


@dataclass
class EnrichSummary:
    pending: int = 0
    analysed: int = 0
    failed: int = 0
    non_vehicles: int = 0
    dealers: int = 0
    ocr_attempted: int = 0
    ocr_hits: int = 0
    duration_s: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)


# ── Scrape ───────────────────────────────────────────────────────────────────


def _save_debug_html(settings: Settings, listing_id: str, html: str) -> None:
    if settings.debug_html_dir is None:
        return
    settings.debug_html_dir.mkdir(parents=True, exist_ok=True)
    target = settings.debug_html_dir / f"{listing_id}.html"
    target.write_text(html, encoding="utf-8")
    log.debug("saved %s", target)


def scrape(
    settings: Settings,
    store: Store,
    *,
    source_factory: Callable[[Settings], ListingSource] = MarketplaceBrowser,
) -> ScrapeSummary:
    """Collect listing ids from the feed, fetch and parse each one, upsert into ``store``.

    Raises :class:`LoginWallError` when Facebook stops serving pages anonymously;
    every other per-listing problem is counted and the run continues.
    """
    started = time.monotonic()
    summary = ScrapeSummary(requested=settings.num_vehicles)

    with source_factory(settings) as source:
        source.open_marketplace()
        ids = source.collect_listing_ids(settings.num_vehicles)
        summary.found = len(ids)
        log.info("Found %d listing(s) on the feed", len(ids))

        for index, listing_id in enumerate(ids, start=1):
            log.info("[%d/%d] fetching %s", index, len(ids), listing_id)
            try:
                html = source.fetch_listing_html(listing_id)
            except LoginWallError:
                raise
            except (PlaywrightError, ScrapeError) as exc:
                summary.failed += 1
                summary.failures.append((listing_id, str(exc)))
                log.warning("  fetch failed: %s", exc)
                continue

            _save_debug_html(settings, listing_id, html)
            try:
                listing = parse_listing_html(
                    html,
                    url=canonical_listing_url(listing_id),
                    city=settings.marketplace_city,
                    currency=settings.currency_symbol,
                )
            except ListingUnavailableError:
                summary.unavailable += 1
                log.info("  listing no longer available")
                continue
            except Exception as exc:  # a parser bug must not end the run; the HTML is kept
                summary.failed += 1
                summary.failures.append((listing_id, f"parse error: {exc}"))
                log.warning("  parse failed: %s", exc)
                continue

            if not listing.is_complete:
                summary.incomplete += 1
                log.warning(
                    "  parsed without %s; keep the HTML (--debug-html) to update the parser",
                    "a title" if listing.title is None else "a description",
                )

            outcome = store.upsert_listing(listing)
            if outcome is UpsertOutcome.NEW:
                summary.new += 1
            elif outcome is UpsertOutcome.UPDATED:
                summary.updated += 1
            else:
                summary.unchanged += 1
            log.info("  %s | %s | %s", listing.title, listing.price_raw or "no price", outcome)

    summary.duration_s = time.monotonic() - started
    return summary


# ── Enrich ───────────────────────────────────────────────────────────────────


def enrich(
    settings: Settings,
    store: Store,
    analyzer: Analyzer,
    *,
    odometer: KmsReader | None = None,
    image_fetch: Callable[[str], bytes] | None = None,
    retry_failed: bool = False,
    reanalyse: bool = False,
    limit: int | None = None,
) -> EnrichSummary:
    """Analyse every listing that lacks a current analysis and store the result.

    Raises when Ollama is unreachable or the model is missing, because retrying
    the same dead endpoint for every listing would only waste time.
    """
    started = time.monotonic()
    pending = store.listings_pending_analysis(
        analyzer.model, retry_failed=retry_failed, force=reanalyse
    )
    if limit is not None:
        pending = pending[:limit]
    summary = EnrichSummary(pending=len(pending))
    log.info("%d listing(s) to analyse with %s", len(pending), analyzer.model)

    for index, listing in enumerate(pending, start=1):
        log.info("[%d/%d] analysing %s: %s", index, len(pending), listing.id, listing.title)
        try:
            analysis = analyzer.analyse(listing)
        except (OllamaUnavailableError, ModelNotFoundError):
            raise
        except LlmError as exc:
            summary.failed += 1
            summary.failures.append((listing.id, str(exc)))
            store.save_analysis(
                AnalysisRecord(listing_id=listing.id, model=analyzer.model, error=str(exc))
            )
            log.warning("  analysis failed: %s", exc)
            continue

        ocr_kms: int | None = None
        kms, source = resolve_kms(listing, analysis, None)
        needs_ocr = kms is None and analysis.is_vehicle and bool(listing.image_urls)
        if needs_ocr and odometer is not None and image_fetch is not None:
            summary.ocr_attempted += 1
            try:
                ocr_kms = odometer.read_kms(
                    listing.image_urls, fetch=image_fetch, max_images=settings.ocr_max_images
                )
            except OcrUnavailableError as exc:
                log.warning("%s. OCR is disabled for the rest of this run.", exc)
                odometer = None
            if ocr_kms is not None:
                summary.ocr_hits += 1
                kms, source = resolve_kms(listing, analysis, ocr_kms)

        store.save_analysis(
            AnalysisRecord(
                listing_id=listing.id,
                model=analyzer.model,
                analysis=analysis,
                kms=kms,
                kms_source=source,
                ocr_kms=ocr_kms,
            )
        )
        summary.analysed += 1
        if not analysis.is_vehicle:
            summary.non_vehicles += 1
        elif analysis.is_dealer:
            summary.dealers += 1
        log.info(
            "  vehicle=%s dealer=%s kms=%s (%s)",
            analysis.is_vehicle,
            analysis.is_dealer,
            kms,
            source or "unknown",
        )

    summary.duration_s = time.monotonic() - started
    return summary

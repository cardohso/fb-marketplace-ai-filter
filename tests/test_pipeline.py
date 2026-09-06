from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from autosieve.config import Settings
from autosieve.llm import AnalysisError, OllamaUnavailableError
from autosieve.models import Analysis, Listing
from autosieve.ocr import OcrUnavailableError
from autosieve.pipeline import enrich, scrape
from autosieve.scraper import LoginWallError, ScrapeError
from autosieve.storage import Store

# ── fakes ────────────────────────────────────────────────────────────────────


class FakeSource:
    """Stands in for MarketplaceBrowser: serves fixture HTML or raises per id."""

    def __init__(self, settings: Settings, pages: dict[str, str | Exception]) -> None:
        self.settings = settings
        self.pages = pages
        self.opened = False
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.closed = True

    def open_marketplace(self) -> None:
        self.opened = True

    def collect_listing_ids(self, limit: int) -> list[str]:
        return list(self.pages)[:limit]

    def fetch_listing_html(self, listing_id: str) -> str:
        page = self.pages[listing_id]
        if isinstance(page, Exception):
            raise page
        return page


class FakeAnalyzer:
    model = "fake-model"

    def __init__(self, answers: dict[str, Analysis | Exception]) -> None:
        self.answers = answers
        self.seen: list[str] = []

    def analyse(self, listing: Listing) -> Analysis:
        self.seen.append(listing.id)
        answer = self.answers[listing.id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeOdometer:
    def __init__(self, value: int | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls = 0

    def read_kms(
        self,
        image_urls: Iterable[str],
        *,
        fetch: Callable[[str], bytes],
        max_images: int = 6,
    ) -> int | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.value


def fixture(fixtures_dir: Path, name: str) -> str:
    return (fixtures_dir / name).read_text(encoding="utf-8")


def make_listing(listing_id: str, **overrides: object) -> Listing:
    base: dict[str, object] = {
        "id": listing_id,
        "url": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        "title": f"Car {listing_id}",
        "description": "Carro em bom estado.",
        "image_urls": ("https://scontent.fbcdn.net/a.jpg",),
    }
    base.update(overrides)
    return Listing.model_validate(base)


@pytest.fixture
def store() -> Store:
    with Store(":memory:") as s:
        yield s


# ── scrape ───────────────────────────────────────────────────────────────────


def test_scrape_isolates_failures_and_stores_the_rest(
    fixtures_dir: Path, store: Store, tmp_path: Path
) -> None:
    pages: dict[str, str | Exception] = {
        "1000000001": fixture(fixtures_dir, "listing_full.html"),
        "1000000002": fixture(fixtures_dir, "listing_unavailable.html"),
        "1000000003": ScrapeError("navigation blew up"),
        "1000000004": fixture(fixtures_dir, "listing_minimal.html"),
        "1000000005": fixture(fixtures_dir, "listing_parts.html"),
    }
    settings = Settings(num_vehicles=10, debug_html_dir=tmp_path / "html")
    sources: list[FakeSource] = []

    def factory(s: Settings) -> FakeSource:
        source = FakeSource(s, pages)
        sources.append(source)
        return source

    summary = scrape(settings, store, source_factory=factory)

    assert summary.found == 5
    assert summary.new == 3
    assert summary.unavailable == 1
    assert summary.failed == 1
    assert summary.failures == [("1000000003", "navigation blew up")]
    assert summary.incomplete == 1  # the minimal page has no description
    assert summary.stored == 3
    assert sources[0].opened and sources[0].closed

    stored = store.get_listing("1000000001")
    assert stored is not None
    assert stored.price_eur == 12_500
    assert stored.kms == 87_000
    assert stored.city == "lisbon"
    # Every fetched page was kept for fixture-building; the failed fetch had no HTML.
    assert sorted(p.name for p in (tmp_path / "html").iterdir()) == [
        "1000000001.html",
        "1000000002.html",
        "1000000004.html",
        "1000000005.html",
    ]


def test_scrape_second_run_is_idempotent(fixtures_dir: Path, store: Store) -> None:
    pages: dict[str, str | Exception] = {"1000000001": fixture(fixtures_dir, "listing_full.html")}
    settings = Settings(num_vehicles=5)
    first = scrape(settings, store, source_factory=lambda s: FakeSource(s, pages))
    second = scrape(settings, store, source_factory=lambda s: FakeSource(s, pages))
    assert (first.new, first.unchanged) == (1, 0)
    assert (second.new, second.unchanged) == (0, 1)
    assert store.counts()["listings"] == 1


def test_scrape_login_wall_aborts_but_keeps_earlier_work(fixtures_dir: Path, store: Store) -> None:
    pages: dict[str, str | Exception] = {
        "1000000001": fixture(fixtures_dir, "listing_full.html"),
        "1000000002": LoginWallError("redirected to /login"),
        "1000000003": fixture(fixtures_dir, "listing_parts.html"),
    }
    with pytest.raises(LoginWallError):
        scrape(Settings(num_vehicles=5), store, source_factory=lambda s: FakeSource(s, pages))
    assert store.get_listing("1000000001") is not None
    assert store.get_listing("1000000003") is None


# ── enrich ───────────────────────────────────────────────────────────────────


def test_enrich_records_success_failure_and_kms_sources(store: Store) -> None:
    with_details = make_listing("2000000001", kms=150_000)
    in_prose = make_listing("2000000002", description="Tem 98.000 km")
    from_llm = make_listing("2000000003")
    broken = make_listing("2000000004")
    parts = make_listing("2000000005", title="Jantes")
    for listing in (with_details, in_prose, from_llm, broken, parts):
        store.upsert_listing(listing)

    analyzer = FakeAnalyzer(
        {
            with_details.id: Analysis(is_vehicle=True, is_dealer=False, kms=149_000),
            in_prose.id: Analysis(is_vehicle=True, is_dealer=True),
            from_llm.id: Analysis(is_vehicle=True, kms=120_000),
            broken.id: AnalysisError("model returned garbage"),
            parts.id: Analysis(is_vehicle=False),
        }
    )
    odometer = FakeOdometer(value=55_000)

    summary = enrich(
        Settings(), store, analyzer, odometer=odometer, image_fetch=lambda _: b"", limit=None
    )

    assert summary.pending == 5
    assert summary.analysed == 4
    assert summary.failed == 1
    assert summary.non_vehicles == 1
    assert summary.dealers == 1
    assert summary.failures == [(broken.id, "model returned garbage")]
    # OCR only runs when nothing else produced a mileage and the listing is a vehicle.
    assert odometer.calls == 0

    def record(listing_id: str) -> tuple[int | None, str | None]:
        rec = store.get_analysis(listing_id)
        assert rec is not None
        return rec.kms, rec.kms_source

    assert record(with_details.id) == (150_000, "details")
    assert record(in_prose.id) == (98_000, "description")
    assert record(from_llm.id) == (120_000, "llm")
    failed = store.get_analysis(broken.id)
    assert failed is not None and not failed.ok and failed.error == "model returned garbage"

    # Nothing is pending any more; the failure is only retried on request.
    assert store.listings_pending_analysis("fake-model") == []
    assert [x.id for x in store.listings_pending_analysis("fake-model", retry_failed=True)] == [
        broken.id
    ]


def test_enrich_uses_ocr_as_last_resort(store: Store) -> None:
    listing = make_listing("2000000010")
    store.upsert_listing(listing)
    analyzer = FakeAnalyzer({listing.id: Analysis(is_vehicle=True)})
    odometer = FakeOdometer(value=187_432)

    summary = enrich(Settings(), store, analyzer, odometer=odometer, image_fetch=lambda _: b"")

    assert odometer.calls == 1
    assert (summary.ocr_attempted, summary.ocr_hits) == (1, 1)
    rec = store.get_analysis(listing.id)
    assert rec is not None
    assert (rec.kms, rec.kms_source, rec.ocr_kms) == (187_432, "ocr", 187_432)


def test_enrich_disables_ocr_when_extra_is_missing(store: Store) -> None:
    a, b = make_listing("2000000020"), make_listing("2000000021")
    store.upsert_listing(a)
    store.upsert_listing(b)
    analyzer = FakeAnalyzer({a.id: Analysis(is_vehicle=True), b.id: Analysis(is_vehicle=True)})
    odometer = FakeOdometer(error=OcrUnavailableError("EasyOCR is not installed"))

    summary = enrich(Settings(), store, analyzer, odometer=odometer, image_fetch=lambda _: b"")

    assert odometer.calls == 1  # not retried for the second listing
    assert summary.analysed == 2
    assert summary.ocr_hits == 0


def test_enrich_aborts_when_ollama_is_down(store: Store) -> None:
    a, b = make_listing("2000000030"), make_listing("2000000031")
    store.upsert_listing(a)
    store.upsert_listing(b)
    analyzer = FakeAnalyzer(
        {a.id: OllamaUnavailableError("connection refused"), b.id: Analysis(is_vehicle=True)}
    )
    with pytest.raises(OllamaUnavailableError):
        enrich(Settings(), store, analyzer)
    assert analyzer.seen == [a.id]
    assert store.get_analysis(a.id) is None


def test_enrich_respects_limit(store: Store) -> None:
    ids = ["2000000040", "2000000041", "2000000042"]
    for listing_id in ids:
        store.upsert_listing(make_listing(listing_id))
    analyzer = FakeAnalyzer(dict.fromkeys(ids, Analysis(is_vehicle=True)))
    summary = enrich(Settings(), store, analyzer, limit=2)
    assert summary.pending == 2
    assert len(analyzer.seen) == 2

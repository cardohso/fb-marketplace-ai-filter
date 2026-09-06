from __future__ import annotations

from pathlib import Path

import pytest

from autosieve.benchmark import Benchmark, SeedBenchmarkProvider
from autosieve.models import Analysis, AnalysisRecord, Listing, VehicleIdentity
from autosieve.report import build_report, render_html, render_terminal
from autosieve.storage import Store

REF = 2026


def bench(**overrides: object) -> Benchmark:
    base: dict[str, object] = {
        "make": "Renault",
        "model": "Clio",
        "fuel": "gasoleo",
        "year_from": 2013,
        "year_to": 2019,
        "median_eur": 9500,
        "sample_size": 50,
    }
    base.update(overrides)
    return Benchmark.model_validate(base)


@pytest.fixture
def store() -> Store:
    with Store(":memory:") as s:
        yield s


def add(store: Store, listing_id: str, price: int | None, **vehicle: object) -> None:
    listing = Listing(
        id=listing_id,
        url=f"https://www.facebook.com/marketplace/item/{listing_id}/",
        title=f"Renault Clio {listing_id}",
        price_eur=price,
        year=2016,
        fuel="gasoleo",
    )
    store.upsert_listing(listing)
    analysis = Analysis(
        is_vehicle=True, vehicle=VehicleIdentity(make="Renault", model="Clio", **vehicle)
    )
    store.save_analysis(
        AnalysisRecord(listing_id=listing_id, model="test", analysis=analysis, kms=None)
    )


def test_build_report_ranks_best_deal_first(store: Store) -> None:
    add(store, "1111111111", 6000)  # ratio 1.58, best
    add(store, "2222222222", 9000)  # ratio 1.06
    add(store, "3333333333", 12000)  # ratio 0.79, worst
    provider = SeedBenchmarkProvider([bench()])

    report = build_report(store, provider, reference_year=REF)
    scored_ids = [r.listing.id for r in report.scored]
    assert scored_ids == ["1111111111", "2222222222", "3333333333"]
    assert report.scored[0].score.score > report.scored[-1].score.score


def test_unscored_listings_sink_and_are_counted(store: Store) -> None:
    add(store, "1111111111", 6000)  # scored
    add(store, "2222222222", 10)  # placeholder price -> unscored
    # A model with no benchmark.
    other = Listing(
        id="3333333333",
        url="https://www.facebook.com/marketplace/item/3333333333/",
        title="Lada Niva",
    )
    store.upsert_listing(other)
    store.save_analysis(
        AnalysisRecord(
            listing_id="3333333333",
            model="test",
            analysis=Analysis(is_vehicle=True, vehicle=VehicleIdentity(make="Lada", model="Niva")),
        )
    )
    provider = SeedBenchmarkProvider([bench()])

    report = build_report(store, provider, reference_year=REF)
    assert [r.listing.id for r in report.scored] == ["1111111111"]
    assert report.rows[0].listing.id == "1111111111"  # scored first
    counts = report.status_counts()
    assert counts["scored"] == 1
    assert counts["no_price"] == 1
    assert counts["no_benchmark"] == 1


def test_render_terminal_contains_ranking_and_summary(store: Store) -> None:
    add(store, "1111111111", 6000)
    report = build_report(store, SeedBenchmarkProvider([bench()]), reference_year=REF)
    text = render_terminal(report)
    assert "score" in text
    assert "1 scored" in text
    assert "Renault Clio" in text


def test_render_html_is_wellformed_and_escaped(store: Store, tmp_path: Path) -> None:
    listing = Listing(
        id="1111111111",
        url="https://www.facebook.com/marketplace/item/1111111111/?ref=<script>",
        title="Renault Clio <b>barato</b>",
        price_eur=6000,
        year=2016,
        fuel="gasoleo",
    )
    store.upsert_listing(listing)
    store.save_analysis(
        AnalysisRecord(
            listing_id="1111111111",
            model="test",
            analysis=Analysis(
                is_vehicle=True,
                is_dealer=True,
                vehicle=VehicleIdentity(make="Renault", model="Clio"),
                notes="Nice & tidy",
            ),
            kms=90000,
        )
    )
    report = build_report(store, SeedBenchmarkProvider([bench()]), reference_year=REF)
    out = render_html(report)

    assert out.startswith("<!doctype html>")
    assert out.count("<tr") >= 2  # header + at least one data row
    # Raw HTML from the listing must be escaped, not injected.
    assert "<b>barato</b>" not in out
    assert "&lt;b&gt;barato&lt;/b&gt;" in out
    assert "<script>" not in out
    assert "dealer" in out
    assert "Nice &amp; tidy" in out

    (tmp_path / "deals.html").write_text(out, encoding="utf-8")

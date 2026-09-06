"""SQLite store for listings and their analyses.

Listing id is the primary key everywhere, which is what makes reruns
idempotent: scraping the same item twice updates one row and appends to its
price history, and enrichment only runs for listings without a current
analysis. Failed analyses are stored too, so they can be skipped or retried
deliberately instead of being redone by accident.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from autosieve.benchmark.models import Benchmark
from autosieve.identity import VehicleKey
from autosieve.models import Analysis, AnalysisRecord, Listing, utcnow

SCHEMA_VERSION = 3

_BENCHMARK_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS benchmark_cache (
    make           TEXT NOT NULL,
    model          TEXT NOT NULL,
    fuel           TEXT NOT NULL,
    year           INTEGER NOT NULL,
    benchmark_json TEXT,
    fetched_at     TEXT NOT NULL,
    PRIMARY KEY (make, model, fuel, year)
)
"""

# Statements that take a database from version N to N + 1.
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: ("ALTER TABLE listings ADD COLUMN location TEXT",),
    2: (_BENCHMARK_CACHE_DDL,),
}

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT,
    price_eur       INTEGER,
    price_raw       TEXT,
    description     TEXT,
    details_json    TEXT NOT NULL DEFAULT '[]',
    kms             INTEGER,
    fuel            TEXT,
    gearbox         TEXT,
    year            INTEGER,
    image_urls_json TEXT NOT NULL DEFAULT '[]',
    city            TEXT,
    location        TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    scraped_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    listing_id  TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    price_eur   INTEGER,
    PRIMARY KEY (listing_id, observed_at)
);

CREATE TABLE IF NOT EXISTS analyses (
    listing_id    TEXT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,
    analysed_at   TEXT NOT NULL,
    analysis_json TEXT,
    kms           INTEGER,
    kms_source    TEXT,
    ocr_kms       INTEGER,
    error         TEXT,
    is_vehicle    INTEGER,
    is_dealer     INTEGER
);

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
"""
    + _BENCHMARK_CACHE_DDL
    + ";\n"
)


class UpsertOutcome(StrEnum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


def _iso(value: datetime) -> str:
    return value.isoformat()


class Store:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
                return
            version = int(row["version"])
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema is version {version}, newer than this build "
                    f"({SCHEMA_VERSION}); upgrade autosieve"
                )
            while version < SCHEMA_VERSION:
                for statement in _MIGRATIONS[version]:
                    self._conn.execute(statement)
                version += 1
            self._conn.execute("UPDATE schema_version SET version = ?", (version,))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ── listings ─────────────────────────────────────────────────────────────

    def upsert_listing(self, listing: Listing) -> UpsertOutcome:
        """Insert or refresh a listing. Appends to price history when the price changes."""
        now = _iso(utcnow())
        existing = self._conn.execute(
            "SELECT price_eur FROM listings WHERE id = ?", (listing.id,)
        ).fetchone()
        params = {
            "id": listing.id,
            "url": listing.url,
            "title": listing.title,
            "price_eur": listing.price_eur,
            "price_raw": listing.price_raw,
            "description": listing.description,
            "details_json": json.dumps(list(listing.details), ensure_ascii=False),
            "kms": listing.kms,
            "fuel": listing.fuel,
            "gearbox": listing.gearbox,
            "year": listing.year,
            "image_urls_json": json.dumps(list(listing.image_urls)),
            "city": listing.city,
            "location": listing.location,
            "now": now,
            "scraped_at": _iso(listing.scraped_at),
        }
        with self._conn:
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO listings (id, url, title, price_eur, price_raw, description,
                        details_json, kms, fuel, gearbox, year, image_urls_json, city,
                        location, first_seen_at, last_seen_at, scraped_at)
                    VALUES (:id, :url, :title, :price_eur, :price_raw, :description,
                        :details_json, :kms, :fuel, :gearbox, :year, :image_urls_json, :city,
                        :location, :now, :now, :scraped_at)
                    """,
                    params,
                )
                self._record_price(listing.id, listing.price_eur, now)
                return UpsertOutcome.NEW

            self._conn.execute(
                """
                UPDATE listings SET url = :url, title = :title, price_eur = :price_eur,
                    price_raw = :price_raw, description = :description,
                    details_json = :details_json, kms = :kms, fuel = :fuel,
                    gearbox = :gearbox, year = :year, image_urls_json = :image_urls_json,
                    city = :city, location = :location, last_seen_at = :now,
                    scraped_at = :scraped_at
                WHERE id = :id
                """,
                params,
            )
            if existing["price_eur"] != listing.price_eur:
                self._record_price(listing.id, listing.price_eur, now)
                return UpsertOutcome.UPDATED
            return UpsertOutcome.UNCHANGED

    def _record_price(self, listing_id: str, price_eur: int | None, observed_at: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO price_history (listing_id, observed_at, price_eur) "
            "VALUES (?, ?, ?)",
            (listing_id, observed_at, price_eur),
        )

    def get_listing(self, listing_id: str) -> Listing | None:
        row = self._conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        return self._row_to_listing(row) if row else None

    def price_history(self, listing_id: str) -> list[tuple[datetime, int | None]]:
        rows = self._conn.execute(
            "SELECT observed_at, price_eur FROM price_history WHERE listing_id = ? "
            "ORDER BY observed_at",
            (listing_id,),
        ).fetchall()
        return [(datetime.fromisoformat(r["observed_at"]), r["price_eur"]) for r in rows]

    def listings_pending_analysis(
        self, model: str, *, retry_failed: bool = False, force: bool = False
    ) -> list[Listing]:
        """Listings with no analysis by ``model``, plus failed ones when asked.

        ``force`` returns every listing regardless of analysis state, for
        re-running after a prompt or model change.
        """
        if force:
            rows = self._conn.execute(
                "SELECT * FROM listings ORDER BY first_seen_at, id"
            ).fetchall()
            return [self._row_to_listing(r) for r in rows]
        sql = """
            SELECT l.* FROM listings l
            LEFT JOIN analyses a ON a.listing_id = l.id
            WHERE a.listing_id IS NULL OR a.model != :model
        """
        if retry_failed:
            sql += " OR a.error IS NOT NULL"
        sql += " ORDER BY l.first_seen_at, l.id"
        rows = self._conn.execute(sql, {"model": model}).fetchall()
        return [self._row_to_listing(r) for r in rows]

    @staticmethod
    def _row_to_listing(row: sqlite3.Row) -> Listing:
        return Listing.model_validate(
            {
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "price_eur": row["price_eur"],
                "price_raw": row["price_raw"],
                "description": row["description"],
                "details": tuple(json.loads(row["details_json"])),
                "kms": row["kms"],
                "fuel": row["fuel"],
                "gearbox": row["gearbox"],
                "year": row["year"],
                "image_urls": tuple(json.loads(row["image_urls_json"])),
                "city": row["city"],
                "location": row["location"],
                "scraped_at": datetime.fromisoformat(row["scraped_at"]),
            }
        )

    # ── analyses ─────────────────────────────────────────────────────────────

    def save_analysis(self, record: AnalysisRecord) -> None:
        analysis = record.analysis
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO analyses (listing_id, model, analysed_at, analysis_json,
                    kms, kms_source, ocr_kms, error, is_vehicle, is_dealer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.listing_id,
                    record.model,
                    _iso(record.analysed_at),
                    analysis.model_dump_json() if analysis else None,
                    record.kms,
                    record.kms_source,
                    record.ocr_kms,
                    record.error,
                    None if analysis is None else int(analysis.is_vehicle),
                    None
                    if analysis is None or analysis.is_dealer is None
                    else int(analysis.is_dealer),
                ),
            )

    def get_analysis(self, listing_id: str) -> AnalysisRecord | None:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE listing_id = ?", (listing_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> AnalysisRecord:
        analysis = (
            Analysis.model_validate_json(row["analysis_json"]) if row["analysis_json"] else None
        )
        return AnalysisRecord(
            listing_id=row["listing_id"],
            model=row["model"],
            analysed_at=datetime.fromisoformat(row["analysed_at"]),
            analysis=analysis,
            kms=row["kms"],
            kms_source=row["kms_source"],
            ocr_kms=row["ocr_kms"],
            error=row["error"],
        )

    # ── reporting ────────────────────────────────────────────────────────────

    def iter_listings_with_analysis(self) -> Iterator[tuple[Listing, AnalysisRecord | None]]:
        rows = self._conn.execute(
            "SELECT l.*, a.listing_id AS a_listing_id FROM listings l "
            "LEFT JOIN analyses a ON a.listing_id = l.id ORDER BY l.first_seen_at, l.id"
        ).fetchall()
        for row in rows:
            listing = self._row_to_listing(row)
            record = self.get_analysis(listing.id) if row["a_listing_id"] else None
            yield listing, record

    # ── benchmark cache ──────────────────────────────────────────────────────

    def get_cached_benchmark(
        self, key: VehicleKey, year: int, *, ttl_days: float
    ) -> tuple[bool, Benchmark | None]:
        """Return ``(fresh, benchmark)``.

        ``fresh`` is True when a non-expired entry exists (its benchmark may be
        None, a cached "no valuation"); False means the caller should fetch.
        """
        row = self._conn.execute(
            "SELECT benchmark_json, fetched_at FROM benchmark_cache "
            "WHERE make = ? AND model = ? AND fuel = ? AND year = ?",
            (key.make, key.model, key.fuel or "", year),
        ).fetchone()
        if row is None:
            return False, None
        age = utcnow() - datetime.fromisoformat(row["fetched_at"])
        if age > timedelta(days=ttl_days):
            return False, None
        payload = row["benchmark_json"]
        return True, (Benchmark.model_validate_json(payload) if payload else None)

    def put_cached_benchmark(self, key: VehicleKey, year: int, benchmark: Benchmark | None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO benchmark_cache "
                "(make, model, fuel, year, benchmark_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key.make,
                    key.model,
                    key.fuel or "",
                    year,
                    benchmark.model_dump_json() if benchmark else None,
                    _iso(utcnow()),
                ),
            )

    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            value: Any = self._conn.execute(sql).fetchone()[0]
            return int(value or 0)

        return {
            "listings": one("SELECT COUNT(*) FROM listings"),
            "analysed": one("SELECT COUNT(*) FROM analyses WHERE error IS NULL"),
            "failed": one("SELECT COUNT(*) FROM analyses WHERE error IS NOT NULL"),
            "non_vehicles": one("SELECT COUNT(*) FROM analyses WHERE is_vehicle = 0"),
            "dealers": one("SELECT COUNT(*) FROM analyses WHERE is_dealer = 1"),
        }

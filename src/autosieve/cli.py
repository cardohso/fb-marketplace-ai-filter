"""The ``autosieve`` command: scrape, enrich, run, export, status."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import partial
from pathlib import Path

import requests
from pydantic import ValidationError

from autosieve import __version__
from autosieve.config import Settings, load_settings
from autosieve.llm import ListingAnalyzer, LlmError, OllamaClient
from autosieve.logging_setup import setup_logging
from autosieve.ocr import ImagePolicy, OdometerReader, download_image
from autosieve.pipeline import EnrichSummary, ScrapeSummary, enrich, scrape
from autosieve.scraper import ScrapeError
from autosieve.storage import Store, export_csv

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_INTERRUPTED = 130


# ── argument parsing ─────────────────────────────────────────────────────────


def _add_scrape_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, metavar="N", help="listings to scrape (NUM_VEHICLES)")
    parser.add_argument("--city", help="Marketplace city slug (MARKETPLACE_CITY)")
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="run Chromium without a window (HEADLESS)",
    )
    parser.add_argument(
        "--debug-html",
        type=Path,
        metavar="DIR",
        help="save every fetched listing page here; use it to build parser fixtures",
    )


def _add_enrich_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Ollama model name (OLLAMA_MODEL)")
    parser.add_argument(
        "--retry-failed", action="store_true", help="re-analyse listings whose last attempt failed"
    )
    parser.add_argument(
        "--max", dest="enrich_limit", type=int, metavar="N", help="analyse at most N listings"
    )
    parser.add_argument("--no-ocr", action="store_true", help="never read odometers from photos")


def _add_export_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, metavar="FILE", help="CSV path (default: timestamped)")
    parser.add_argument(
        "--include-non-vehicles",
        action="store_true",
        help="keep listings the model classified as parts or accessories",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosieve",
        description="Scrape Facebook Marketplace vehicle listings, enrich them with a local LLM, "
        "and export the result.",
    )
    parser.add_argument("--version", action="version", version=f"autosieve {__version__}")
    parser.add_argument("--db", type=Path, metavar="FILE", help="SQLite database (DB_PATH)")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="warnings only")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_scrape = sub.add_parser("scrape", help="collect listings into the database")
    _add_scrape_options(p_scrape)
    p_scrape.set_defaults(func=cmd_scrape)

    p_enrich = sub.add_parser("enrich", help="analyse stored listings with Ollama")
    _add_enrich_options(p_enrich)
    p_enrich.set_defaults(func=cmd_enrich)

    p_run = sub.add_parser("run", help="scrape, enrich and export in one go")
    _add_scrape_options(p_run)
    _add_enrich_options(p_run)
    _add_export_options(p_run)
    p_run.set_defaults(func=cmd_run)

    p_export = sub.add_parser("export", help="write the database to CSV")
    _add_export_options(p_export)
    p_export.set_defaults(func=cmd_export)

    p_status = sub.add_parser("status", help="show what the database holds")
    p_status.set_defaults(func=cmd_status)
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    mapping = {
        "num_vehicles": getattr(args, "limit", None),
        "marketplace_city": getattr(args, "city", None),
        "headless": getattr(args, "headless", None),
        "debug_html_dir": getattr(args, "debug_html", None),
        "ollama_model": getattr(args, "model", None),
        "db_path": args.db,
    }
    return load_settings(**{k: v for k, v in mapping.items() if v is not None})


# ── helpers ──────────────────────────────────────────────────────────────────


def _ocr_components(
    settings: Settings, *, disabled: bool
) -> tuple[OdometerReader | None, Callable[[str], bytes] | None]:
    if disabled or not settings.ocr_enabled:
        return None, None
    policy = ImagePolicy.from_settings(settings)
    fetch = partial(download_image, policy=policy, session=requests.Session())
    return OdometerReader(gpu=settings.ocr_gpu), fetch


def _default_export_path(settings: Settings) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return settings.export_dir / f"vehicles_{stamp}.csv"


def _print_scrape_summary(summary: ScrapeSummary) -> None:
    print(
        f"\nScrape: {summary.found} found, {summary.new} new, {summary.updated} price changes, "
        f"{summary.unchanged} unchanged, {summary.unavailable} gone, {summary.incomplete} "
        f"incomplete, {summary.failed} failed in {summary.duration_s:.0f}s"
    )
    for listing_id, reason in summary.failures:
        print(f"  ! {listing_id}: {reason}")


def _print_enrich_summary(summary: EnrichSummary) -> None:
    print(
        f"Enrich: {summary.pending} pending, {summary.analysed} analysed, {summary.failed} failed, "
        f"{summary.non_vehicles} non-vehicles, {summary.dealers} dealers, "
        f"OCR {summary.ocr_hits}/{summary.ocr_attempted} in {summary.duration_s:.0f}s"
    )
    for listing_id, reason in summary.failures:
        print(f"  ! {listing_id}: {reason}")


def _run_enrich(args: argparse.Namespace, settings: Settings, store: Store) -> EnrichSummary:
    client = OllamaClient.from_settings(settings)
    client.health_check()
    odometer, fetch = _ocr_components(settings, disabled=args.no_ocr)
    return enrich(
        settings,
        store,
        ListingAnalyzer(client),
        odometer=odometer,
        image_fetch=fetch,
        retry_failed=args.retry_failed,
        limit=args.enrich_limit,
    )


def _run_export(args: argparse.Namespace, settings: Settings, store: Store) -> Path:
    path: Path = args.out or _default_export_path(settings)
    rows = export_csv(store, path, include_non_vehicles=args.include_non_vehicles)
    print(f"Export: {rows} row(s) -> {path}")
    return path


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_scrape(_args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        summary = scrape(settings, store)
    _print_scrape_summary(summary)
    return EXIT_OK if summary.stored or summary.found == 0 else EXIT_FAILURE


def cmd_enrich(args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        summary = _run_enrich(args, settings, store)
    _print_enrich_summary(summary)
    return EXIT_OK


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        scrape_summary = scrape(settings, store)
        _print_scrape_summary(scrape_summary)
        enrich_summary = _run_enrich(args, settings, store)
        _print_enrich_summary(enrich_summary)
        _run_export(args, settings, store)
    return EXIT_OK


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        _run_export(args, settings, store)
    return EXIT_OK


def cmd_status(_args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        counts = store.counts()
    print(f"Database: {settings.db_path}")
    for key, value in counts.items():
        print(f"  {key:<13}{value:>6}")
    return EXIT_OK


# ── entry point ──────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    try:
        settings = _settings_from_args(args)
    except ValidationError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return EXIT_FAILURE

    try:
        result: int = args.func(args, settings)
        return result
    except KeyboardInterrupt:
        print("\nInterrupted. Everything stored so far is kept.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (ScrapeError, LlmError, sqlite3.Error, OSError) as exc:
        log.debug("fatal error", exc_info=True)
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FAILURE

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
from autosieve.benchmark import SeedBenchmarkProvider
from autosieve.config import Settings, load_settings
from autosieve.llm import ListingAnalyzer, LlmError, OllamaClient
from autosieve.logging_setup import setup_logging
from autosieve.ocr import ImagePolicy, OdometerReader, download_image
from autosieve.pipeline import EnrichSummary, ScrapeSummary, enrich, scrape
from autosieve.report import build_report, render_html, render_terminal
from autosieve.scoring import score_listing
from autosieve.scraper import ScrapeError
from autosieve.storage import Store, export_csv
from autosieve.watch import Watch, load_watches, save_watches, watches_path
from autosieve.watch.events import detect_events

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
        "--reanalyse",
        action="store_true",
        help="re-analyse every stored listing (use after a prompt or model change)",
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


def _add_watch_add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True, help="unique label for the watch")
    parser.add_argument("--make")
    parser.add_argument("--model")
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    parser.add_argument("--price-min", type=int)
    parser.add_argument("--price-max", type=int)
    parser.add_argument("--km-max", type=int)
    parser.add_argument("--max-distance-km", type=int, help="exclude listings farther than this")
    parser.add_argument("--fuel", choices=("gasolina", "gasoleo", "hibrido", "eletrico", "gpl"))
    parser.add_argument("--gearbox", choices=("manual", "automatica"))
    parser.add_argument("--private-only", action="store_true", help="exclude dealers")
    parser.add_argument("--min-score", type=float, help="only alert at or above this deal score")


def _add_report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--benchmark-source",
        choices=("seed", "standvirtual"),
        default="seed",
        help="seed (packaged, default) or standvirtual (live valuations, cached, then seed)",
    )
    parser.add_argument(
        "--benchmarks",
        type=Path,
        metavar="FILE",
        help="JSON of benchmarks to use instead of the packaged seed",
    )
    parser.add_argument(
        "--benchmark-ttl-days",
        type=float,
        default=30.0,
        metavar="N",
        help="how long a cached Standvirtual valuation stays fresh (default 30)",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        metavar="FILE",
        help="write the ranked deals to this HTML file",
    )
    parser.add_argument(
        "--top", type=int, default=20, metavar="N", help="rows to show in the terminal (default 20)"
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

    p_run = sub.add_parser("run", help="scrape, enrich, export and rank in one go")
    _add_scrape_options(p_run)
    _add_enrich_options(p_run)
    _add_export_options(p_run)
    _add_report_options(p_run)
    p_run.set_defaults(func=cmd_run)

    p_export = sub.add_parser("export", help="write the database to CSV")
    _add_export_options(p_export)
    p_export.set_defaults(func=cmd_export)

    p_report = sub.add_parser("report", help="rank stored listings by deal score")
    _add_report_options(p_report)
    p_report.set_defaults(func=cmd_report)

    p_poll = sub.add_parser("poll", help="scrape, enrich and alert on watch matches")
    _add_scrape_options(p_poll)
    _add_enrich_options(p_poll)
    _add_report_options(p_poll)
    p_poll.add_argument(
        "--dry-run",
        action="store_true",
        help="print alerts instead of sending, and change no state",
    )
    p_poll.set_defaults(func=cmd_poll)

    p_watch = sub.add_parser("watch", help="manage watches (saved searches)")
    watch_sub = p_watch.add_subparsers(dest="watch_command", required=True, metavar="ACTION")
    p_watch_add = watch_sub.add_parser("add", help="add a watch")
    _add_watch_add_options(p_watch_add)
    p_watch_add.set_defaults(func=cmd_watch_add)
    p_watch_list = watch_sub.add_parser("list", help="show watches")
    p_watch_list.set_defaults(func=cmd_watch_list)
    p_watch_remove = watch_sub.add_parser("remove", help="remove a watch by name")
    p_watch_remove.add_argument("name", help="watch name to remove")
    p_watch_remove.set_defaults(func=cmd_watch_remove)

    p_login = sub.add_parser("login", help="sign into Facebook once and save the session")
    p_login.set_defaults(func=cmd_login)

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
        reanalyse=args.reanalyse,
        limit=args.enrich_limit,
    )


def _run_export(args: argparse.Namespace, settings: Settings, store: Store) -> Path:
    path: Path = args.out or _default_export_path(settings)
    rows = export_csv(store, path, include_non_vehicles=args.include_non_vehicles)
    print(f"Export: {rows} row(s) -> {path}")
    return path


def _seed_provider(args: argparse.Namespace) -> SeedBenchmarkProvider:
    path = getattr(args, "benchmarks", None)
    return SeedBenchmarkProvider.from_file(path) if path else SeedBenchmarkProvider.default()


def _render_report(args: argparse.Namespace, report: object) -> None:
    from autosieve.report import Report

    assert isinstance(report, Report)
    print(render_terminal(report, top=args.top))
    out = getattr(args, "report_out", None)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(report), encoding="utf-8")
        print(f"Report: {len(report.scored)} ranked -> {out}")


def _run_report(args: argparse.Namespace, settings: Settings, store: Store) -> None:
    seed = _seed_provider(args)
    if getattr(args, "benchmark_source", "seed") != "standvirtual":
        _render_report(args, build_report(store, seed, origin=settings.origin))
        return

    # Live valuations, cached in the store, with the seed as a fallback for
    # models Standvirtual cannot value. The browser stays open for the whole run.
    from autosieve.benchmark.cache import CachedBenchmarkProvider, LayeredBenchmarkProvider
    from autosieve.benchmark.standvirtual import (
        StandvirtualBenchmarker,
        StandvirtualBenchmarkProvider,
    )

    with StandvirtualBenchmarker(settings) as valuator:
        live = StandvirtualBenchmarkProvider(
            valuator, reference_year=datetime.now().astimezone().year
        )
        cached = CachedBenchmarkProvider(live, store, ttl_days=args.benchmark_ttl_days)
        provider = LayeredBenchmarkProvider([cached, seed])
        report = build_report(store, provider, origin=settings.origin)
    _render_report(args, report)


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
        print()
        _run_report(args, settings, store)
    return EXIT_OK


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        _run_export(args, settings, store)
    return EXIT_OK


def cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    with Store(settings.db_path) as store:
        _run_report(args, settings, store)
    return EXIT_OK


def _notifier(settings: Settings, *, dry_run: bool) -> object:
    from autosieve.notify import ConsoleNotifier, TelegramNotifier

    if dry_run or not settings.telegram_configured:
        if not dry_run:
            log.warning("Telegram is not configured; printing alerts instead of sending")
        return ConsoleNotifier()
    return TelegramNotifier(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)


def cmd_poll(args: argparse.Namespace, settings: Settings) -> int:
    from autosieve.notify import NotifyError, format_event

    watches = load_watches(settings.watches_path)
    if not watches:
        print(f"No watches defined. Add one with `autosieve watch add` ({settings.watches_path}).")
        return EXIT_OK

    with Store(settings.db_path) as store:
        scrape_summary = scrape(settings, store)
        _print_scrape_summary(scrape_summary)
        enrich_summary = _run_enrich(args, settings, store)
        _print_enrich_summary(enrich_summary)

        provider = _seed_provider(args)

        def score_of(listing: object, analysis: object, distance: float | None) -> object:
            return score_listing(listing, analysis, provider, distance_km=distance)  # type: ignore[arg-type]

        events = detect_events(
            store,
            watches,
            new_ids=set(scrape_summary.new_ids),
            score_of=score_of,  # type: ignore[arg-type]
            origin=settings.origin,
            persist=not args.dry_run,
        )

    print(f"\nAlerts: {len(events)} event(s) from {len(watches)} watch(es)")
    notifier = _notifier(settings, dry_run=args.dry_run)
    sent = 0
    for event in events:
        try:
            notifier.send(format_event(event))  # type: ignore[attr-defined]
            sent += 1
        except NotifyError as exc:
            log.error("failed to send alert for %s: %s", event.listing.id, exc)
    if events and not args.dry_run:
        print(f"Sent {sent}/{len(events)} alert(s)")
    return EXIT_OK


def cmd_watch_add(args: argparse.Namespace, settings: Settings) -> int:
    watches = load_watches(settings.watches_path)
    if any(w.name == args.name for w in watches):
        print(f"A watch named {args.name!r} already exists.", file=sys.stderr)
        return EXIT_FAILURE
    watch = Watch(
        name=args.name,
        make=args.make,
        model=args.model,
        year_min=args.year_min,
        year_max=args.year_max,
        price_min=args.price_min,
        price_max=args.price_max,
        km_max=args.km_max,
        max_distance_km=args.max_distance_km,
        fuel=args.fuel,
        gearbox=args.gearbox,
        private_only=args.private_only,
        min_score=args.min_score,
    )
    watches.append(watch)
    path = save_watches(watches, settings.watches_path)
    print(f"Added watch {watch.name!r} ({watch.describe()}) -> {path}")
    return EXIT_OK


def cmd_watch_list(_args: argparse.Namespace, settings: Settings) -> int:
    watches = load_watches(settings.watches_path)
    if not watches:
        print(f"No watches in {watches_path(settings.watches_path)}.")
        return EXIT_OK
    for watch in watches:
        flag = "" if watch.enabled else " (disabled)"
        print(f"  {watch.name}{flag}: {watch.describe()}")
    return EXIT_OK


def cmd_watch_remove(args: argparse.Namespace, settings: Settings) -> int:
    watches = load_watches(settings.watches_path)
    kept = [w for w in watches if w.name != args.name]
    if len(kept) == len(watches):
        print(f"No watch named {args.name!r}.", file=sys.stderr)
        return EXIT_FAILURE
    save_watches(kept, settings.watches_path)
    print(f"Removed watch {args.name!r}")
    return EXIT_OK


def cmd_login(_args: argparse.Namespace, settings: Settings) -> int:
    from autosieve.scraper.session import save_session

    path = save_session(settings)
    print(f"Saved Facebook session -> {path}")
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

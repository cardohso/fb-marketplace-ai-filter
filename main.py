"""
AutoSieve - Full Pipeline
Runs scraper → LLM parser → Standvirtual benchmarker in sequence.

Usage:
    python3 main.py              # run full pipeline
    python3 main.py --skip-scrape vehicles_2026-03-15.csv  # skip scraping, use existing CSV
    python3 main.py --skip-benchmark   # scrape + enrich only, no Standvirtual valuation
"""

import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("autosieve")


def main():
    parser = argparse.ArgumentParser(description="AutoSieve - FB Marketplace vehicle pipeline")
    parser.add_argument("--skip-scrape", metavar="CSV", default=None,
                        help="Skip scraping and use an existing CSV file")
    parser.add_argument("--skip-benchmark", action="store_true",
                        help="Skip Standvirtual benchmarking step")
    args = parser.parse_args()

    # ── Step 1: Scrape ───────────────────────────────────────────────────────
    if args.skip_scrape:
        csv_path = args.skip_scrape
        log.info(f"Skipping scraper, using: {csv_path}")
    else:
        log.info("Step 1/3: Scraping Facebook Marketplace...")
        from scraper import scrape
        csv_path = scrape()

    # ── Step 2: LLM Enrichment ───────────────────────────────────────────────
    log.info("Step 2/3: Enriching listings with LLM...")
    from llm_parser import enrich_csv
    enriched_df = enrich_csv(csv_path)
    enriched_path = csv_path.replace(".csv", "_enriched.csv")

    # ── Step 3: Standvirtual Benchmark ───────────────────────────────────────
    if args.skip_benchmark:
        log.info("Skipping Standvirtual benchmarking.")
        final_path = enriched_path
    else:
        log.info("Step 3/3: Benchmarking against Standvirtual...")
        from benchmarker import benchmark_csv
        benchmark_csv(enriched_path)
        final_path = enriched_path.replace("_enriched.csv", "_benchmarked.csv")

    log.info(f"Pipeline complete → {final_path}")


if __name__ == "__main__":
    main()

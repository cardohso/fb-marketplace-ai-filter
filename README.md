# AutoSieve

![Status](https://img.shields.io/badge/Status-Alpha-orange)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)

AutoSieve is a personal car scout for **Facebook Marketplace Portugal**. It collects
vehicle listings, reads the facts Facebook shows on the page, asks a local LLM
(Ollama) for the facts hidden in the seller's prose, and stores everything in a
SQLite database you can export to CSV. The end goal is a **deal score**: listings
priced below their market benchmark, from private sellers, with low mileage.

## What works today

| Stage | Status | Notes |
|---|---|---|
| Scrape listing feed and pages | Working | Playwright, anonymous session, condition-based waits, login-wall detection |
| Deterministic page facts | Working | Price, mileage, fuel, gearbox and year from the title and details block |
| LLM enrichment | Working | Ollama with schema-constrained JSON: vehicle identity, dealer signals, maintenance, condition |
| Odometer OCR from photos | Working, optional | EasyOCR behind the `[ocr]` extra; last resort when no mileage is found in text |
| Storage and export | Working | SQLite keyed by listing id, price history, formula-safe CSV export |
| Market benchmark (Standvirtual) | Not started | Phase 2 |
| Deal score and ranked report | Not started | Phase 2 |
| Alerts and watchlist | Not started | Phase 3 |

The HTML parser is tested against reduced copies of real listing pages captured
in September 2026 (`tests/fixtures/live_*.html`) plus synthetic fixtures for
layouts not yet seen live. Facebook changes its markup often. When a run reports
listings as *incomplete*, rerun with `--debug-html` and turn the saved pages into
fixtures with `scripts/make_fixture.py`.

## Before you run it

Scraping Facebook Marketplace is against Facebook's terms of service. AutoSieve
runs an anonymous browser session and does not log in, which limits what it can
see and can still be rate-limited or blocked. Do not point it at an account you
care about, and keep the volume small.

## Install

Requirements: Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com/) with a model pulled.

```powershell
git clone https://github.com/cardohso/fb-marketplace-ai-filter.git
cd fb-marketplace-ai-filter
uv sync                      # core dependencies
uv run playwright install chromium
ollama pull llama3.1
```

Optional odometer OCR pulls in PyTorch (roughly two gigabytes):

```powershell
uv sync --extra ocr
```

Without `uv`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[ocr]"
playwright install chromium
```

Copy `.env.example` to `.env` and adjust what you need. Every setting is
validated at startup, so a typo fails immediately with a readable message.

## Use

```powershell
uv run autosieve run --limit 20           # scrape, enrich, export in one go
```

Or step by step:

```powershell
uv run autosieve scrape --limit 20        # feed -> database
uv run autosieve enrich                   # database -> Ollama -> database
uv run autosieve export --out cars.csv    # database -> CSV
uv run autosieve status                   # what the database holds
```

Useful flags:

| Flag | Command | Effect |
|---|---|---|
| `--limit N` | scrape, run | Listings to collect from the feed |
| `--city porto` | scrape, run | Marketplace city slug; browser geolocation follows it |
| `--headless` | scrape, run | Run Chromium without a window (more often blocked) |
| `--debug-html DIR` | scrape, run | Save every fetched page for parser debugging and fixtures |
| `--retry-failed` | enrich, run | Re-analyse listings whose last LLM attempt failed |
| `--max N` | enrich, run | Analyse at most N listings this run |
| `--no-ocr` | enrich, run | Never download photos or run OCR |
| `--include-non-vehicles` | export, run | Keep listings the model classified as parts |
| `--db FILE` | all | Use a different SQLite file |
| `-v` / `-q` | all | Debug logging / warnings only |

Runs are idempotent. Scraping the same listing again updates its row and appends
to its price history; enrichment only touches listings without a current
analysis. A crash or `Ctrl+C` keeps everything stored so far.

## Configuration

Environment variables or `.env` (UTF-8). Command-line flags override both.

| Variable | Default | Meaning |
|---|---|---|
| `NUM_VEHICLES` | `5` | Listings per scrape |
| `MARKETPLACE_CITY` | `lisbon` | City slug in the Marketplace URL |
| `CURRENCY_SYMBOL` | `€` | Symbol that marks a price on the page |
| `HEADLESS` | `false` | Headless Chromium |
| `GEO_LATITUDE`, `GEO_LONGITUDE` | city centre | Browser geolocation override |
| `PAGE_TIMEOUT_MS` | `30000` | Wait for the feed |
| `LISTING_TIMEOUT_MS` | `15000` | Wait for a listing page |
| `DEBUG_HTML_DIR` | unset | Save fetched pages here |
| `OLLAMA_MODEL` | `llama3.1` | Any model pulled in Ollama |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama base URL (`OLLAMA_URL` with a path still works) |
| `LLM_TIMEOUT_S` | `120` | Per-request timeout |
| `RETRY_ATTEMPTS` | `3` | Retries on transport or server errors |
| `RETRY_DELAY_S` | `2` | Pause between retries |
| `OCR_ENABLED` | `true` | Try OCR when no mileage is found in text |
| `OCR_GPU` | `false` | Use CUDA for EasyOCR |
| `OCR_MAX_IMAGES` | `6` | Photos tried per listing |
| `IMAGE_MAX_BYTES` | `10000000` | Largest photo downloaded |
| `IMAGE_TIMEOUT_S` | `15` | Photo download timeout |
| `DB_PATH` | `autosieve.db` | SQLite file |
| `EXPORT_DIR` | `.` | Where timestamped exports go |

## How it works

```
Marketplace feed ──► listing ids ──► listing HTML ──► parse_listing_html() ──► SQLite
                                                        (title, price, details,
                                                         mileage, fuel, gearbox,
                                                         year, photos)
SQLite ──► Ollama (JSON schema) ──► Analysis ──► mileage resolution ──► SQLite ──► CSV
                                                  details > prose > LLM > OCR
```

* `autosieve/scraper/` drives Chromium (`browser.py`) and parses HTML
  (`page_parser.py`). Every Facebook UI string lives in `locale.py`.
* `autosieve/llm/` talks to Ollama. The output is constrained to the JSON schema
  of `models.Analysis`, then validated; seller text is wrapped and sanitised so
  it cannot act as instructions.
* `autosieve/ocr/` downloads photos only from allow-listed HTTPS hosts with a
  size cap, and reads odometers with EasyOCR when nothing else found a mileage.
* `autosieve/storage/` is the SQLite store and the CSV export. Unknowns are
  `NULL`, never the string "unknown", and exported cells are escaped against
  spreadsheet formula injection.
* `autosieve/pipeline.py` runs each listing inside its own error boundary and
  produces a run summary. Only a login wall or an unreachable Ollama aborts a run.

## Develop

```powershell
uv sync --extra dev
uv run ruff check . ; uv run ruff format --check .
uv run mypy
uv run pytest
```

Tests never touch Facebook or Ollama: the parser runs against HTML fixtures in
`tests/fixtures/`, and HTTP is mocked with `responses`. CI runs the same checks on
Python 3.12, 3.13 and 3.14.

To capture new fixtures, run a scrape with `--debug-html debug_html`, then reduce
a saved page to a small faithful fixture and review it before committing:

```powershell
uv run python scripts/make_fixture.py debug_html/<id>.html tests/fixtures/live_<name>.html
```

The script keeps only the visible text, headings and image tags the parser reads,
and checks that the reduced page yields exactly the same text lines as the
original.

## Roadmap

- [x] Phase 1: package structure, validated config, typed models, tested parser,
  schema-constrained LLM output, safe OCR, SQLite store, CLI, CI
- [ ] Phase 2: vehicle identity, Standvirtual benchmark, deal score with a
  cost-adjusted condition multiplier, ranked report
- [ ] Phase 3: watchlist, price-drop alerts, due-diligence cards, duplicate and
  stock-photo detection

## Author

**João Pedro Cardoso**

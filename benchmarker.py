"""
AutoSieve - Standvirtual Benchmarker
Takes an enriched CSV and queries Standvirtual's avaliador to get market price estimates.
Outputs a final CSV with deal scores.

Usage: python3 benchmarker.py vehicles_..._enriched.csv
"""

import re
import sys
import logging
import pandas as pd
from playwright.sync_api import sync_playwright
from config import HEADLESS

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("autosieve.benchmarker")

AVALIADOR_URL = "https://www.standvirtual.com/avaliacao-do-carro"


def select_dropdown_option(page, label: str, value: str) -> bool:
    """Select an option from a Standvirtual dropdown by its label text.
    Returns True if the option was found and selected."""
    try:
        # Find the select element by its label
        select = page.locator(f"select").filter(has=page.locator(f"option")).all()
        for sel in select:
            # Check if this select's parent/label contains the label text
            parent = sel.locator("xpath=ancestor::div[1]")
            parent_text = parent.inner_text()
            if label.lower() in parent_text.lower():
                # Try to find matching option
                options = sel.locator("option").all()
                for opt in options:
                    opt_text = opt.inner_text().strip()
                    if opt_text.lower() == value.lower():
                        sel.select_option(label=opt_text)
                        page.wait_for_timeout(500)
                        return True
                # Fuzzy match: option contains value or value contains option
                for opt in options:
                    opt_text = opt.inner_text().strip()
                    if (value.lower() in opt_text.lower() or
                            opt_text.lower() in value.lower()):
                        sel.select_option(label=opt_text)
                        page.wait_for_timeout(500)
                        return True
        return False
    except Exception as e:
        log.warning(f"Failed to select {label}={value}: {e}")
        return False


def find_and_select(page, dropdown_label: str, value: str) -> bool:
    """Find a dropdown by nearby label text and select the best matching option."""
    if not value or value == "unknown":
        return False
    try:
        # Strategy: find all <select> elements, check their preceding label
        selects = page.query_selector_all("select")
        for sel in selects:
            # Get the label text from the parent container
            parent = sel.evaluate_handle(
                "el => el.closest('div[class]') || el.parentElement"
            )
            label_text = parent.evaluate("el => el.textContent || ''")
            if dropdown_label.lower() not in label_text.lower():
                continue

            # Get all options
            options = sel.query_selector_all("option")
            option_texts = []
            for opt in options:
                text = opt.inner_text().strip()
                if text and text != "Selecionar":
                    option_texts.append(text)

            # Exact match
            for text in option_texts:
                if text.lower() == value.lower():
                    sel.select_option(label=text)
                    page.wait_for_timeout(500)
                    return True

            # Fuzzy: value contained in option or option contained in value
            for text in option_texts:
                if (value.lower() in text.lower() or
                        text.lower() in value.lower()):
                    sel.select_option(label=text)
                    page.wait_for_timeout(500)
                    return True

            log.warning(f"No match for {dropdown_label}='{value}'. "
                        f"Available: {option_texts[:10]}")
            return False

        log.warning(f"Dropdown '{dropdown_label}' not found")
        return False
    except Exception as e:
        log.warning(f"Error selecting {dropdown_label}={value}: {e}")
        return False


def get_valuation(page, vehicle: dict) -> dict:
    """Fill the Standvirtual avaliador form and extract the price estimate.

    Args:
        page: Playwright page already on the avaliador URL
        vehicle: dict with keys: llm_brand, llm_model, llm_year, llm_kms,
                 llm_fuel_type, llm_transmission

    Returns:
        dict with 'sv_price_min', 'sv_price_max', 'sv_price_avg' or None values
    """
    empty = {"sv_price_min": None, "sv_price_max": None, "sv_price_avg": None}

    brand = str(vehicle.get("llm_brand", "unknown"))
    model = str(vehicle.get("llm_model", "unknown"))
    year = str(vehicle.get("llm_year", "unknown"))
    kms = str(vehicle.get("llm_kms", "unknown"))
    fuel = str(vehicle.get("llm_fuel_type", "unknown"))
    transmission = str(vehicle.get("llm_transmission", "unknown"))

    if brand == "unknown" or year == "unknown":
        log.warning(f"Skipping valuation — missing brand or year")
        return empty

    try:
        # Navigate to avaliador
        page.goto(AVALIADOR_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Accept cookies if present
        try:
            cookie_btn = page.locator("button:has-text('Aceitar'), button:has-text('Accept')")
            if cookie_btn.count() > 0:
                cookie_btn.first.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # Step 1: Year and Brand
        log.info(f"  Step 1: Year={year}, Brand={brand}")
        find_and_select(page, "Ano", year)
        page.wait_for_timeout(500)
        find_and_select(page, "Marca", brand)
        page.wait_for_timeout(500)

        # Click "Continuar"
        continuar_btn = page.locator("button:has-text('Continuar')")
        if continuar_btn.count() > 0:
            continuar_btn.first.click()
            page.wait_for_timeout(2000)
        else:
            log.warning("Continuar button not found")
            return empty

        # Step 2: Fill the modal with additional details
        log.info(f"  Step 2: Model={model}, KMs={kms}, Fuel={fuel}")

        # Model
        if model != "unknown":
            find_and_select(page, "Modelo", model)
            page.wait_for_timeout(500)

        # Segment (may auto-populate)
        # Skip — often auto-fills or not critical

        # Quilómetros (text input, not dropdown)
        if kms != "unknown":
            km_input = page.locator("input[type='text'], input[type='number']").filter(
                has=page.locator("xpath=ancestor::div[contains(., 'Quilómetros')]")
            )
            # Fallback: find input near "km" text
            if km_input.count() == 0:
                all_inputs = page.query_selector_all("input")
                for inp in all_inputs:
                    parent = inp.evaluate_handle("el => el.parentElement")
                    parent_text = parent.evaluate("el => el.textContent || ''")
                    if "km" in parent_text.lower() or "quilómetro" in parent_text.lower():
                        inp.click()
                        inp.fill(str(kms))
                        break
            else:
                km_input.first.click()
                km_input.first.fill(str(kms))
            page.wait_for_timeout(500)

        # Combustível (fuel type)
        if fuel != "unknown":
            find_and_select(page, "Combustível", fuel)
            page.wait_for_timeout(500)

        # Tipo de Caixa (transmission)
        if transmission != "unknown":
            find_and_select(page, "Tipo de Caixa", transmission)
            page.wait_for_timeout(500)

        # Seller type: always "Particular" (private)
        try:
            particular_btn = page.locator("button:has-text('Particular')")
            if particular_btn.count() > 0:
                particular_btn.first.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

        # Submit: "Obtenha uma avaliação grátis"
        submit_btn = page.locator("button:has-text('Obtenha uma avaliação')")
        if submit_btn.count() > 0:
            submit_btn.first.click()
            page.wait_for_timeout(5000)
        else:
            log.warning("Submit button not found")
            return empty

        # Extract the price range from the result page
        # Look for pattern like "EUR XX,XXX - EUR XX,XXX" or "XX.XXX € - XX.XXX €"
        body_text = page.inner_text("body")
        price_pattern = re.compile(
            r"EUR\s*([\d.,]+)\s*[-–]\s*EUR\s*([\d.,]+)", re.IGNORECASE
        )
        match = price_pattern.search(body_text)
        if not match:
            # Try alternative format
            price_pattern2 = re.compile(
                r"([\d.,]+)\s*€\s*[-–]\s*([\d.,]+)\s*€"
            )
            match = price_pattern2.search(body_text)

        if match:
            min_str = match.group(1).replace(".", "").replace(",", "")
            max_str = match.group(2).replace(".", "").replace(",", "")
            try:
                price_min = int(min_str)
                price_max = int(max_str)
                price_avg = (price_min + price_max) // 2
                log.info(f"  Valuation: EUR {price_min:,} - EUR {price_max:,} "
                         f"(avg: EUR {price_avg:,})")
                return {
                    "sv_price_min": price_min,
                    "sv_price_max": price_max,
                    "sv_price_avg": price_avg,
                }
            except ValueError:
                log.warning(f"Failed to parse prices: {match.group(0)}")
                return empty
        else:
            log.warning("Price range not found on result page")
            # Save debug screenshot
            page.screenshot(path="debug_standvirtual.png")
            return empty

    except Exception as e:
        log.error(f"Valuation failed: {e}")
        return empty


def parse_listing_price(value: str) -> int | None:
    """Parse a price string like '4200 €' or '€4,200' into an integer."""
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def benchmark_csv(input_path: str, output_path: str | None = None) -> pd.DataFrame:
    """Load an enriched CSV, get Standvirtual valuations, compute deal scores."""
    df = pd.read_csv(input_path)
    log.info(f"Loaded {len(df)} vehicles from {input_path}")

    required = {"llm_brand", "llm_year"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}. Run llm_parser.py first.")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(locale="pt-PT")
        page = context.new_page()

        for idx, row in df.iterrows():
            title = row.get("title", "unknown")
            log.info(f"[{idx + 1}/{len(df)}] Benchmarking: {title}")
            valuation = get_valuation(page, row.to_dict())
            results.append(valuation)

        browser.close()

    # Merge results
    val_df = pd.DataFrame(results)
    benchmarked_df = pd.concat([df, val_df], axis=1)

    # Compute deal score: market_avg / listing_price
    scores = []
    for _, row in benchmarked_df.iterrows():
        listing_price = parse_listing_price(str(row.get("value", "")))
        market_avg = row.get("sv_price_avg")
        if listing_price and market_avg and listing_price > 0:
            score = round(market_avg / listing_price, 2)
        else:
            score = None
        scores.append(score)

    benchmarked_df["deal_score"] = scores

    if output_path is None:
        base = input_path.replace("_enriched.csv", "").replace(".csv", "")
        output_path = f"{base}_benchmarked.csv"

    benchmarked_df.to_csv(output_path, index=False, encoding="utf-8")
    log.info(f"Saved benchmarked data -> {output_path}")
    return benchmarked_df


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 benchmarker.py <enriched_csv> [output_csv]")
        print("Example: python3 benchmarker.py vehicles_2025-01-01_enriched.csv")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    result_df = benchmark_csv(input_file, output_file)
    print("\n-- Benchmark Preview -------------------------------------------------")
    cols = ["title", "value", "llm_brand", "llm_model", "llm_year",
            "sv_price_min", "sv_price_max", "deal_score"]
    available = [c for c in cols if c in result_df.columns]
    print(result_df[available].to_string(index=False))

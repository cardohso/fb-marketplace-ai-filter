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


# Map LLM fuel names to Standvirtual fuel names
FUEL_MAP = {
    "gasóleo": "Diesel",
    "gasolina": "Gasolina",
    "elétrico": "Elétrico",
    "híbrido (gasolina)": "Gasolina/Elétrico",
    "híbrido (gasóleo)": "Diesel/Elétrico",
    "gpl": "GPL",
}


def fill_dropdown(page, label_text: str, value: str, timeout: int = 5000) -> bool:
    """Fill a Standvirtual custom dropdown by label text.
    These are searchable input dropdowns — click input, type value, select option.
    Waits for the input to be enabled before interacting."""
    if not value or value == "unknown":
        return False
    try:
        label = page.locator(f'label:has-text("{label_text}")')
        if label.count() == 0:
            log.warning(f"Label '{label_text}' not found")
            return False

        container = label.locator("xpath=following-sibling::div").first
        inp = container.locator("input").first

        # Wait for input to be enabled (cascading form)
        try:
            inp.wait_for(state="attached", timeout=timeout)
            if inp.is_disabled():
                page.wait_for_timeout(1000)
                if inp.is_disabled():
                    log.warning(f"Input for '{label_text}' is disabled, skipping")
                    return False
        except Exception:
            log.warning(f"Input for '{label_text}' not ready")
            return False

        inp.click()
        page.wait_for_timeout(300)
        inp.fill(value)
        page.wait_for_timeout(800)

        # Click the first matching option
        options = page.locator('div[role="option"]').all()
        visible_opts = [o for o in options if o.is_visible()]

        # Exact match
        for opt in visible_opts:
            if opt.inner_text().strip().lower() == value.lower():
                opt.click()
                page.wait_for_timeout(300)
                return True

        # Fuzzy match
        for opt in visible_opts:
            opt_text = opt.inner_text().strip()
            if value.lower() in opt_text.lower() or opt_text.lower() in value.lower():
                opt.click()
                page.wait_for_timeout(300)
                return True

        # Last fallback: first visible option
        if visible_opts:
            log.warning(f"No exact match for {label_text}='{value}', "
                        f"selecting: {visible_opts[0].inner_text().strip()}")
            visible_opts[0].click()
            page.wait_for_timeout(300)
            return True

        log.warning(f"No options found for {label_text}='{value}'")
        # Close dropdown by pressing Escape
        inp.press("Escape")
        return False
    except Exception as e:
        log.warning(f"Failed to fill {label_text}='{value}': {e}")
        return False


def fill_text_input(page, label_text: str, value: str) -> bool:
    """Fill a text input field by its label text or nearby placeholder."""
    if not value or value == "unknown":
        return False
    try:
        # Try by label first
        label = page.locator(f'label:has-text("{label_text}")')
        if label.count() > 0:
            container = label.locator("xpath=following-sibling::div").first
            inp = container.locator("input").first
            if not inp.is_disabled():
                inp.click()
                inp.fill(str(value))
                page.wait_for_timeout(300)
                return True

        # Fallback: find all inputs and look for one near the label text
        all_inputs = page.query_selector_all("input:not([disabled])")
        for inp in all_inputs:
            parent = inp.evaluate_handle("el => el.closest('div').parentElement")
            parent_text = parent.evaluate("el => el.textContent || ''")
            if label_text.lower().split("(")[0].strip() in parent_text.lower():
                inp.click()
                inp.fill(str(value))
                page.wait_for_timeout(300)
                return True

        log.warning(f"Text input for '{label_text}' not found")
        return False
    except Exception as e:
        log.warning(f"Failed to fill text {label_text}='{value}': {e}")
        return False


def select_first_option(page, input_name: str) -> bool:
    """Click a dropdown input by name and select the first available option."""
    try:
        inp = page.locator(f'input[name="{input_name}"]')
        if inp.count() == 0 or inp.is_disabled():
            return False
        inp.click()
        page.wait_for_timeout(500)
        options = page.locator('div[role="option"]').all()
        for opt in options:
            if opt.is_visible():
                opt.click()
                page.wait_for_timeout(300)
                return True
        inp.press("Escape")
        return False
    except Exception as e:
        log.warning(f"Failed to select first option for {input_name}: {e}")
        return False


def dismiss_cookies(page):
    """Accept cookies if the banner appears."""
    try:
        btn = page.locator('button:has-text("Aceitar"), button:has-text("Accept")')
        if btn.count() > 0:
            btn.first.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass


def get_valuation(page, vehicle: dict) -> dict:
    """Fill the Standvirtual avaliador form and extract the price estimate."""
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
        dismiss_cookies(page)

        # Step 1: Year and Brand
        log.info(f"  Step 1: Year={year}, Brand={brand}")
        fill_dropdown(page, "Ano (obrigatório)", year)
        page.wait_for_timeout(500)
        fill_dropdown(page, "Marca (obrigatório)", brand)
        page.wait_for_timeout(500)

        # Click "Continuar"
        continuar_btn = page.locator('button:has-text("Continuar")')
        if continuar_btn.count() > 0:
            continuar_btn.first.click()
            page.wait_for_timeout(2000)
        else:
            log.warning("Continuar button not found")
            return empty

        # Step 2: Fill the modal
        # Cascading order: Model → (Segment auto) → Fuel → KMs → Potência → (Cilindrada auto) → Gearbox
        sv_fuel = FUEL_MAP.get(fuel.lower(), fuel) if fuel != "unknown" else "unknown"
        log.info(f"  Step 2: Model={model}, KMs={kms}, Fuel={sv_fuel}, Trans={transmission}")

        # Model
        fill_dropdown(page, "Modelo (obrigatório)", model)
        page.wait_for_timeout(1000)

        # Combustível
        fill_dropdown(page, "Combustível (obrigatório)", sv_fuel)
        page.wait_for_timeout(500)

        # Quilómetros (by input name — label-based search is unreliable for this field)
        # Default to 150000 km if unknown (average for used cars in Portugal)
        km_value = kms if kms != "unknown" else "150000"
        try:
            page.fill('input[name="mileage"]', str(km_value))
            page.wait_for_timeout(300)
            if kms == "unknown":
                log.info("  Using default 150,000 km (KMs unknown)")
        except Exception as e:
            log.warning(f"Failed to fill KMs: {e}")

        # Potência — select first available option (we don't extract this from listings)
        select_first_option(page, "engine_power")
        page.wait_for_timeout(500)

        # Cilindrada — select first available option (auto-narrows after potência)
        select_first_option(page, "engine_capacity")
        page.wait_for_timeout(500)

        # Tipo de Caixa (default to Manual if unknown)
        trans_value = transmission if transmission != "unknown" else "Manual"
        fill_dropdown(page, "Tipo de Caixa (obrigatório)", trans_value)
        page.wait_for_timeout(500)

        # Close any open dropdown overlay
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Seller type: always "Particular"
        try:
            particular_btn = page.locator('button:has-text("Particular")')
            if particular_btn.count() > 0:
                particular_btn.first.click(force=True)
                page.wait_for_timeout(300)
        except Exception:
            pass

        # Submit
        submit_btn = page.locator('button:has-text("Obtenha uma avaliação")')
        if submit_btn.count() > 0:
            submit_btn.first.click()
            page.wait_for_timeout(5000)
        else:
            log.warning("Submit button not found")
            return empty

        # Extract the price range from the result page
        body_text = page.inner_text("body")

        # Match price formats:
        # "12 550 EUR- 15 350 EUR" (actual result, space-separated thousands)
        # "EUR 26,140 - EUR 31,050" (example on page, comma-separated)
        price_patterns = [
            re.compile(r"(\d{1,3}(?:\s\d{3})*)\s*EUR\s*[-–]\s*(\d{1,3}(?:\s\d{3})*)\s*EUR", re.IGNORECASE),
            re.compile(r"EUR\s*(\d{1,3}(?:[.,]\d{3})*)\s*[-–]\s*EUR\s*(\d{1,3}(?:[.,]\d{3})*)", re.IGNORECASE),
        ]
        matches = []
        for pat in price_patterns:
            matches.extend(pat.findall(body_text))

        # Filter out the example price (26,140 - 31,050)
        filtered = []
        for m in matches:
            min_clean = re.sub(r"[\s.,]", "", m[0])
            max_clean = re.sub(r"[\s.,]", "", m[1])
            if min_clean == "26140" and max_clean == "31050":
                continue
            filtered.append(m)
        matches = filtered

        if matches:
            min_str, max_str = matches[-1]
            min_str = re.sub(r"[\s.,]", "", min_str)
            max_str = re.sub(r"[\s.,]", "", max_str)
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
                log.warning(f"Failed to parse prices: {min_str}, {max_str}")
                return empty

        log.warning("Price range not found on result page")
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

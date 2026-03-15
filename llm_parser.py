"""
AutoSieve - LLM Parser Module
Reads scraped vehicle CSVs, enriches each row with structured LLM analysis,
and outputs an enriched CSV ready for the benchmarking engine (Phase 4).

LLM Backend: Ollama (local) → run `ollama serve` with llama3.1 pulled
"""

import re
import json
import time
import logging
from io import BytesIO
import pandas as pd
import requests
import easyocr
from PIL import Image
from config import OLLAMA_MODEL, OLLAMA_URL, RETRY_ATTEMPTS, RETRY_DELAY, OCR_GPU

# EasyOCR reader (lazy-loaded on first use)
_ocr_reader = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("autosieve.llm_parser")

# ── Prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Portuguese automotive listing analyst.
Your job is to extract structured information from a car listing written in Portuguese or English.
Always respond ONLY with a valid JSON object — no explanation, no markdown, no extra text.

JSON schema:
{
  "is_vehicle": boolean,         // true if the listing is selling an actual vehicle (car, motorcycle, van, truck). false ONLY if it is clearly selling parts, accessories, tyres, subwoofers, headlights, tools, etc. When in doubt, default to true.
  "is_dealer": boolean,          // true if seller appears to be a dealer (keywords: IVA dedutível, garantia, stand, empresa, NIPC)
  "brand": string | null,        // vehicle manufacturer (e.g. "Renault", "BMW", "Mercedes-Benz"). Extract from title or description.
  "model": string | null,        // vehicle model (e.g. "Clio", "320d", "A-Class"). Extract from title or description.
  "year": integer | null,        // manufacturing year (e.g. 2018). Extract from title or description.
  "fuel_type": string | null,    // one of: "Gasolina", "Gasóleo", "Elétrico", "Híbrido (Gasolina)", "Híbrido (Gasóleo)", "GPL", or null
  "transmission": string | null, // one of: "Manual", "Automática", or null
  "kms": integer | null,         // mileage as a plain integer (e.g. 87000), null if not mentioned
  "maintenance": {
    "timing_belt_done": boolean | null,   // true if timing belt replacement is mentioned
    "ipo_ok": boolean | null              // true if IPO (vehicle inspection) is described as current/ok
  },
  "iuc_status": "ok" | "pending" | "unknown",  // IUC tax status
  "condition": {
    "accident_history": boolean | null,   // true if accidents or bodywork repairs are mentioned
    "paint_issues": boolean | null        // true if paint defects, scratches or dents are mentioned
  },
  "notes": string                         // one concise sentence summarising standout positive or negative aspects
}"""

def build_user_message(title: str, description: str, price: str) -> str:
    return f"""Listing title: {title}
Price: {price}
Description:
{description}

Extract the structured information from this listing."""


# ── LLM Backends ─────────────────────────────────────────────────────────────

def call_llm(messages: list[dict]) -> str:
    """Call local Ollama instance with retries."""
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            log.debug(f"Ollama attempt {attempt}")
            payload = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.0},
            }
            resp = requests.post(OLLAMA_URL, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as e:
            last_error = e
            log.warning(f"Ollama attempt {attempt} failed: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"Ollama failed after {RETRY_ATTEMPTS} attempts. Last error: {last_error}")


# ── OCR KM Extraction ────────────────────────────────────────────────────────

# Pattern: digits (with optional dots/commas/spaces as thousand separators) followed by "km"
KM_PATTERN = re.compile(
    r"(\d[\d\s.,]*\d)\s*km\b",
    re.IGNORECASE,
)


def get_ocr_reader() -> easyocr.Reader:
    """Lazy-load EasyOCR reader."""
    global _ocr_reader
    if _ocr_reader is None:
        log.info("Loading EasyOCR reader...")
        _ocr_reader = easyocr.Reader(["en", "pt"], gpu=OCR_GPU)
    return _ocr_reader


def download_image(url: str) -> Image.Image | None:
    """Download an image URL and return a PIL Image."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content))
    except Exception as e:
        log.warning(f"Failed to download image: {e}")
        return None


def parse_km_value(text: str) -> int | None:
    """Extract a km value from OCR text like '223.184 km' → 223184."""
    digits = re.sub(r"[\s.,]", "", text)
    if not digits.isdigit():
        return None
    value = int(digits)
    if 100 < value < 1_000_000:
        return value
    return None


def extract_kms_from_images(image_urls: list[str]) -> int | None:
    """Try to read KMs from listing images using EasyOCR."""
    reader = get_ocr_reader()
    best_km = None

    for url in image_urls:
        img = download_image(url)
        if not img:
            continue
        try:
            results = reader.readtext(img)
            # Join all detected text into one string for pattern matching
            full_text = " ".join(text for _, text, _ in results)
            matches = KM_PATTERN.findall(full_text)
            for match in matches:
                kms = parse_km_value(match)
                if kms is not None:
                    log.info(f"OCR found {kms} km in image")
                    # Keep the largest reading (total odometer, not trip)
                    if best_km is None or kms > best_km:
                        best_km = kms
        except Exception as e:
            log.warning(f"OCR extraction failed: {e}")

    return best_km


# ── JSON Parsing ─────────────────────────────────────────────────────────────

def parse_llm_response(raw: str) -> dict:
    """Extract JSON from LLM response, stripping any markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


EMPTY_RESULT = {
    "is_vehicle": None,
    "is_dealer": None,
    "brand": None,
    "model": None,
    "year": None,
    "fuel_type": None,
    "transmission": None,
    "kms": None,
    "maintenance": {"timing_belt_done": None, "ipo_ok": None},
    "iuc_status": "unknown",
    "condition": {"accident_history": None, "paint_issues": None},
    "notes": "parse_error",
}


# ── Per-vehicle Analysis ──────────────────────────────────────────────────────

def analyse_vehicle(title: str, description: str, price: str,
                    image_urls: list[str] | None = None) -> dict:
    """Run LLM analysis on a single vehicle listing.
    Falls back to vision model to extract KMs from images if not found in text."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": build_user_message(title, description, price)},
    ]
    try:
        raw = call_llm(messages)
        result = parse_llm_response(raw)
    except Exception as e:
        log.error(f"Failed to analyse '{title}': {e}")
        return EMPTY_RESULT

    # Vision fallback: if KMs not found in text, try reading from images (vehicles only)
    if result.get("is_vehicle") and result.get("kms") is None and image_urls:
        log.info(f"KMs not in text, trying OCR on {len(image_urls)} images...")
        kms = extract_kms_from_images(image_urls)
        if kms is not None:
            result["kms"] = kms

    return result


# ── DataFrame Enrichment ──────────────────────────────────────────────────────

def flatten_result(result: dict) -> dict:
    """Flatten nested analysis dict into CSV-friendly columns.
    Any missing/null field is represented as 'unknown'."""
    def val(v):
        return "unknown" if v is None else v

    return {
        "llm_is_vehicle":         val(result.get("is_vehicle")),
        "llm_is_dealer":          val(result.get("is_dealer")),
        "llm_brand":              val(result.get("brand")),
        "llm_model":              val(result.get("model")),
        "llm_year":               val(result.get("year")),
        "llm_fuel_type":          val(result.get("fuel_type")),
        "llm_transmission":       val(result.get("transmission")),
        "llm_kms":                val(result.get("kms")),
        "llm_timing_belt_done":   val(result.get("maintenance", {}).get("timing_belt_done")),
        "llm_ipo_ok":             val(result.get("maintenance", {}).get("ipo_ok")),
        "llm_iuc_status":         val(result.get("iuc_status")),
        "llm_accident_history":   val(result.get("condition", {}).get("accident_history")),
        "llm_paint_issues":       val(result.get("condition", {}).get("paint_issues")),
        "llm_notes":              val(result.get("notes")),
    }


def enrich_csv(input_path: str, output_path: str | None = None) -> pd.DataFrame:
    """
    Load a scraped vehicles CSV, enrich each row with LLM analysis,
    and save the result to a new CSV.

    Args:
        input_path:  Path to the CSV produced by scraper.py
        output_path: Optional output path. Defaults to <input>_enriched.csv

    Returns:
        Enriched DataFrame
    """
    df = pd.read_csv(input_path)
    log.info(f"Loaded {len(df)} vehicles from {input_path}")

    required_cols = {"title", "description", "value"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV is missing columns: {missing}")

    enriched_rows = []
    for idx, row in df.iterrows():
        log.info(f"[{idx + 1}/{len(df)}] Analysing: {row['title'][:60]}...")
        # Parse image URLs from pipe-separated string
        raw_images = str(row.get("image_urls", ""))
        image_urls = [u for u in raw_images.split("|") if u.startswith("http")]
        result = analyse_vehicle(
            title=str(row.get("title", "")),
            description=str(row.get("description", "")),
            price=str(row.get("value", "")),
            image_urls=image_urls or None,
        )
        enriched_rows.append(flatten_result(result))

    enriched_df = pd.concat([df, pd.DataFrame(enriched_rows)], axis=1)

    if output_path is None:
        base = input_path.replace(".csv", "")
        output_path = f"{base}_enriched.csv"

    # Filter out non-vehicle listings
    non_vehicles = enriched_df["llm_is_vehicle"] == False  # noqa: E712
    if non_vehicles.any():
        log.info(f"Filtered out {non_vehicles.sum()} non-vehicle listing(s)")
    enriched_df = enriched_df[~non_vehicles].reset_index(drop=True)

    enriched_df.to_csv(output_path, index=False, encoding="utf-8")
    log.info(f"Saved enriched data → {output_path}")
    return enriched_df


# ── CLI Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python llm_parser.py <path_to_vehicles_csv> [output_csv]")
        print("Example: python llm_parser.py vehicles_2025-01-01_12-00-00.csv")
        sys.exit(1)

    input_file  = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    result_df = enrich_csv(input_file, output_file)
    print("\n── Enriched Preview ──────────────────────────────────────────")
    print(result_df[["title", "value", "llm_is_dealer", "llm_kms", "llm_iuc_status", "llm_notes"]].to_string(index=False))
"""
AutoSieve - LLM Parser Module
Reads scraped vehicle CSVs, enriches each row with structured LLM analysis,
and outputs an enriched CSV ready for the benchmarking engine (Phase 4).

LLM Backend: Ollama (local) → run `ollama serve` with llama3.1 pulled
"""

import json
import time
import base64
import logging
import pandas as pd
import requests

# ── Configuration ────────────────────────────────────────────────────────────

OLLAMA_MODEL        = "llama3.1"
OLLAMA_VISION_MODEL = "llava:13b"
OLLAMA_URL          = "http://localhost:11434/api/chat"

RETRY_ATTEMPTS = 3
RETRY_DELAY    = 2   # seconds between retries

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("autosieve.llm_parser")

# ── Prompt ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Portuguese automotive listing analyst.
Your job is to extract structured information from a car listing written in Portuguese or English.
Always respond ONLY with a valid JSON object — no explanation, no markdown, no extra text.

JSON schema:
{
  "is_dealer": boolean,          // true if seller appears to be a dealer (keywords: IVA dedutível, garantia, stand, empresa, NIPC)
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


# ── Vision KM Extraction ─────────────────────────────────────────────────────

VISION_PROMPT = """Look at this vehicle listing image carefully.
Does it show a dashboard, odometer, or instrument cluster?
If yes, read the exact number displayed before "km" or "KM" on the display (e.g. "9328 km").
Do NOT guess or estimate — only report the exact digits you can clearly read.
If there are multiple km readings, return the largest one (total odometer, not trip meter).
If you are NOT 100% confident in the reading, respond with: unknown
If this image does not show a dashboard or odometer, respond with: null
Respond with ONLY the integer, "unknown", or "null" — no other text."""


def download_image_as_base64(url: str) -> str | None:
    """Download an image URL and return its base64 encoding."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        log.warning(f"Failed to download image: {e}")
        return None


def extract_kms_from_images(image_urls: list[str]) -> int | None:
    """Try to read KMs from listing images using a vision model."""
    for url in image_urls:
        img_b64 = download_image_as_base64(url)
        if not img_b64:
            continue
        try:
            payload = {
                "model": OLLAMA_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": VISION_PROMPT,
                        "images": [img_b64],
                    }
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            }
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip().lower()
            if raw in ("null", "unknown"):
                if raw == "unknown":
                    log.info("Vision model not confident in reading")
                continue
            # Extract digits from response
            digits = "".join(c for c in raw if c.isdigit())
            if digits:
                kms = int(digits)
                # Sanity: most vehicles have < 999,999 km
                if kms > 999_999:
                    log.warning(f"Vision reading {kms} km is unrealistic, skipping")
                    continue
                if kms < 100:
                    log.warning(f"Vision reading {kms} km is too low, skipping")
                    continue
                log.info(f"Vision extracted KMs: {kms}")
                return kms
        except Exception as e:
            log.warning(f"Vision KM extraction failed: {e}")
    return None


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
    "is_dealer": None,
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

    # Vision fallback: if KMs not found in text, try reading from images
    if result.get("kms") is None and image_urls:
        log.info(f"KMs not in text, trying vision on {len(image_urls)} images...")
        kms = extract_kms_from_images(image_urls)
        if kms is not None:
            result["kms"] = kms

    return result


# ── DataFrame Enrichment ──────────────────────────────────────────────────────

def flatten_result(result: dict) -> dict:
    """Flatten nested analysis dict into CSV-friendly columns."""
    return {
        "llm_is_dealer":          result.get("is_dealer"),
        "llm_kms":                result.get("kms"),
        "llm_timing_belt_done":   result.get("maintenance", {}).get("timing_belt_done"),
        "llm_ipo_ok":             result.get("maintenance", {}).get("ipo_ok"),
        "llm_iuc_status":         result.get("iuc_status", "unknown"),
        "llm_accident_history":   result.get("condition", {}).get("accident_history"),
        "llm_paint_issues":       result.get("condition", {}).get("paint_issues"),
        "llm_notes":              result.get("notes", ""),
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
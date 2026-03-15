"""
AutoSieve - Centralized Configuration
Reads from .env file, falls back to defaults.
"""

import os
from pathlib import Path

# Load .env file if it exists
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── Scraper ──────────────────────────────────────────────────────────────────

NUM_VEHICLES = int(os.environ.get("NUM_VEHICLES", "5"))
MARKETPLACE_CITY = os.environ.get("MARKETPLACE_CITY", "lisbon")
MARKETPLACE_URL = f"https://www.facebook.com/marketplace/{MARKETPLACE_CITY}/vehicles?exact=0&sortBy=creation_time_descend"
CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "€")
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

# ── Ollama ───────────────────────────────────────────────────────────────────

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")

# ── LLM Parser ───────────────────────────────────────────────────────────────

RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", "3"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "2"))

# ── EasyOCR ──────────────────────────────────────────────────────────────────

OCR_GPU = os.environ.get("OCR_GPU", "false").lower() == "true"

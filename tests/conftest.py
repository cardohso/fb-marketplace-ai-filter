from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Marked tests that need heavy or external resources run only when opted in.
_GATED_MARKERS = {"browser": "AUTOSIEVE_RUN_BROWSER", "ocr": "AUTOSIEVE_RUN_OCR"}


def pytest_collection_modifyitems(items: Iterable[pytest.Item]) -> None:
    for item in items:
        for marker, env in _GATED_MARKERS.items():
            if marker in item.keywords and not os.environ.get(env):
                item.add_marker(pytest.mark.skip(reason=f"set {env}=1 to run {marker} tests"))


_ENV_KEYS = (
    "NUM_VEHICLES",
    "MARKETPLACE_CITY",
    "CURRENCY_SYMBOL",
    "HEADLESS",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "OLLAMA_HOST",
    "RETRY_ATTEMPTS",
    "RETRY_DELAY",
    "RETRY_DELAY_S",
    "OCR_GPU",
    "OCR_ENABLED",
    "DB_PATH",
    "GEO_LATITUDE",
    "GEO_LONGITUDE",
    "BROWSER_CHANNEL",
    "FB_STATE_PATH",
)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests independent of the developer's real .env and environment."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

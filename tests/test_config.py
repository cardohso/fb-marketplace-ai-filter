from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from autosieve.config import Settings, load_settings


def test_defaults_are_sane() -> None:
    s = Settings()
    assert s.num_vehicles == 5
    assert s.marketplace_city == "lisbon"
    assert s.currency_symbol == "€"
    assert s.ollama_host == "http://localhost:11434"
    assert s.geolocation == (38.7223, -9.1393)
    assert "marketplace/lisbon/vehicles" in s.marketplace_url


def test_env_file_is_read_as_utf8(tmp_path: Path) -> None:
    # The euro sign is the regression case: the old loader used the platform
    # default encoding and read it as mojibake on Windows.
    (tmp_path / ".env").write_text("CURRENCY_SYMBOL=€\nNUM_VEHICLES=12\n", encoding="utf-8")
    s = Settings()
    assert s.currency_symbol == "€"
    assert s.num_vehicles == 12


def test_legacy_ollama_url_with_api_path_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.lan:11434/api/chat")
    assert Settings().ollama_host == "http://ollama.lan:11434"


def test_ollama_host_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "localhost:11434")
    with pytest.raises(ValidationError, match="absolute URL"):
        Settings()


def test_invalid_number_fails_readably(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUM_VEHICLES", "lots")
    with pytest.raises(ValidationError, match="num_vehicles"):
        Settings()


def test_num_vehicles_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUM_VEHICLES", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_city_drives_geolocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CITY", " Porto ")
    s = Settings()
    assert s.marketplace_city == "porto"
    assert s.geolocation == (41.1579, -8.6291)


def test_unknown_city_has_no_geolocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CITY", "evora")
    assert Settings().geolocation is None


def test_explicit_geo_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_LATITUDE", "40.0")
    monkeypatch.setenv("GEO_LONGITUDE", "-8.0")
    assert Settings().geolocation == (40.0, -8.0)


def test_half_geo_pair_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_LATITUDE", "40.0")
    with pytest.raises(ValidationError, match="together"):
        Settings()


def test_legacy_retry_delay_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRY_DELAY", "0.5")
    assert Settings().retry_delay_s == 0.5


def test_overrides_beat_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NUM_VEHICLES", "3")
    assert load_settings(num_vehicles=9).num_vehicles == 9

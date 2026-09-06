from __future__ import annotations

from pathlib import Path

import pytest
import responses

from autosieve.cli import build_parser, main
from autosieve.models import Analysis, AnalysisRecord, Listing
from autosieve.storage import Store


def seed(db: Path) -> None:
    with Store(db) as store:
        listing = Listing(
            id="1234567890",
            url="https://www.facebook.com/marketplace/item/1234567890/",
            title="Renault Clio",
            price_eur=12_500,
            description="Bom estado",
        )
        store.upsert_listing(listing)
        store.save_analysis(
            AnalysisRecord(
                listing_id=listing.id, model="llama3.1", analysis=Analysis(is_vehicle=True)
            )
        )


def test_parser_has_all_commands() -> None:
    parser = build_parser()
    for command in ("scrape", "enrich", "run", "export", "status"):
        args = parser.parse_args([command])
        assert args.command == command


def test_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "test.db"
    seed(db)
    assert main(["--db", str(db), "status"]) == 0
    out = capsys.readouterr().out
    assert "listings" in out
    assert "analysed" in out


def test_export_writes_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "test.db"
    seed(db)
    out = tmp_path / "exports" / "cars.csv"
    assert main(["--db", str(db), "export", "--out", str(out)]) == 0
    assert out.exists()
    assert "1 row(s)" in capsys.readouterr().out
    header = out.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("id,url,title,price_eur")


def test_export_default_path_is_timestamped(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    seed(db)
    assert main(["--db", str(db), "export"]) == 0
    files = list(tmp_path.glob("vehicles_*.csv"))
    assert len(files) == 1


@responses.activate
def test_enrich_fails_fast_when_ollama_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `responses` is active with no registered URLs, so every request is refused.
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.test:11434")
    db = tmp_path / "test.db"
    seed(db)
    assert main(["--db", str(db), "enrich"]) == 1
    err = capsys.readouterr().err
    assert "cannot reach Ollama" in err
    assert "Traceback" not in err


def test_configuration_error_is_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--db", str(tmp_path / "x.db"), "scrape", "--limit", "0"]) == 1
    err = capsys.readouterr().err
    assert "Configuration error" in err
    assert "num_vehicles" in err

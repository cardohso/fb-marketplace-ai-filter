from __future__ import annotations

import sys

import pytest
import requests
import responses

from autosieve.ocr import (
    ImageDownloadError,
    ImagePolicy,
    OcrUnavailableError,
    OdometerReader,
    download_image,
    is_allowed_url,
)

POLICY = ImagePolicy(allowed_host_suffixes=("fbcdn.net",), max_bytes=1_000, timeout_s=1.0)
IMG = "https://scontent-lis1-1.xx.fbcdn.net/v/t45/photo.jpg"


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (IMG, True),
        ("https://fbcdn.net/x.jpg", True),
        ("http://scontent.fbcdn.net/x.jpg", False),
        ("https://evil.example/scontent.fbcdn.net/x.jpg", False),
        ("https://notfbcdn.net/x.jpg", False),
        ("https://fbcdn.net.evil.example/x.jpg", False),
        ("ftp://scontent.fbcdn.net/x.jpg", False),
        ("not a url", False),
    ],
)
def test_is_allowed_url(url: str, allowed: bool) -> None:
    assert is_allowed_url(url, POLICY) is allowed


@responses.activate
def test_download_image_ok() -> None:
    responses.add(responses.GET, IMG, body=b"\xff\xd8jpegbytes")
    assert download_image(IMG, POLICY) == b"\xff\xd8jpegbytes"


@responses.activate
def test_download_refuses_disallowed_url_without_a_request() -> None:
    with pytest.raises(ImageDownloadError, match="not an allowed"):
        download_image("https://evil.example/x.jpg", POLICY)
    assert len(responses.calls) == 0


@responses.activate
def test_download_rejects_declared_oversize() -> None:
    responses.add(responses.GET, IMG, body=b"x", headers={"Content-Length": "5000"})
    with pytest.raises(ImageDownloadError, match="over the"):
        download_image(IMG, POLICY)


@responses.activate
def test_download_rejects_streamed_oversize() -> None:
    responses.add(responses.GET, IMG, body=b"x" * 2_000)
    with pytest.raises(ImageDownloadError, match="exceeded"):
        download_image(IMG, POLICY)


@responses.activate
def test_download_wraps_http_errors() -> None:
    responses.add(responses.GET, IMG, status=403)
    with pytest.raises(ImageDownloadError, match="download failed"):
        download_image(IMG, POLICY)
    responses.add(responses.GET, IMG + "?2", body=requests.ConnectionError("boom"))
    with pytest.raises(ImageDownloadError):
        download_image(IMG + "?2", POLICY)


# ── odometer selection logic (no EasyOCR involved) ───────────────────────────


def test_reader_stops_at_first_image_with_a_reading() -> None:
    texts = {
        b"1": "Renault Clio 2019",
        b"2": "0 20 40 180 km 312 km 187.432 km",
        b"3": "999.999 km",
    }
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return url.encode()

    reader = OdometerReader(text_reader=lambda b: texts[b])
    assert reader.read_kms(["1", "2", "3"], fetch=fetch) == 187_432
    assert fetched == ["1", "2"]


def test_reader_skips_failed_downloads_and_ocr_errors() -> None:
    def fetch(url: str) -> bytes:
        if url == "bad":
            raise ImageDownloadError("nope")
        return url.encode()

    def ocr(image: bytes) -> str:
        if image == b"boom":
            raise RuntimeError("cuda exploded")
        return "154.000 km"

    reader = OdometerReader(text_reader=ocr)
    assert reader.read_kms(["bad", "boom", "ok"], fetch=fetch) == 154_000


def test_reader_respects_max_images_and_returns_none() -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b""

    reader = OdometerReader(text_reader=lambda _: "180 km")
    assert reader.read_kms(["a", "b", "c", "d"], fetch=fetch, max_images=2) is None
    assert calls == ["a", "b"]


def test_missing_easyocr_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "easyocr", None)
    reader = OdometerReader()
    with pytest.raises(OcrUnavailableError, match=r"autosieve\[ocr\]"):
        reader.read_kms(["x"], fetch=lambda _: b"")

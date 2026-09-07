"""End-to-end OCR against the real EasyOCR reader.

Opt-in: needs the ``[ocr]`` extra (EasyOCR + PyTorch) and a one-time model
download. Run with ``AUTOSIEVE_RUN_OCR=1 pytest``. Skipped otherwise, and if
EasyOCR is not installed the import guard skips collection.
"""

from __future__ import annotations

from io import BytesIO

import pytest

pytest.importorskip("easyocr")
pytest.importorskip("PIL")

from PIL import Image, ImageDraw, ImageFont

from autosieve.ocr import OdometerReader

pytestmark = pytest.mark.ocr


def _dashboard_png(total: str, trip: str, speed: str) -> bytes:
    """A crude dashboard: a large odometer total, a smaller trip, a speed reading."""
    img = Image.new("RGB", (600, 300), "black")
    draw = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("arialbd.ttf", 64)
        small = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        big = small = ImageFont.load_default()
    draw.text((60, 110), total, fill="white", font=big)
    draw.text((70, 210), trip, fill=(170, 170, 170), font=small)
    draw.text((440, 30), speed, fill="white", font=small)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_reads_the_odometer_total_not_the_trip_or_speed() -> None:
    images = {"dash.png": _dashboard_png("187432 km", "312.5 km", "120")}
    reader = OdometerReader()  # real EasyOCR
    km = reader.read_kms(["dash.png"], fetch=lambda url: images[url], max_images=1)
    assert km == 187_432


def test_returns_none_when_no_plausible_reading() -> None:
    images = {"blank.png": _dashboard_png("Service due", "", "120")}
    reader = OdometerReader()
    assert reader.read_kms(["blank.png"], fetch=lambda url: images[url]) is None


def test_dhash_distinguishes_similar_from_different_images() -> None:
    from autosieve.duplicates import hamming, image_dhash

    base = _dashboard_png("187432 km", "312 km", "120")
    near = _dashboard_png("187432 km", "312 km", "121")  # tiny change
    far = _dashboard_png("Service due", "", "80")

    h_base, h_near, h_far = image_dhash(base), image_dhash(near), image_dhash(far)
    assert hamming(h_base, h_near) <= 6  # basically the same picture
    assert hamming(h_base, h_far) > hamming(h_base, h_near)

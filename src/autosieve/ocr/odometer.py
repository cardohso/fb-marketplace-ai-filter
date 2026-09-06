"""Read the odometer from dashboard photos.

EasyOCR (and with it PyTorch) is imported only when a reading is actually
attempted, so ``autosieve`` starts instantly and the ``[ocr]`` extra stays
optional. The text recogniser is injectable so the selection logic is tested
without any model.

Heuristics, and why:

* Photos are tried in order and the search stops at the first photo that
  yields a reading. A dashboard photo shows total and trip together, so the
  largest number on that one photo is the odometer; scanning every remaining
  photo only adds false positives from stickers and documents.
* A reading needs at least four digits. Speedometer dials and trip meters
  produce three-digit "km" strings that are not mileage.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from io import BytesIO

from autosieve.ocr.images import ImageDownloadError
from autosieve.parsing.km import OCR_MIN_KM, largest_km

log = logging.getLogger(__name__)

TextReader = Callable[[bytes], str]


class OcrUnavailableError(Exception):
    """EasyOCR is not installed. Install with ``pip install autosieve[ocr]``."""


def _easyocr_text_reader(*, gpu: bool, languages: tuple[str, ...]) -> TextReader:
    try:
        import easyocr
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise OcrUnavailableError(
            "EasyOCR is not installed. Install the OCR extra: pip install 'autosieve[ocr]'"
        ) from exc

    log.info("Loading EasyOCR (%s)...", "GPU" if gpu else "CPU")
    reader = easyocr.Reader(list(languages), gpu=gpu, verbose=False)

    def read(image_bytes: bytes) -> str:
        # EasyOCR accepts paths, bytes and numpy arrays; a PIL image only when it
        # happens to be a JPEG. Converting to an RGB array works for every format.
        with Image.open(BytesIO(image_bytes)) as img:
            array = np.asarray(img.convert("RGB"))
        pieces = reader.readtext(array, detail=0)
        return " ".join(str(piece) for piece in pieces)

    return read


class OdometerReader:
    def __init__(
        self,
        *,
        text_reader: TextReader | None = None,
        gpu: bool = False,
        languages: tuple[str, ...] = ("en", "pt"),
        min_km: int = OCR_MIN_KM,
    ) -> None:
        self._text_reader = text_reader
        self._gpu = gpu
        self._languages = languages
        self._min_km = min_km

    def _reader(self) -> TextReader:
        if self._text_reader is None:
            self._text_reader = _easyocr_text_reader(gpu=self._gpu, languages=self._languages)
        return self._text_reader

    def read_kms(
        self,
        image_urls: Iterable[str],
        *,
        fetch: Callable[[str], bytes],
        max_images: int = 6,
    ) -> int | None:
        """Mileage from the first photo that shows one, or None."""
        reader = self._reader()
        for index, url in enumerate(image_urls):
            if index >= max_images:
                break
            try:
                image_bytes = fetch(url)
            except ImageDownloadError as exc:
                log.warning("skipping image %d: %s", index + 1, exc)
                continue
            try:
                text = reader(image_bytes)
            except Exception as exc:  # OCR libraries raise all sorts of things
                log.warning("OCR failed on image %d: %s", index + 1, exc)
                continue
            value = largest_km(text, minimum=self._min_km)
            if value is not None:
                log.info("OCR read %d km from image %d", value, index + 1)
                return value
        return None

"""Fetch listing photos defensively.

Image URLs come out of scraped HTML, which is untrusted input. Only HTTPS URLs
on allow-listed hosts are fetched, and the body is capped before it is read
into memory, so a hostile or broken page cannot point the scraper at an
internal address or make it download a multi-gigabyte blob.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from autosieve.config import Settings

log = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024


class ImageDownloadError(Exception):
    """The image was refused, too large, or could not be fetched."""


@dataclass(frozen=True, slots=True)
class ImagePolicy:
    allowed_host_suffixes: tuple[str, ...] = ("fbcdn.net", "facebook.com")
    max_bytes: int = 10_000_000
    timeout_s: float = 15.0

    @classmethod
    def from_settings(cls, settings: Settings) -> ImagePolicy:
        return cls(
            allowed_host_suffixes=settings.image_allowed_host_suffixes,
            max_bytes=settings.image_max_bytes,
            timeout_s=settings.image_timeout_s,
        )


def is_allowed_url(url: str, policy: ImagePolicy) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(
        host == suffix or host.endswith("." + suffix) for suffix in policy.allowed_host_suffixes
    )


def download_image(url: str, policy: ImagePolicy, session: requests.Session | None = None) -> bytes:
    """Return the image bytes, or raise :class:`ImageDownloadError`."""
    if not is_allowed_url(url, policy):
        raise ImageDownloadError(f"refusing to fetch {url[:80]}: not an allowed https host")
    http = session or requests.Session()
    try:
        with http.get(url, timeout=policy.timeout_s, stream=True) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > policy.max_bytes:
                raise ImageDownloadError(
                    f"image is {declared} bytes, over the {policy.max_bytes} cap"
                )
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(CHUNK_SIZE):
                total += len(chunk)
                if total > policy.max_bytes:
                    raise ImageDownloadError(f"image exceeded the {policy.max_bytes} byte cap")
                chunks.append(chunk)
    except requests.RequestException as exc:
        raise ImageDownloadError(f"download failed: {exc}") from exc
    return b"".join(chunks)

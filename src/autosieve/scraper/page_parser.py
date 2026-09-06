"""Turn the HTML of one listing page into a :class:`Listing`.

This module never touches a browser. It takes a string and returns data, so it
can be driven by saved fixtures and unit-tested without Facebook. Everything
Facebook-specific it relies on is a visible UI string listed in
:mod:`autosieve.scraper.locale`, which also documents the observed page layout.

The page is treated as an ordered list of short text "lines" (leaf elements).
Facebook's class names are obfuscated and change constantly; the visible text
and its order are the only stable structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from autosieve.models import Listing, max_plausible_year
from autosieve.parsing.km import first_km
from autosieve.parsing.normalize import fold, normalize_fuel, normalize_gearbox
from autosieve.parsing.price import parse_price
from autosieve.parsing.urls import extract_listing_id
from autosieve.scraper import locale
from autosieve.scraper.errors import ListingUnavailableError

# The price sits directly under the title; anything further down is another listing.
PRICE_WINDOW = 3
# Title, price, posted-ago, location: the location is within a few lines of the title.
LOCATION_WINDOW = 5
MAX_DETAIL_LINES = 20
MAX_DETAIL_LINE_LEN = 80
MAX_ATTRIBUTE_VALUE_LEN = 80
MAX_IMAGES = 30
_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


@dataclass(frozen=True, slots=True)
class _Lines:
    """Leaf text nodes in document order, with the index of the title."""

    texts: list[str]
    title_index: int | None

    def index_of(self, labels: tuple[str, ...]) -> int | None:
        return next((i for i, t in enumerate(self.texts) if t in labels), None)

    def window(self, start: int, size: int) -> list[str]:
        return self.texts[start + 1 : start + 1 + size]


def _leaf_lines(soup: BeautifulSoup) -> _Lines:
    texts: list[str] = []
    title_index: int | None = None
    h1 = soup.find("h1")
    for el in soup.find_all(["h1", "h2", "span", "div", "a"]):
        if el.find(True) is not None:
            continue
        text = el.get_text(" ", strip=True)
        if not text or (texts and texts[-1] == text):
            continue
        if title_index is None and h1 is not None and (el is h1 or h1 in el.parents):
            title_index = len(texts)
        texts.append(text)
    return _Lines(texts=texts, title_index=title_index)


def _is_ui_label(text: str) -> bool:
    return text in locale.UI_LABELS


def _strip_ui_affixes(text: str) -> str:
    for heading in locale.DESCRIPTION_HEADINGS:
        if text.startswith(heading):
            text = text[len(heading) :].strip()
    for suffix in (*locale.SEE_MORE, *locale.SEE_LESS):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


# ── Field extractors ─────────────────────────────────────────────────────────


def _title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else None


def _price(lines: _Lines, currency: str) -> tuple[str | None, int | None]:
    """The price line right under the title. "GRÁTIS" is recorded with no numeric value."""
    if lines.title_index is None:
        return None, None
    for text in lines.window(lines.title_index, PRICE_WINDOW):
        if len(text) >= 50:
            continue
        if locale.is_free_price(text):
            return text, None
        if currency in text:
            return text, parse_price(text)
    return None, None


def _location(lines: _Lines, price_raw: str | None) -> str | None:
    """The short line under the title that is neither the price nor the posted-ago line."""
    if lines.title_index is None:
        return None
    for text in lines.window(lines.title_index, LOCATION_WINDOW):
        if text in locale.DESCRIPTION_HEADINGS or text in locale.DETAILS_HEADINGS:
            break
        if text == price_raw or _is_ui_label(text) or len(text) > 60:
            continue
        if locale.is_posted_ago(text) or locale.is_free_price(text):
            continue
        return text
    return None


def _is_description_stop(text: str, location: str | None) -> bool:
    return (
        text in locale.DESCRIPTION_STOP_LABELS
        or text in locale.DETAILS_HEADINGS
        or locale.is_location_footer(text)
        or (location is not None and text == location)
    )


def _description_and_attributes(
    lines: _Lines, location: str | None
) -> tuple[str | None, tuple[str, ...]]:
    """Seller prose after the description heading, plus any label/value pairs in front of it.

    Facebook renders attributes such as "Estado" / "Usado - Como novo" between
    the heading and the prose. They are returned as ``"Estado: Usado - Como novo"``
    so the details extractors can read them like any other detail line.
    """
    start = lines.index_of(locale.DESCRIPTION_HEADINGS)
    if start is None:
        return _description_fallback(lines, location), ()

    attributes: list[str] = []
    parts: list[str] = []
    texts = lines.texts
    i = start + 1
    while i < len(texts):
        text = texts[i]
        if _is_description_stop(text, location):
            break
        has_value = i + 1 < len(texts) and not _is_description_stop(texts[i + 1], location)
        if (
            locale.is_attribute_label(text)
            and has_value
            and len(texts[i + 1]) <= MAX_ATTRIBUTE_VALUE_LEN
        ):
            attributes.append(f"{text.rstrip(':')}: {texts[i + 1]}")
            i += 2
            continue
        if not _is_ui_label(text):
            cleaned = _strip_ui_affixes(text)
            if cleaned:
                parts.append(cleaned)
        i += 1
    return ("\n".join(parts) or None), tuple(attributes)


def _description_fallback(lines: _Lines, location: str | None) -> str | None:
    """No heading: the longest prose line after the title, before the sidebar starts."""
    if lines.title_index is None:
        return None
    best = ""
    for text in lines.texts[lines.title_index + 1 :]:
        if text in locale.DESCRIPTION_STOP_LABELS and text not in (
            *locale.SEE_MORE,
            *locale.SEE_LESS,
        ):
            break
        if _is_ui_label(text) or len(text) >= 3000 or text == location:
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in locale.BOILERPLATE_KEYWORDS):
            continue
        cleaned = _strip_ui_affixes(text)
        if len(cleaned) > 30 and len(cleaned) > len(best):
            best = cleaned
    return best or None


def _details(lines: _Lines) -> tuple[str, ...]:
    """Short lines under a details heading, when the page has one."""
    start = lines.index_of(locale.DETAILS_HEADINGS)
    if start is None:
        return ()
    collected: list[str] = []
    for text in lines.texts[start + 1 :]:
        if text in locale.DESCRIPTION_HEADINGS or text in locale.DESCRIPTION_STOP_LABELS:
            break
        if _is_ui_label(text) or len(text) > MAX_DETAIL_LINE_LEN:
            continue
        collected.append(text)
        if len(collected) >= MAX_DETAIL_LINES:
            break
    return tuple(collected)


def _kms_from_details(details: tuple[str, ...]) -> int | None:
    for line in details:
        if line.startswith(locale.DRIVEN_PREFIXES) or fold(line).startswith("quilometragem"):
            value = first_km(line)
            if value is not None:
                return value
    for line in details:
        value = first_km(line)
        if value is not None:
            return value
    return None


def _fuel_from_details(details: tuple[str, ...]) -> str | None:
    for line in details:
        if len(line) <= 40:
            fuel = normalize_fuel(line)
            if fuel is not None:
                return fuel
    return None


def _gearbox_from_details(details: tuple[str, ...]) -> str | None:
    for line in details:
        folded = fold(line)
        if len(line) <= 40 and ("transmiss" in folded or "caixa" in folded or "gear" in folded):
            gearbox = normalize_gearbox(line)
            if gearbox is not None:
                return gearbox
    for line in details:
        if len(line) <= 25:
            gearbox = normalize_gearbox(line)
            if gearbox is not None:
                return gearbox
    return None


def _year(title: str | None, details: tuple[str, ...]) -> int | None:
    upper = max_plausible_year()
    for text in (title or "", *details):
        for match in _YEAR.finditer(text):
            year = int(match.group(1))
            if year <= upper:
                return year
    return None


def _images(soup: BeautifulSoup) -> tuple[str, ...]:
    """Product photos by alt text; fall back to any CDN image that is not a profile picture."""
    by_alt: list[str] = []
    fallback: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src")
        alt = img.get("alt")
        if not isinstance(src, str) or not src.startswith("http") or src in seen:
            continue
        alt_text = alt if isinstance(alt, str) else ""
        seen.add(src)
        if alt_text.startswith(locale.PRODUCT_PHOTO_ALT_PREFIXES):
            by_alt.append(src)
        elif "fbcdn" in src and not any(
            m in alt_text.lower() for m in locale.PROFILE_PHOTO_MARKERS
        ):
            fallback.append(src)
    chosen = by_alt or fallback
    return tuple(chosen[:MAX_IMAGES])


def _looks_unavailable(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True)
    return any(marker in text for marker in locale.LISTING_UNAVAILABLE_MARKERS)


# ── Entry point ──────────────────────────────────────────────────────────────


def parse_listing_html(
    html: str,
    *,
    url: str,
    city: str | None = None,
    currency: str = "€",
) -> Listing:
    """Parse a listing page. Raises :class:`ListingUnavailableError` for removed listings.

    A page that renders but lacks a description or price still returns a
    :class:`Listing`; check ``listing.is_complete`` and keep the HTML for
    inspection when it is false.
    """
    listing_id = extract_listing_id(url)
    if listing_id is None:
        raise ValueError(f"not a Marketplace item URL: {url}")

    soup = BeautifulSoup(html, "html.parser")
    title = _title(soup)
    if title is None and _looks_unavailable(soup):
        raise ListingUnavailableError(f"listing {listing_id} is no longer available")

    lines = _leaf_lines(soup)
    price_raw, price_eur = _price(lines, currency)
    location = _location(lines, price_raw)
    description, attributes = _description_and_attributes(lines, location)
    details = (*_details(lines), *attributes)

    return Listing(
        id=listing_id,
        url=url,
        title=title,
        price_eur=price_eur,
        price_raw=price_raw,
        description=description,
        details=details,
        kms=_kms_from_details(details),
        fuel=_fuel_from_details(details),
        gearbox=_gearbox_from_details(details),
        year=_year(title, details),
        image_urls=_images(soup),
        city=city,
        location=location,
    )

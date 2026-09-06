"""Turn the HTML of one listing page into a :class:`Listing`.

This module never touches a browser. It takes a string and returns data, so it
can be driven by saved fixtures and unit-tested without Facebook. Everything
Facebook-specific it relies on is a visible UI string listed in
:mod:`autosieve.scraper.locale`.

The page is treated as an ordered list of short text "lines" (leaf elements).
Facebook's class names are obfuscated and change constantly; the visible text
and its order are the only stable structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from autosieve.models import Listing, max_plausible_year
from autosieve.parsing.km import first_km
from autosieve.parsing.normalize import fold, normalize_fuel, normalize_gearbox
from autosieve.parsing.price import parse_price
from autosieve.parsing.urls import extract_listing_id
from autosieve.scraper import locale
from autosieve.scraper.errors import ListingUnavailableError

MAX_DETAIL_LINES = 20
MAX_DETAIL_LINE_LEN = 80
MAX_IMAGES = 30
_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


@dataclass(frozen=True, slots=True)
class _Lines:
    """Leaf text nodes in document order, with the index of the title."""

    texts: list[str]
    title_index: int | None


def _leaf_lines(soup: BeautifulSoup) -> _Lines:
    texts: list[str] = []
    title_index: int | None = None
    h1 = soup.find("h1")
    for el in soup.find_all(["h1", "h2", "span", "div", "a"]):
        if not isinstance(el, Tag) or el.find(True) is not None:
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
    """The first short, parseable price after the title; before it only as a last resort."""
    candidates: list[tuple[int, str, int]] = []
    for index, text in enumerate(lines.texts):
        if currency not in text or len(text) >= 50:
            continue
        value = parse_price(text)
        if value is not None:
            candidates.append((index, text, value))
    if not candidates:
        return None, None
    start = lines.title_index if lines.title_index is not None else -1
    after_title = [c for c in candidates if c[0] > start]
    _, raw, value = (after_title or candidates)[0]
    return raw, value


def _description(soup: BeautifulSoup, lines: _Lines) -> str | None:
    """Strategy 1: the container that holds the description heading."""
    heading = soup.find(
        lambda tag: (
            isinstance(tag, Tag)
            and tag.name in {"span", "div", "h2"}
            and tag.get_text(strip=True) in locale.DESCRIPTION_HEADINGS
        )
    )
    if isinstance(heading, Tag):
        container: Tag | None = heading
        for _ in range(4):
            container = container.parent if container is not None else None
            if not isinstance(container, Tag):
                break
            text = _strip_ui_affixes(container.get_text(" ", strip=True))
            if len(text) > 10:
                return text
    return _description_fallback(lines)


def _description_fallback(lines: _Lines) -> str | None:
    """Strategy 2: the longest prose span after the details heading."""
    in_details = False
    best = ""
    for text in lines.texts:
        if text in locale.DETAILS_HEADINGS:
            in_details = True
            continue
        if not in_details or _is_ui_label(text) or len(text) >= 3000:
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in locale.BOILERPLATE_KEYWORDS):
            continue
        if text.startswith(("Usado", "Novo", "Used", "New")):
            continue
        cleaned = _strip_ui_affixes(text)
        if len(cleaned) > 30 and len(cleaned) > len(best):
            best = cleaned
    return best or None


def _details(lines: _Lines) -> tuple[str, ...]:
    """Short lines that follow the details heading, up to the description or a limit."""
    try:
        start = next(i for i, t in enumerate(lines.texts) if t in locale.DETAILS_HEADINGS)
    except StopIteration:
        return ()
    collected: list[str] = []
    for text in lines.texts[start + 1 :]:
        if text in locale.DESCRIPTION_HEADINGS or text in locale.SEE_MORE:
            break
        if _is_ui_label(text) or len(text) > MAX_DETAIL_LINE_LEN:
            continue
        collected.append(text)
        if len(collected) >= MAX_DETAIL_LINES:
            break
    return tuple(collected)


def _kms_from_details(details: tuple[str, ...]) -> int | None:
    for line in details:
        if line.startswith(locale.DRIVEN_PREFIXES):
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
    details = _details(lines)

    return Listing(
        id=listing_id,
        url=url,
        title=title,
        price_eur=price_eur,
        price_raw=price_raw,
        description=_description(soup, lines),
        details=details,
        kms=_kms_from_details(details),
        fuel=_fuel_from_details(details),
        gearbox=_gearbox_from_details(details),
        year=_year(title, details),
        image_urls=_images(soup),
        city=city,
    )

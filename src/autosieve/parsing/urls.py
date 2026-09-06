"""Facebook Marketplace listing URL helpers.

Marketplace item links carry tracking query strings, so two links to the same
item rarely compare equal as strings. The numeric item id is the only stable
identity, and everything downstream keys on it.
"""

from __future__ import annotations

import re

FACEBOOK_ORIGIN = "https://www.facebook.com"
_ITEM_ID = re.compile(r"/marketplace/item/(\d{6,})(?:[/?#]|$)")


def extract_listing_id(href: str) -> str | None:
    """Return the numeric item id from any Marketplace item href, or None."""
    match = _ITEM_ID.search(href)
    return match.group(1) if match else None


def canonical_listing_url(listing_id: str) -> str:
    """The tracking-free URL for a listing id."""
    if not listing_id.isdigit():
        raise ValueError(f"listing id must be numeric, got {listing_id!r}")
    return f"{FACEBOOK_ORIGIN}/marketplace/item/{listing_id}/"


def absolutize(href: str, origin: str = FACEBOOK_ORIGIN) -> str:
    """Turn a site-relative href into an absolute URL; leave absolute URLs alone."""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    return origin.rstrip("/") + "/" + href.lstrip("/")

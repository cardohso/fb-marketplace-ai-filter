from __future__ import annotations

import pytest

from autosieve.parsing.urls import absolutize, canonical_listing_url, extract_listing_id


@pytest.mark.parametrize(
    "href",
    [
        "/marketplace/item/1234567890/",
        "/marketplace/item/1234567890/?ref=browse_tab&referral_code=abc",
        "https://www.facebook.com/marketplace/item/1234567890?tracking=%7B%22x%22%7D",
        "https://m.facebook.com/marketplace/item/1234567890",
    ],
)
def test_extract_listing_id(href: str) -> None:
    assert extract_listing_id(href) == "1234567890"


def test_non_item_links_have_no_id() -> None:
    assert extract_listing_id("/marketplace/lisbon/vehicles") is None
    assert extract_listing_id("/marketplace/item/abc/") is None


def test_canonical_url_drops_tracking() -> None:
    assert canonical_listing_url("1234567890") == (
        "https://www.facebook.com/marketplace/item/1234567890/"
    )
    with pytest.raises(ValueError, match="numeric"):
        canonical_listing_url("nope")


def test_absolutize() -> None:
    assert absolutize("/marketplace/item/1/") == "https://www.facebook.com/marketplace/item/1/"
    assert absolutize("https://x.test/a") == "https://x.test/a"
    assert absolutize("//scontent.fbcdn.net/p.jpg") == "https://scontent.fbcdn.net/p.jpg"

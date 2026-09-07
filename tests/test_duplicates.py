from __future__ import annotations

import pytest

from autosieve.duplicates import duplicate_groups, hamming
from autosieve.storage import Store


def test_hamming() -> None:
    assert hamming(0b1010, 0b1010) == 0
    assert hamming(0b1111, 0b1010) == 2
    assert hamming(0, (1 << 64) - 1) == 64


def test_duplicate_groups_finds_shared_images() -> None:
    # a and b share a near-identical image (distance 1); c is unrelated.
    hashes = {
        "a": [0b0000],
        "b": [0b0001],  # 1 bit from a
        "c": [0b1111_1111],
    }
    groups = duplicate_groups(hashes, max_distance=2)
    assert groups == [["a", "b"]] or groups == [["b", "a"]]


def test_duplicate_groups_transitive_grouping() -> None:
    # a~b and b~d chain into one group even if a and d are far apart.
    hashes = {"a": [0], "b": [1], "d": [3], "z": [0xFFFF]}
    groups = duplicate_groups(hashes, max_distance=2)
    assert len(groups) == 1
    assert set(groups[0]) == {"a", "b", "d"}


def test_duplicate_groups_ignores_singletons_and_empty() -> None:
    hashes = {"a": [0], "b": [0xF0F0], "empty": []}
    assert duplicate_groups(hashes, max_distance=2) == []


def test_duplicate_groups_matches_any_image_pair() -> None:
    # b's second image matches a's only image.
    hashes = {"a": [0b1010], "b": [0xFFFF, 0b1011]}
    groups = duplicate_groups(hashes, max_distance=2)
    assert len(groups) == 1 and set(groups[0]) == {"a", "b"}


def test_image_hash_store_round_trip() -> None:
    with Store(":memory:") as store:
        store.upsert_listing_min("1111111111")
        assert not store.has_image_hashes("1111111111")
        store.save_image_hashes("1111111111", [10, 20, 30])
        assert store.has_image_hashes("1111111111")
        assert store.all_image_hashes() == {"1111111111": [10, 20, 30]}
        # Re-saving replaces, not appends.
        store.save_image_hashes("1111111111", [99])
        assert store.all_image_hashes() == {"1111111111": [99]}


@pytest.fixture(autouse=True)
def _min_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A tiny helper so the store test does not need a full Listing.
    from autosieve.models import Listing
    from autosieve.storage.db import Store as RealStore

    def upsert_listing_min(self: RealStore, listing_id: str) -> None:
        self.upsert_listing(
            Listing(
                id=listing_id,
                url=f"https://www.facebook.com/marketplace/item/{listing_id}/",
                title="Car",
            )
        )

    monkeypatch.setattr(RealStore, "upsert_listing_min", upsert_listing_min, raising=False)

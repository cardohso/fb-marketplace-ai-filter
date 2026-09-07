"""Find listings that share the same photo.

A perceptual hash (dHash) of each listing image lets us spot the same picture
reused across listings: a hidden dealer reposting one car under several ads, or
a scam using a stock photo. Near-identical images have a small Hamming distance
between their hashes, so listings are grouped when any of their images match.

The hashing needs Pillow (the ``[ocr]`` extra); the grouping is pure Python.
"""

from __future__ import annotations

from io import BytesIO

HASH_SIZE = 8  # dHash compares 8x8 gradients -> 64-bit hash
# Two images within this Hamming distance are treated as the same picture.
DEFAULT_MAX_DISTANCE = 6


class DuplicatesUnavailableError(Exception):
    """Pillow is not installed. Install the OCR extra: pip install 'autosieve[ocr]'."""


def image_dhash(image_bytes: bytes) -> int:
    """A 64-bit difference hash of an image (row-wise brightness gradients)."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise DuplicatesUnavailableError(
            "Pillow is not installed. Install the OCR extra: pip install 'autosieve[ocr]'"
        ) from exc
    with Image.open(BytesIO(image_bytes)) as img:
        small = img.convert("L").resize((HASH_SIZE + 1, HASH_SIZE))
    # tobytes() on an "L" image is one byte per pixel, row-major.
    pixels = list(small.tobytes())
    width = HASH_SIZE + 1
    bits = 0
    for row in range(HASH_SIZE):
        for col in range(HASH_SIZE):
            left = pixels[row * width + col]
            right = pixels[row * width + col + 1]
            bits = (bits << 1) | int(left > right)
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _min_distance(a: list[int], b: list[int]) -> int:
    """Closest match between any image of one listing and any of another."""
    return min((hamming(x, y) for x in a for y in b), default=64)


def duplicate_groups(
    hashes_by_listing: dict[str, list[int]], *, max_distance: int = DEFAULT_MAX_DISTANCE
) -> list[list[str]]:
    """Group listing ids that share a near-identical image. Singletons are dropped."""
    ids = [i for i, hashes in hashes_by_listing.items() if hashes]
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            if _min_distance(hashes_by_listing[left], hashes_by_listing[right]) <= max_distance:
                union(left, right)

    groups: dict[str, list[str]] = {}
    for member in ids:
        groups.setdefault(find(member), []).append(member)
    return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)

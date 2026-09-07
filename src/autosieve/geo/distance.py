"""Great-circle distance between two points on Earth."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_KM = 6371.0

# Default origin for the deal meter: Faro, Portugal.
FARO: tuple[float, float] = (37.0194, -7.9322)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in kilometres between two (latitude, longitude) points."""
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(h))

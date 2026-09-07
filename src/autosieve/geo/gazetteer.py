"""Resolve a Portuguese location string to coordinates, offline.

Facebook shows locations as "Town, District" (e.g. "Odivelas, Lisboa"). We match
the town first, then fall back to the district centroid, so any well-formed
location resolves at least coarsely — good enough to weight a deal by distance,
which does not need street precision. The gazetteer is a small packaged file, so
there is no geocoding service, no network, and no rate limit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from autosieve.parsing.normalize import fold

DATA_RESOURCE = "pt_places.json"


@dataclass(frozen=True, slots=True)
class Gazetteer:
    towns: dict[str, tuple[float, float]]
    districts: dict[str, tuple[float, float]]

    def resolve(self, location: str | None) -> tuple[float, float] | None:
        if not location:
            return None
        segments = [fold(s) for s in location.split(",") if s.strip()]
        for segment in segments:  # a named town is more precise than its district
            if segment in self.towns:
                return self.towns[segment]
        for segment in segments:  # fall back to the district centroid
            if segment in self.districts:
                return self.districts[segment]
        return None


def _to_coords(raw: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    return {fold(name): (float(v[0]), float(v[1])) for name, v in raw.items()}


def _load(path_text: str) -> Gazetteer:
    data = json.loads(path_text)
    return Gazetteer(
        towns=_to_coords(data.get("towns", {})),
        districts=_to_coords(data.get("districts", {})),
    )


_DEFAULT: Gazetteer | None = None


def default_gazetteer() -> Gazetteer:
    """The packaged Portugal gazetteer, loaded once."""
    global _DEFAULT
    if _DEFAULT is None:
        text = (resources.files("autosieve.geo.data") / DATA_RESOURCE).read_text(encoding="utf-8")
        _DEFAULT = _load(text)
    return _DEFAULT


def geocode(location: str | None, gazetteer: Gazetteer | None = None) -> tuple[float, float] | None:
    """Coordinates for a location string, or None if nothing matched."""
    return (gazetteer or default_gazetteer()).resolve(location)

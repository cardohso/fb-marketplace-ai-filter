"""Turn a listing's location string into a distance, for weighting deals by how
far a car is from you.
"""

from autosieve.geo.distance import FARO, haversine_km
from autosieve.geo.gazetteer import Gazetteer, default_gazetteer, geocode

__all__ = ["FARO", "Gazetteer", "default_gazetteer", "geocode", "haversine_km"]

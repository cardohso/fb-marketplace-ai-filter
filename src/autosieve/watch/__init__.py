"""Watchlists: saved searches that alert on new matches and price drops."""

from autosieve.watch.config import load_watches, save_watches, watches_path
from autosieve.watch.matcher import MatchResult, watch_matches
from autosieve.watch.models import Watch

__all__ = [
    "MatchResult",
    "Watch",
    "load_watches",
    "save_watches",
    "watch_matches",
    "watches_path",
]

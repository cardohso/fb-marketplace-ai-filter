"""Failure modes the scraper reports instead of crashing the run."""

from __future__ import annotations


class ScrapeError(Exception):
    """Base class for anything that stops one listing or one run from being scraped."""


class LoginWallError(ScrapeError):
    """Facebook redirected to a login page; nothing on this run can be scraped anonymously."""


class ListingUnavailableError(ScrapeError):
    """The listing was removed, sold, or is not visible without logging in."""

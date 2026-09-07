"""The Notifier seam and a console implementation for dry runs."""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class NotifyError(Exception):
    """A notification could not be delivered."""


class Notifier(Protocol):
    def send(self, text: str) -> None:
        """Deliver one message, or raise :class:`NotifyError`."""
        ...


class ConsoleNotifier:
    """Prints alerts instead of sending them. Used for dry runs and when no
    channel is configured.
    """

    def send(self, text: str) -> None:
        print("\n--- ALERT ---\n" + text + "\n-------------")

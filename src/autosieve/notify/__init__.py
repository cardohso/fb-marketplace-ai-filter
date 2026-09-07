"""Send alerts. Telegram today, behind a small Notifier seam for other channels."""

from autosieve.notify.base import ConsoleNotifier, Notifier, NotifyError
from autosieve.notify.format import format_event
from autosieve.notify.telegram import TelegramNotifier

__all__ = [
    "ConsoleNotifier",
    "Notifier",
    "NotifyError",
    "TelegramNotifier",
    "format_event",
]

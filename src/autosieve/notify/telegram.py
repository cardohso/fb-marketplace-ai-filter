"""Send alerts to a Telegram chat via the Bot API.

Create a bot with @BotFather to get a token, then find your chat id (message the
bot and read getUpdates, or use @userinfobot). Put both in .env as
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests

from autosieve.notify.base import NotifyError

log = logging.getLogger(__name__)

API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LEN = 4096


@dataclass
class TelegramNotifier:
    token: str
    chat_id: str
    timeout_s: float = 15.0
    session: requests.Session = field(default_factory=requests.Session)

    def send(self, text: str) -> None:
        if not self.token or not self.chat_id:
            raise NotifyError("Telegram token and chat id are required")
        payload = {
            "chat_id": self.chat_id,
            "text": text[:MAX_MESSAGE_LEN],
            "disable_web_page_preview": False,
        }
        try:
            resp = self.session.post(
                API_TEMPLATE.format(token=self.token), json=payload, timeout=self.timeout_s
            )
        except requests.RequestException as exc:
            raise NotifyError(f"could not reach Telegram: {exc}") from exc
        if resp.status_code != 200:
            raise NotifyError(
                f"Telegram rejected the message ({resp.status_code}): {resp.text[:200]}"
            )
        body = resp.json()
        if not body.get("ok", False):
            raise NotifyError(f"Telegram error: {body.get('description', 'unknown')}")

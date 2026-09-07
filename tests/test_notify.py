from __future__ import annotations

import json

import pytest
import requests
import responses

from autosieve.models import Listing
from autosieve.notify import ConsoleNotifier, NotifyError, TelegramNotifier, format_event
from autosieve.scoring import DealScore, ScoreStatus
from autosieve.watch import Watch
from autosieve.watch.events import AlertEvent, AlertKind

TOKEN = "123:ABC"
CHAT = "42"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

WATCH = Watch(name="clio", make="Renault", model="Clio")


def listing() -> Listing:
    return Listing(
        id="1234567890",
        url="https://www.facebook.com/marketplace/item/1234567890/",
        title="Renault Clio 1.5 dCi",
        price_eur=8000,
        year=2016,
        location="Faro, Portugal",
    )


def scored() -> DealScore:
    return DealScore(
        listing_id="1234567890",
        status=ScoreStatus.SCORED,
        score=1.19,
        benchmark_median=9500,
        confidence=0.8,
        kms=90000,
        reasons=["low mileage: +2%"],
    )


# ── formatting ───────────────────────────────────────────────────────────────


def test_format_new_event_has_the_essentials() -> None:
    event = AlertEvent(
        kind=AlertKind.NEW, watch=WATCH, listing=listing(), price_eur=8000, score=scored()
    )
    text = format_event(event)
    assert "New match [clio]" in text
    assert "8.000 €" in text
    assert "2016" in text
    assert "Faro, Portugal" in text
    assert "deal score 1.19" in text
    assert "market 9.500 €" in text
    assert "90.000 km" in text
    assert "marketplace/item/1234567890" in text


def test_format_price_drop_shows_the_delta() -> None:
    event = AlertEvent(
        kind=AlertKind.PRICE_DROP,
        watch=WATCH,
        listing=listing(),
        price_eur=8000,
        previous_price=9000,
    )
    text = format_event(event)
    assert "Price drop [clio]" in text
    assert "9.000 € → 8.000 €" in text
    assert "-1.000 €" in text


def test_format_without_a_score_still_works() -> None:
    event = AlertEvent(kind=AlertKind.NEW, watch=WATCH, listing=listing(), price_eur=8000)
    text = format_event(event)
    assert "deal score" not in text
    assert "8.000 €" in text


# ── telegram ─────────────────────────────────────────────────────────────────


@responses.activate
def test_telegram_sends_message() -> None:
    responses.add(responses.POST, URL, json={"ok": True, "result": {}})
    TelegramNotifier(token=TOKEN, chat_id=CHAT).send("hello")
    body = json.loads(responses.calls[0].request.body)
    assert body["chat_id"] == CHAT
    assert body["text"] == "hello"


@responses.activate
def test_telegram_raises_on_api_error() -> None:
    responses.add(
        responses.POST, URL, status=400, json={"ok": False, "description": "chat not found"}
    )
    with pytest.raises(NotifyError, match=r"chat not found|400"):
        TelegramNotifier(token=TOKEN, chat_id=CHAT).send("hi")


@responses.activate
def test_telegram_raises_on_transport_error() -> None:
    responses.add(responses.POST, URL, body=requests.ConnectionError("down"))
    with pytest.raises(NotifyError, match="could not reach"):
        TelegramNotifier(token=TOKEN, chat_id=CHAT).send("hi")


def test_telegram_requires_credentials() -> None:
    with pytest.raises(NotifyError, match="required"):
        TelegramNotifier(token="", chat_id="").send("hi")


def test_console_notifier_prints(capsys: pytest.CaptureFixture[str]) -> None:
    ConsoleNotifier().send("a deal")
    assert "a deal" in capsys.readouterr().out

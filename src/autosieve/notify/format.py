"""Render an alert event as a plain-text message (channel-agnostic)."""

from __future__ import annotations

from autosieve.watch.events import AlertEvent, AlertKind


def _eur(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") + " €" if value is not None else "?"


def _km(value: int | None) -> str:
    return f"{value:,}".replace(",", ".") + " km" if value is not None else "km unknown"


def _headline(event: AlertEvent) -> str:
    title = event.listing.title or "vehicle"
    if event.kind is AlertKind.NEW:
        return f"🚗 New match [{event.watch.name}]: {title}"
    drop = f" (-{_eur(event.drop_eur)})" if event.drop_eur else ""
    return (
        f"📉 Price drop [{event.watch.name}]: {title}\n"
        f"{_eur(event.previous_price)} → {_eur(event.price_eur)}{drop}"
    )


def format_event(event: AlertEvent) -> str:
    listing = event.listing
    lines = [_headline(event)]

    if event.kind is AlertKind.NEW:
        lines.append(_eur(event.price_eur))

    location = listing.location
    if event.score is not None and event.score.distance_km is not None:
        location = f"{location or '?'} ({event.score.distance_km:.0f} km away)"
    facts = [f for f in (str(listing.year) if listing.year else None, location) if f]
    if facts:
        lines.append(" · ".join(facts))

    score = event.score
    if score is not None and score.is_scored and score.score is not None:
        deal = f"deal score {score.score:.2f} vs market {_eur(score.benchmark_median)}"
        if score.confidence:
            deal += f" (confidence {score.confidence:.0%})"
        lines.append(deal)
        if score.reasons:
            lines.append("• " + "; ".join(score.reasons))

    kms = score.kms if score is not None else listing.kms
    lines.append(_km(kms))
    lines.append(listing.url)
    return "\n".join(lines)

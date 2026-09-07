"""Turn watch matches into alert events, remembering what was already sent.

Two events fire:

* ``new`` — a listing that is new to the store this run and matches a watch.
* ``price_drop`` — a listing already known to a watch whose price fell by a
  material amount since the watch last saw it.

Pre-existing listings that match a newly added watch are recorded silently as a
baseline, so adding a watch does not flood you with alerts for cars already in
the store; only genuinely new listings and real drops are surfaced.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from autosieve.models import Analysis, Listing
from autosieve.scoring import DealScore
from autosieve.storage import Store
from autosieve.watch.matcher import watch_matches
from autosieve.watch.models import Watch

ScoreOf = Callable[[Listing, Analysis | None], DealScore | None]

DEFAULT_DROP_MIN_EUR = 200
DEFAULT_DROP_MIN_PCT = 0.03


class AlertKind(StrEnum):
    NEW = "new"
    PRICE_DROP = "price_drop"


@dataclass(frozen=True, slots=True)
class AlertEvent:
    kind: AlertKind
    watch: Watch
    listing: Listing
    price_eur: int | None
    previous_price: int | None = None
    score: DealScore | None = None

    @property
    def drop_eur(self) -> int | None:
        if self.previous_price is None or self.price_eur is None:
            return None
        return self.previous_price - self.price_eur


def _is_material_drop(previous: int, current: int) -> bool:
    drop = previous - current
    return drop >= max(DEFAULT_DROP_MIN_EUR, previous * DEFAULT_DROP_MIN_PCT)


def detect_events(
    store: Store,
    watches: Iterable[Watch],
    *,
    new_ids: set[str],
    score_of: ScoreOf | None = None,
    persist: bool = True,
) -> list[AlertEvent]:
    """Find alert events across all watches and update watch state.

    ``new_ids`` are the listing ids added to the store in this run. ``persist``
    False evaluates without writing state, for a dry run.
    """
    events: list[AlertEvent] = []
    active = [w for w in watches if w.enabled]
    if not active:
        return events

    for listing, record in store.iter_listings_with_analysis():
        analysis = record.analysis if record else None
        score = score_of(listing, analysis) if score_of is not None else None
        for watch in active:
            if not watch_matches(watch, listing, analysis, score).matched:
                continue
            state = store.get_watch_state(watch.name, listing.id)
            if state is None:
                is_new = listing.id in new_ids
                if persist:
                    store.upsert_watch_state(
                        watch.name, listing.id, last_price=listing.price_eur, alerted=is_new
                    )
                if is_new:
                    events.append(
                        AlertEvent(
                            kind=AlertKind.NEW,
                            watch=watch,
                            listing=listing,
                            price_eur=listing.price_eur,
                            score=score,
                        )
                    )
                continue

            previous = state.last_price
            current = listing.price_eur
            if (
                previous is not None
                and current is not None
                and _is_material_drop(previous, current)
            ):
                if persist:
                    store.upsert_watch_state(
                        watch.name, listing.id, last_price=current, alerted=True
                    )
                events.append(
                    AlertEvent(
                        kind=AlertKind.PRICE_DROP,
                        watch=watch,
                        listing=listing,
                        price_eur=current,
                        previous_price=previous,
                        score=score,
                    )
                )
            elif persist and current != previous:
                # Track a price rise or immaterial change without alerting.
                store.upsert_watch_state(watch.name, listing.id, last_price=current, alerted=False)

    return events

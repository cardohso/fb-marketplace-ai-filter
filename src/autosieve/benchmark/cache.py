"""Compose benchmark providers: cache expensive lookups, and fall back in order."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from autosieve.benchmark.models import Benchmark
from autosieve.benchmark.provider import BenchmarkProvider
from autosieve.identity import VehicleKey
from autosieve.storage import Store

log = logging.getLogger(__name__)


class CachedBenchmarkProvider:
    """Wrap a provider so each identity is looked up at most once per TTL.

    A miss is cached too (as a null benchmark), so a model the source cannot
    value is not retried on every run until the entry expires.
    """

    def __init__(self, inner: BenchmarkProvider, store: Store, *, ttl_days: float) -> None:
        self._inner = inner
        self._store = store
        self._ttl_days = ttl_days

    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        if year is None:
            return self._inner.lookup(key, None)
        fresh, cached = self._store.get_cached_benchmark(key, year, ttl_days=self._ttl_days)
        if fresh:
            return cached
        result = self._inner.lookup(key, year)
        self._store.put_cached_benchmark(key, year, result)
        return result


class LayeredBenchmarkProvider:
    """Try each provider in order and return the first benchmark found."""

    def __init__(self, providers: Sequence[BenchmarkProvider]) -> None:
        self._providers = list(providers)

    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        for provider in self._providers:
            result = provider.lookup(key, year)
            if result is not None:
                return result
        return None

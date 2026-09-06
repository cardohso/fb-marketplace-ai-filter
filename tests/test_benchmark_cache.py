from __future__ import annotations

import pytest

from autosieve.benchmark import Benchmark, SeedBenchmarkProvider
from autosieve.benchmark.cache import CachedBenchmarkProvider, LayeredBenchmarkProvider
from autosieve.identity import VehicleKey
from autosieve.storage import Store


def bench(median: int = 9500, **overrides: object) -> Benchmark:
    base: dict[str, object] = {
        "make": "Renault",
        "model": "Clio",
        "fuel": "gasoleo",
        "year_from": 2013,
        "year_to": 2019,
        "median_eur": median,
        "sample_size": 50,
    }
    base.update(overrides)
    return Benchmark.model_validate(base)


KEY = VehicleKey(make="renault", model="clio", fuel="gasoleo")


class CountingProvider:
    def __init__(self, result: Benchmark | None) -> None:
        self.result = result
        self.calls = 0

    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        self.calls += 1
        return self.result


@pytest.fixture
def store() -> Store:
    with Store(":memory:") as s:
        yield s


def test_cache_serves_second_lookup_without_calling_inner(store: Store) -> None:
    inner = CountingProvider(bench(median=10_000))
    provider = CachedBenchmarkProvider(inner, store, ttl_days=30)

    first = provider.lookup(KEY, 2016)
    second = provider.lookup(KEY, 2016)

    assert first is not None and first.median_eur == 10_000
    assert second is not None and second.median_eur == 10_000
    assert inner.calls == 1  # the second lookup hit the cache


def test_cache_remembers_a_miss(store: Store) -> None:
    inner = CountingProvider(None)
    provider = CachedBenchmarkProvider(inner, store, ttl_days=30)

    assert provider.lookup(KEY, 2016) is None
    assert provider.lookup(KEY, 2016) is None
    assert inner.calls == 1  # a miss is cached, not retried


def test_cache_expires_after_ttl(store: Store) -> None:
    inner = CountingProvider(bench())
    # A zero-day TTL means every entry is immediately stale.
    provider = CachedBenchmarkProvider(inner, store, ttl_days=0)
    provider.lookup(KEY, 2016)
    provider.lookup(KEY, 2016)
    assert inner.calls == 2


def test_cache_passes_through_unknown_year(store: Store) -> None:
    # With no year the cache cannot key an entry, so it delegates to the inner
    # provider each time without storing anything.
    inner = CountingProvider(bench())
    provider = CachedBenchmarkProvider(inner, store, ttl_days=30)
    assert provider.lookup(KEY, None) is not None
    assert provider.lookup(KEY, None) is not None
    assert inner.calls == 2


def test_layered_returns_first_hit() -> None:
    live = CountingProvider(None)  # live has nothing
    seed = SeedBenchmarkProvider([bench(median=9000)])
    layered = LayeredBenchmarkProvider([live, seed])

    result = layered.lookup(KEY, 2016)
    assert result is not None and result.median_eur == 9000
    assert live.calls == 1  # tried live first, then fell back to seed


def test_layered_prefers_earlier_provider() -> None:
    live = CountingProvider(bench(median=12_000))
    seed = SeedBenchmarkProvider([bench(median=9000)])
    layered = LayeredBenchmarkProvider([live, seed])
    result = layered.lookup(KEY, 2016)
    assert result is not None and result.median_eur == 12_000

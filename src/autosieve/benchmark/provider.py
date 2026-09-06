"""Benchmark providers: the interface, and a seed-file implementation.

The seed file is a curated starting point derived from Standvirtual's Avaliador,
not a live feed. It lets the deal score work today and be tested deterministically.
A live scraper can implement the same :class:`BenchmarkProvider` protocol later
and drop in without changing the scorer.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Protocol

from autosieve.benchmark.models import Benchmark
from autosieve.identity import VehicleKey

SEED_RESOURCE = "seed_benchmarks.json"


class BenchmarkProvider(Protocol):
    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        """The best benchmark for this identity and year, or None if unknown."""
        ...


def _specificity(benchmark: Benchmark, key: VehicleKey) -> tuple[int, int, int]:
    """Rank candidates: exact fuel first, then larger samples, then narrower bands."""
    if key.fuel is not None and benchmark.fuel == key.fuel:
        fuel_rank = 2
    elif benchmark.fuel is None:
        fuel_rank = 1  # a fuel-agnostic benchmark still applies
    else:
        fuel_rank = 0
    return (fuel_rank, benchmark.sample_size, -(benchmark.year_to - benchmark.year_from))


class SeedBenchmarkProvider:
    """Serves benchmarks from an in-memory list, indexed by canonical make and model."""

    def __init__(self, benchmarks: list[Benchmark]) -> None:
        self._by_model: dict[tuple[str, str], list[Benchmark]] = {}
        for benchmark in benchmarks:
            key = benchmark.key
            self._by_model.setdefault((key.make, key.model), []).append(benchmark)

    @property
    def size(self) -> int:
        return sum(len(v) for v in self._by_model.values())

    def lookup(self, key: VehicleKey, year: int | None) -> Benchmark | None:
        candidates = [
            benchmark
            for benchmark in self._by_model.get((key.make, key.model), [])
            if benchmark.covers_year(year)
            # A fuel-specific benchmark for a different fuel does not apply.
            and not (key.fuel is not None and benchmark.fuel not in (None, key.fuel))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda b: _specificity(b, key))

    @classmethod
    def from_records(cls, records: list[dict[str, object]]) -> SeedBenchmarkProvider:
        return cls([Benchmark.model_validate(r) for r in records])

    @classmethod
    def from_file(cls, path: Path) -> SeedBenchmarkProvider:
        records = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_records(records)

    @classmethod
    def default(cls) -> SeedBenchmarkProvider:
        """Load the packaged seed benchmarks."""
        with resources.as_file(resources.files("autosieve.benchmark.data") / SEED_RESOURCE) as path:
            return cls.from_file(path)

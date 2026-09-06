"""Market price benchmarks for vehicle identities.

A :class:`BenchmarkProvider` answers "what does this car normally sell for?".
The deal score depends only on that interface, so the benchmark source can be a
curated seed file today and a live Standvirtual scraper later without touching
the scorer.
"""

from autosieve.benchmark.models import Benchmark
from autosieve.benchmark.provider import BenchmarkProvider, SeedBenchmarkProvider

__all__ = ["Benchmark", "BenchmarkProvider", "SeedBenchmarkProvider"]

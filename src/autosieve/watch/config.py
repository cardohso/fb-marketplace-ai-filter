"""Load and save the watch list. The JSON file is the source of truth; the CLI
adds and removes entries in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from autosieve.watch.models import Watch

DEFAULT_FILENAME = "watches.json"


def watches_path(explicit: Path | None = None) -> Path:
    return explicit if explicit is not None else Path(DEFAULT_FILENAME)


def load_watches(path: Path | None = None) -> list[Watch]:
    """Read the watch list, or an empty list if the file does not exist."""
    target = watches_path(path)
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{target} must contain a JSON array of watches")
    watches = [Watch.model_validate(item) for item in raw]
    names = [w.name for w in watches]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate watch name(s) in {target}: {', '.join(sorted(duplicates))}")
    return watches


def save_watches(watches: list[Watch], path: Path | None = None) -> Path:
    """Write the watch list back, pretty-printed."""
    target = watches_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [w.model_dump(exclude_defaults=True) for w in watches]
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target

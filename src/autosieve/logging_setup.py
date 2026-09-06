"""Console logging for the CLI. Library modules only ever call ``logging.getLogger``."""

from __future__ import annotations

import logging
import sys


def setup_logging(*, verbose: int = 0, quiet: bool = False) -> None:
    level = logging.WARNING if quiet else logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # Third-party chatter is never what the user is looking for.
    for noisy in ("urllib3", "PIL", "easyocr"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

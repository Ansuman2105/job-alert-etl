"""Single-line structured logging.

GitHub Actions shows stdout verbatim, so keep each record on one line and lead
with the stage — that makes a failed run readable from the phone app.
"""

from __future__ import annotations

import logging
import sys


def configure(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # already configured (e.g. second CLI call in one process)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level.upper())

    # These log every connection and request at INFO; far too noisy for a job log.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

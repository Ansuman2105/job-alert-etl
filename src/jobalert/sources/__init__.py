"""Source registry.

Adding a board: write a module exposing NAME, REQUIRES_BOARD, fetch() and
normalise(), then add it here. Nothing else in the pipeline changes.
"""

from __future__ import annotations

from types import ModuleType

from . import arbeitnow, ashby, greenhouse, lever, remoteok

# Sources that need a per-company token from config/companies.yaml
BOARD_SOURCES: dict[str, ModuleType] = {
    greenhouse.NAME: greenhouse,
    ashby.NAME: ashby,
    lever.NAME: lever,
}

# Whole-feed sources, toggled under `feeds:` in config/companies.yaml
FEED_SOURCES: dict[str, ModuleType] = {
    arbeitnow.NAME: arbeitnow,
    remoteok.NAME: remoteok,
}

ALL_SOURCES: dict[str, ModuleType] = {**BOARD_SOURCES, **FEED_SOURCES}


def get(name: str) -> ModuleType:
    try:
        return ALL_SOURCES[name]
    except KeyError:
        raise KeyError(
            f"Unknown source {name!r}. Known: {', '.join(sorted(ALL_SOURCES))}"
        ) from None


__all__ = ["ALL_SOURCES", "BOARD_SOURCES", "FEED_SOURCES", "get"]

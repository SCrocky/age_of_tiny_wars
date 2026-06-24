"""
Central logging configuration.

Import `get_logger(__name__-ish tag)` to obtain a module logger:

    from logging_config import get_logger
    log = get_logger("server")
    log.info("Starting game — %d humans", n)

Levels:
    DEBUG    verbose per-decision detail (every gather/spawn, scene dumps)
    INFO     notable events (game start/over, builds, combat phase changes, connects)
    WARNING  recoverable problems (bad command, disconnect, UDP fallback)
    ERROR    failures

The active level is read from the LOG_LEVEL env var (default INFO). Set
LOG_LEVEL=DEBUG for verbose output or LOG_LEVEL=WARNING to quieten things.
"""

import logging
import os

_LEVEL_NAME = os.environ.get("LOG_LEVEL", "INFO").upper()
_LEVEL      = getattr(logging, _LEVEL_NAME, logging.INFO)

logging.basicConfig(
    level=_LEVEL,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger; the name is shown as [name] in each line."""
    return logging.getLogger(name)

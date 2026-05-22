"""
StandardLogger — infrastructure implementation of ILogger.

Wraps Python's stdlib ``logging`` module so that every other layer only
ever sees the ``ILogger`` interface defined in the domain.

Usage
-----
Call ``configure_logging()`` once at application startup (in ``main.py``).
Obtain a named logger anywhere in infrastructure/application layers via
``get_logger(__name__)`` or inject ``StandardLogger(name)`` through DI.
"""

import logging
import sys
from typing import Final

from fire.domain.interfaces.logger import ILogger

_LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logger for the entire application.

    Must be called exactly once, before any loggers are used.
    Subsequent calls are no-ops thanks to ``force=False`` being the stdlib
    default.  Pass ``level`` as a string (e.g. ``"DEBUG"``, ``"WARNING"``).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        # Already configured — avoid duplicate handlers on hot-reloads.
        root_logger.setLevel(numeric_level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    logging.basicConfig(
        level=numeric_level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        handlers=[handler],
    )


def get_logger(name: str) -> "StandardLogger":
    """Return a ``StandardLogger`` bound to *name* (typically ``__name__``)."""
    return StandardLogger(name)


class StandardLogger(ILogger):
    """
    Concrete ``ILogger`` backed by a stdlib ``logging.Logger``.

    Instantiate via :func:`get_logger` rather than directly so that the
    name is always a fully-qualified module name.
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    # ------------------------------------------------------------------
    # ILogger implementation
    # ------------------------------------------------------------------

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.exception(msg, *args, **kwargs)

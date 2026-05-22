"""
ILogger — abstract logger interface (domain layer).

Placing the interface here keeps the application and domain layers free
from any concrete logging framework.  Infrastructure provides the
implementation; use-cases and domain services depend only on this contract.
"""

from abc import ABC, abstractmethod


class ILogger(ABC):
    """Minimal structured logging contract."""

    @abstractmethod
    def debug(self, msg: str, *args: object, **kwargs: object) -> None: ...

    @abstractmethod
    def info(self, msg: str, *args: object, **kwargs: object) -> None: ...

    @abstractmethod
    def warning(self, msg: str, *args: object, **kwargs: object) -> None: ...

    @abstractmethod
    def error(self, msg: str, *args: object, **kwargs: object) -> None: ...

    @abstractmethod
    def exception(self, msg: str, *args: object, **kwargs: object) -> None:
        """Log an error message together with the current exception traceback."""
        ...

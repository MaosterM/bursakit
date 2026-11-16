"""Every exception bursakit raises on purpose."""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "BursakitError",
    "RateLimited",
    "SchemaError",
    "SourceUnavailable",
    "TickerNotFound",
]


class BursakitError(Exception):
    """Base class for bursakit errors."""


class TickerNotFound(BursakitError, LookupError):
    """No Bursa listing matches what the caller asked for."""

    def __init__(self, ticker: object, suggestions: Sequence[str] = ()) -> None:
        self.ticker = str(ticker)
        self.suggestions = tuple(suggestions)
        message = f"no Bursa listing matches {self.ticker!r}"
        if self.suggestions:
            message += f"; did you mean {', '.join(self.suggestions)}?"
        super().__init__(message)


class SourceUnavailable(BursakitError):
    """A source, or every source for a data type, could not answer."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        retryable: bool = False,
        causes: Sequence[BaseException] = (),
    ) -> None:
        super().__init__(message)
        self.source = source
        self.retryable = retryable
        self.causes = tuple(causes)


class RateLimited(SourceUnavailable):
    """A source asked us to slow down."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        retry_after: float | None = None,
        causes: Sequence[BaseException] = (),
    ) -> None:
        super().__init__(message, source=source, retryable=True, causes=causes)
        self.retry_after = retry_after


class SchemaError(BursakitError):
    """A DataFrame does not match the schema for its data type."""


class NotSupported(BursakitError):
    """Internal: a source adapter does not provide this data type."""

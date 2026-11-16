"""The only module that imports yfinance.

It turns yfinance calls into plain DataFrames, lists and dicts, and yfinance's
exceptions into bursakit's. Everything above it (the Yahoo adapter) is tested
offline against recorded copies of what these functions return.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ..errors import RateLimited, SourceUnavailable, TickerNotFound


@contextmanager
def _raising() -> Iterator[dict[str, Any]]:
    """Make yfinance raise instead of logging and returning an empty frame."""
    import yfinance as yf

    debug = getattr(getattr(yf, "config", None), "debug", None)
    if debug is None or not hasattr(debug, "hide_exceptions"):
        yield {"raise_errors": True}  # older yfinance
        return
    previous = debug.hide_exceptions
    debug.hide_exceptions = False
    try:
        yield {}
    finally:
        debug.hide_exceptions = previous


def _translate(symbol: str, exc: Exception) -> Exception:
    from yfinance import exceptions as yfe

    if isinstance(exc, yfe.YFRateLimitError):
        return RateLimited("yahoo: rate limited", source="yahoo", causes=[exc])
    if isinstance(exc, yfe.YFTickerMissingError):
        return TickerNotFound(symbol)
    return SourceUnavailable(
        f"yahoo: {type(exc).__name__}: {exc}", source="yahoo", retryable=True, causes=[exc]
    )


class LiveYF:
    """Calls Yahoo Finance through yfinance."""

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        """Daily bars with ``Dividends``. ``end`` is inclusive; ``None`` means all history."""
        import yfinance as yf
        from yfinance import exceptions as yfe

        span: dict[str, Any]
        if start is None or end is None:
            span = {"period": "max"}
        else:
            span = {"start": start.isoformat(), "end": (end + timedelta(days=1)).isoformat()}
        with _raising() as extra:
            try:
                frame = yf.Ticker(symbol).history(
                    interval="1d", auto_adjust=False, actions=True, **span, **extra
                )
            except yfe.YFPricesMissingError:
                return pd.DataFrame()  # a real ticker with no bars in the range
            except (TickerNotFound, SourceUnavailable):
                raise
            except Exception as exc:
                raise _translate(symbol, exc) from exc
        return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    def search(self, query: str) -> list[dict[str, Any]]:
        import yfinance as yf

        try:
            quotes = yf.Search(query, max_results=10, news_count=0).quotes
        except Exception as exc:
            raise _translate(query, exc) from exc
        return [dict(quote) for quote in quotes or []]

    def screen(self, sector: str | None, offset: int, size: int) -> dict[str, Any]:
        import yfinance as yf
        from yfinance import EquityQuery

        query = EquityQuery("eq", ["exchange", "KLS"])
        if sector is not None:
            query = EquityQuery("and", [query, EquityQuery("eq", ["sector", sector])])
        try:
            result = yf.screen(query, size=size, offset=offset, sortField="ticker", sortAsc=True)
        except Exception as exc:
            raise _translate("KLS screen", exc) from exc
        if not isinstance(result, dict):
            raise SourceUnavailable("yahoo: screener returned no result", source="yahoo")
        return result

"""bursakit: Bursa Malaysia stock data and Malaysian macro series as DataFrames.

Every public function follows the same path: check the cache; on a miss ask
the router, which tries each source in order; validate the answer against the
schema; store it; return it.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from . import _util, cache, macro, router
from ._util import DateLike
from .errors import BursakitError, RateLimited, SchemaError, SourceUnavailable, TickerNotFound
from .tickers import Ticker, resolve

__version__ = "0.1.0"

__all__ = [
    "BursakitError",
    "RateLimited",
    "SchemaError",
    "SourceUnavailable",
    "Ticker",
    "TickerNotFound",
    "__version__",
    "cache",
    "dividends",
    "listings",
    "macro",
    "prices",
    "resolve",
]


def prices(
    ticker: str | int | Ticker,
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    """Daily open, high, low, close and volume for a Bursa-listed stock.

    ``ticker`` may be a stock code (``1155``), a ``.KL`` symbol or a stock name
    (``"MAYBANK"``). ``start`` and ``end`` are inclusive; the default is the
    last 365 days. Prices are in MYR, adjusted for splits and bonus issues.
    """
    resolved = resolve(ticker)
    first, last = _util.span(start, end, default=timedelta(days=365))
    df, source = cache.series(
        "prices",
        resolved.code,
        first,
        last,
        lambda s, e: router.fetch("prices", resolved, s, e),
        verify="close",
        overlap=7,
        refresh=refresh,
    )
    return _util.tag(df, "prices", source, ticker=resolved.code)


def dividends(ticker: str | int | Ticker, *, refresh: bool = False) -> pd.DataFrame:
    """Dividend history: MYR per share, indexed by ex-date."""
    resolved = resolve(ticker)
    df, source = cache.frame(
        "dividends", resolved.code, lambda: router.fetch("dividends", resolved), refresh=refresh
    )
    return _util.tag(df, "dividends", source, ticker=resolved.code)


def listings(*, refresh: bool = False) -> pd.DataFrame:
    """Companies listed on Bursa Malaysia: stock code, name, company, sector, market."""
    df, source = cache.frame("listings", "all", lambda: router.fetch("listings"), refresh=refresh)
    return _util.tag(df, "listings", source)

"""Yahoo Finance adapter (``.KL`` tickers): prices, dividends, listings, name lookup.

Unofficial access through yfinance. Prices and dividends are adjusted for
splits and bonus issues by Yahoo, not for dividends (``auto_adjust=False``).
"""

from __future__ import annotations

import logging
from datetime import date
from functools import partial
from typing import Any, ClassVar, Protocol

import pandas as pd

from .. import policy
from ..errors import SourceUnavailable, TickerNotFound
from ..schema import DIVIDENDS, LISTINGS, PRICES
from ..tickers import Ticker
from .base import Source

__all__ = ["SECTORS", "YFClient", "Yahoo"]

#: Yahoo's sector names. The screener has no sector field in its results, so
#: listings are gathered one sector at a time.
SECTORS = (
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial Services",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
)

_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}

_log = logging.getLogger(__name__)


class YFClient(Protocol):
    """What the adapter needs from Yahoo. ``_yf.LiveYF`` is the real one."""

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame: ...
    def search(self, query: str) -> list[dict[str, Any]]: ...
    def screen(self, sector: str | None, offset: int, size: int) -> dict[str, Any]: ...


class Yahoo(Source):
    name: ClassVar[str] = "yahoo"
    attribution: ClassVar[str] = "Yahoo Finance"
    # Personal, non-commercial use only. See docs/source-terms.md.
    terms: ClassVar[str] = "https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html"

    def __init__(self, client: YFClient | None = None, *, page_size: int = 250) -> None:
        self._given = client
        self._page_size = page_size

    @property
    def _client(self) -> YFClient:
        if self._given is None:
            from ._yf import LiveYF  # imports yfinance only when first used

            self._given = LiveYF()
        return self._given

    def _history(self, ticker: Ticker, start: date | None, end: date | None) -> pd.DataFrame:
        try:
            raw = policy.call(self.name, partial(self._client.history, ticker.symbol, start, end))
        except TickerNotFound:
            raise TickerNotFound(ticker.code) from None
        if raw.empty:
            return raw
        missing = [column for column in (*_RENAME, "Dividends") if column not in raw.columns]
        if missing:
            raise SourceUnavailable(
                f"yahoo: history for {ticker.symbol} lacks columns {missing}", source=self.name
            )
        index = pd.DatetimeIndex(raw.index)
        if index.tz is not None:  # exchange-local midnight -> plain calendar date
            index = index.tz_localize(None)
        out = raw.set_axis(index.normalize(), axis="index")
        return out[~out.index.duplicated(keep="last")]

    def prices(self, ticker: Ticker, start: date, end: date) -> pd.DataFrame:
        raw = self._history(ticker, start, end)
        if raw.empty:
            return pd.DataFrame(columns=PRICES.column_names, index=pd.DatetimeIndex([]))
        bars = raw.rename(columns=_RENAME)[PRICES.column_names]
        bars = bars.loc[(bars.index >= pd.Timestamp(start)) & (bars.index <= pd.Timestamp(end))]
        bars = bars.dropna(subset=["open", "high", "low", "close"], how="all")  # no trading
        bars = self._complete(bars, ticker)
        # Yahoo serves 32-bit floats (8.670000076...); Bursa ticks are 0.005 at the finest.
        bars[["open", "high", "low", "close"]] = bars[["open", "high", "low", "close"]].round(4)
        return bars

    def _complete(self, bars: pd.DataFrame, ticker: Ticker) -> pd.DataFrame:
        """Drop days with a missing price or volume, so one bad row costs one row.

        Without this the schema check would reject the whole range. Each dropped
        day is logged, because it leaves a gap that only ``refresh=True`` refills.
        """
        partial_days = bars.isna().any(axis=1)
        if not partial_days.any():
            return bars.copy()
        dropped = [day.strftime("%Y-%m-%d") for day in bars.index[partial_days]]
        shown = ", ".join(dropped[:5]) + (", ..." if len(dropped) > 5 else "")
        _log.warning(
            "yahoo: dropped %d incomplete row(s) for %s: %s", len(dropped), ticker.symbol, shown
        )
        return bars.loc[~partial_days].copy()

    def dividends(self, ticker: Ticker) -> pd.DataFrame:
        raw = self._history(ticker, None, None)
        if raw.empty:
            return pd.DataFrame(columns=DIVIDENDS.column_names, index=pd.DatetimeIndex([]))
        paid = raw.loc[raw["Dividends"] > 0, ["Dividends"]]
        return paid.rename(columns={"Dividends": "amount"}).round(6)

    def lookup(self, name: str) -> Ticker:
        wanted = name.strip().upper()
        quotes = policy.call(self.name, partial(self._client.search, wanted))
        bursa = [q for q in quotes if str(q.get("symbol", "")).endswith(".KL")]
        for quote in bursa:
            short = str(quote.get("shortname") or "").strip().upper()
            if short == wanted:
                return Ticker(str(quote["symbol"])[:-3], short)
        suggestions = [str(q.get("shortname")) for q in bursa if q.get("shortname")]
        raise TickerNotFound(name, suggestions[:5])

    def listings(self) -> pd.DataFrame:
        rows: dict[str, dict[str, Any]] = {}
        for sector in (*SECTORS, None):  # the last pass picks up unclassified listings
            for quote in self._screen_all(sector):
                symbol = str(quote.get("symbol") or "")
                if not symbol.endswith(".KL") or symbol[:-3] in rows:
                    continue
                code = symbol[:-3]
                rows[code] = {
                    "name": quote.get("shortName") or code,
                    "company": quote.get("longName"),
                    "sector": sector,
                    "market": None,  # Yahoo does not say Main / ACE / LEAP
                }
        if not rows:
            raise SourceUnavailable("yahoo: screener returned no Bursa listings", source=self.name)
        frame = pd.DataFrame.from_dict(rows, orient="index", columns=LISTINGS.column_names)
        frame.index.name = LISTINGS.index
        return frame

    def _screen_all(self, sector: str | None) -> list[dict[str, Any]]:
        quotes: list[dict[str, Any]] = []
        while True:
            page = policy.call(
                self.name, partial(self._client.screen, sector, len(quotes), self._page_size)
            )
            got = list(page.get("quotes") or [])
            quotes.extend(got)
            if not got or len(quotes) >= int(page.get("total") or 0):
                return quotes

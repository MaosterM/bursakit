"""The interface every source adapter implements.

An adapter overrides only the data types it can serve. Each method returns a
DataFrame already shaped like the schema for that data type (same column
names, naive calendar dates, MYR); the router validates it. Date ranges are
inclusive at both ends. "No rows in that range" is an empty frame, not an error.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pandas as pd

from ..errors import NotSupported
from ..tickers import Ticker

__all__ = ["KINDS", "Source"]

#: Data types a source may serve. "lookup" resolves a stock name to a Ticker.
KINDS = ("prices", "dividends", "listings", "lookup", "opr", "fx")


class Source:
    #: Short identifier used in routes, the policy table and ``df.attrs["source"]``.
    name: ClassVar[str] = ""
    #: Credit line carried in ``df.attrs["attribution"]``.
    attribution: ClassVar[str] = ""
    #: Link to the terms the data is used under, carried in ``df.attrs["terms"]``.
    terms: ClassVar[str] = ""

    def prices(self, ticker: Ticker, start: date, end: date) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not provide prices")

    def dividends(self, ticker: Ticker) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not provide dividends")

    def listings(self) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not provide listings")

    def lookup(self, name: str) -> Ticker:
        raise NotSupported(f"{self.name} does not provide name lookup")

    def opr(self, start: date, end: date) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not provide the OPR")

    def fx(self, currency: str, start: date, end: date) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not provide exchange rates")

    def supports(self, kind: str) -> bool:
        """True if this adapter overrides the method for ``kind``."""
        return getattr(type(self), kind) is not getattr(Source, kind)

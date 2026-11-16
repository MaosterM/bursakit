"""Malaysian macro series: the Overnight Policy Rate and exchange rates."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from . import _util, cache, router
from ._util import DateLike

__all__ = ["CURRENCIES", "fx", "opr"]

#: Currencies Bank Negara Malaysia publishes a ringgit rate for.
CURRENCIES = frozenset(
    {
        "AED", "AUD", "BND", "CAD", "CHF", "CNY", "EGP", "EUR", "GBP",
        "HKD", "IDR", "INR", "JPY", "KHR", "KRW", "MMK", "NPR", "NZD",
        "PHP", "PKR", "SAR", "SGD", "THB", "TWD", "USD", "VND", "XDR",
    }
)  # fmt: skip


def opr(
    start: DateLike | None = None, end: DateLike | None = None, *, refresh: bool = False
) -> pd.DataFrame:
    """Overnight Policy Rate decisions: ``rate`` and ``change`` in percent.

    One row per Monetary Policy Committee decision. The default range is the
    last five years; the series starts in 2004.
    """
    first, last = _util.span(start, end, default=timedelta(days=5 * 365))
    df, source = cache.series(
        "opr", "opr", first, last, lambda s, e: router.fetch("opr", s, e), refresh=refresh
    )
    return _util.tag(df, "opr", source)


def fx(
    currency: str,
    start: DateLike | None = None,
    end: DateLike | None = None,
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    """Ringgit exchange rates: ``buy``, ``sell`` and ``mid`` in MYR per 1 unit.

    Bank Negara Malaysia's 17:00 rates. The default range is the last 365 days.
    """
    code = currency.strip().upper()
    if code not in CURRENCIES:
        raise ValueError(
            f"unknown currency {currency!r}; choose one of {', '.join(sorted(CURRENCIES))}"
        )
    first, last = _util.span(start, end, default=timedelta(days=365))
    df, source = cache.series(
        "fx", code, first, last, lambda s, e: router.fetch("fx", code, s, e), refresh=refresh
    )
    return _util.tag(df, "fx", source, pair=f"{code}MYR")

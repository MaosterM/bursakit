"""Bank Negara Malaysia Open API adapter: OPR and exchange rates.

Endpoints confirmed in the week 1 spike (see docs/spike-go-no-go.md):

* ``/opr/year/{year}``: one request per year, 2004 onward, may repeat rows.
* ``/exchange-rate/{ccy}/year/{y}/month/{m}``: one request per month. Some
  currencies are quoted per 100 units and may have a null middle rate.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import pandas as pd

from .. import policy
from ..errors import SourceUnavailable
from ..schema import FX, OPR
from .base import Source

__all__ = ["BNM"]

BASE = "https://api.bnm.gov.my/public"
HEADERS = {"Accept": "application/vnd.BNM.API.v1+json"}
#: The 17:00 session is BNM's end-of-day reference and matches data.gov.my.
FX_PARAMS = {"session": "1700", "quote": "rm"}
OPR_FIRST_YEAR = 2004


class BNM(Source):
    name: ClassVar[str] = "bnm"
    attribution: ClassVar[str] = "Bank Negara Malaysia"

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """The ``data`` member of a response, or ``None`` on "No records found"."""
        try:
            body = policy.get_json(self.name, f"{BASE}{path}", params=params, headers=HEADERS)
        except policy.HTTPNotFound:
            return None
        if not isinstance(body, dict) or "data" not in body:
            raise SourceUnavailable(f"bnm: no 'data' in response for {path}", source=self.name)
        return body["data"]

    def opr(self, start: date, end: date) -> pd.DataFrame:
        records: dict[str, dict[str, Any]] = {}
        for year in range(max(start.year, OPR_FIRST_YEAR), end.year + 1):
            data = self._get(f"/opr/year/{year}") or []
            for item in [data] if isinstance(data, dict) else data:
                try:
                    records[str(item["date"])] = {
                        "rate": item["new_opr_level"],
                        "change": item["change_in_opr"],
                    }
                except (KeyError, TypeError) as exc:
                    raise SourceUnavailable(
                        f"bnm: unexpected OPR record {item!r}", source=self.name
                    ) from exc
        return _dated(records, OPR.column_names, start, end)

    def fx(self, currency: str, start: date, end: date) -> pd.DataFrame:
        code = currency.upper()
        records: dict[str, dict[str, Any]] = {}
        for year, month in _months(start, end):
            data = self._get(f"/exchange-rate/{code}/year/{year}/month/{month}", FX_PARAMS)
            if data is None:
                continue
            try:
                unit = float(data["unit"])
                rates = data["rate"]
                for item in [rates] if isinstance(rates, dict) else rates:
                    buy, sell, mid = item["buying_rate"], item["selling_rate"], item["middle_rate"]
                    if mid is None and buy is not None and sell is not None:
                        mid = (buy + sell) / 2
                    if mid is None:
                        continue
                    records[str(item["date"])] = {
                        "buy": None if buy is None else buy / unit,
                        "sell": None if sell is None else sell / unit,
                        "mid": mid / unit,
                    }
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                raise SourceUnavailable(
                    f"bnm: unexpected exchange-rate response for {code}", source=self.name
                ) from exc
        return _dated(records, FX.column_names, start, end)


def _months(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _dated(
    records: dict[str, dict[str, Any]], columns: list[str], start: date, end: date
) -> pd.DataFrame:
    """Records keyed by ISO date -> a date-indexed frame clipped to ``start..end``."""
    kept = {day: row for day, row in records.items() if start.isoformat() <= day <= end.isoformat()}
    frame = pd.DataFrame.from_dict(kept, orient="index", columns=columns)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    return frame.sort_index()

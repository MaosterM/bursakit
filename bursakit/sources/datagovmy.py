"""data.gov.my Open API adapter: exchange rates.

Dataset ``exchangerates_daily_1700`` carries BNM's 17:00 buying, middle and
selling rates per 1 unit of each currency, 2003 onward, in a single request.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pandas as pd

from .. import policy
from ..errors import SourceUnavailable
from ..schema import FX
from .base import Source

__all__ = ["DataGovMy"]

URL = "https://api.data.gov.my/data-catalogue/"
FX_DATASET = "exchangerates_daily_1700"
_RATE_TYPES = {"buying": "buy", "selling": "sell", "middle": "mid"}


class DataGovMy(Source):
    name: ClassVar[str] = "datagovmy"
    # The dataset is BNM's rates republished under CC BY 4.0; credit both.
    attribution: ClassVar[str] = "Source: Bank Negara Malaysia, via data.gov.my (CC BY 4.0)"
    terms: ClassVar[str] = "https://creativecommons.org/licenses/by/4.0/"

    def fx(self, currency: str, start: date, end: date) -> pd.DataFrame:
        column = currency.lower()
        params = {
            "id": FX_DATASET,
            "date_start": f"{start.isoformat()}@date",
            "date_end": f"{end.isoformat()}@date",
            "include": f"date,rate_type,{column}",
        }
        try:
            rows = policy.get_json(self.name, URL, params=params)
        except policy.HTTPNotFound as exc:
            raise SourceUnavailable(
                f"datagovmy: dataset {FX_DATASET} not found", source=self.name
            ) from exc
        if not isinstance(rows, list):
            raise SourceUnavailable("datagovmy: expected a list of records", source=self.name)
        if not rows:
            return pd.DataFrame(columns=FX.column_names, index=pd.DatetimeIndex([]))

        long = pd.DataFrame.from_records(rows)
        missing = [name for name in ("date", "rate_type", column) if name not in long.columns]
        if missing:
            raise SourceUnavailable(
                f"datagovmy: {FX_DATASET} lacks fields {missing}", source=self.name
            )
        wide = long.pivot_table(index="date", columns="rate_type", values=column, aggfunc="last")
        wide = wide.rename(columns=_RATE_TYPES).reindex(columns=FX.column_names)
        wide["mid"] = wide["mid"].fillna((wide["buy"] + wide["sell"]) / 2)
        wide = wide.dropna(subset=["mid"])
        wide.index = pd.DatetimeIndex(pd.to_datetime(wide.index))
        wide.columns.name = None
        return wide.sort_index()

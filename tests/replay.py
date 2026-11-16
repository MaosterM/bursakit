"""Replay recorded source responses so the test suite never touches the network."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from bursakit.errors import TickerNotFound
from bursakit.policy import Response

FIXTURES = Path(__file__).parent / "fixtures"


def request_key(url: str, params: Mapping[str, str]) -> str:
    query = "&".join(f"{name}={params[name]}" for name in sorted(params))
    return f"{url}?{query}" if query else url


class FixtureTransport:
    """Stands in for ``policy.transport``: serves responses from ``fixtures/http``."""

    def __init__(self) -> None:
        self.index: dict[str, str] = json.loads(
            (FIXTURES / "http" / "index.json").read_text("utf-8")
        )
        self.calls: list[str] = []
        #: Per-URL overrides, e.g. to simulate an outage: ``{key: Response(503, "")}``.
        self.overrides: dict[str, Response] = {}
        #: If set, every request to a host containing this text fails with it.
        self.fail_host: tuple[str, Response] | None = None

    def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> Response:
        key = request_key(url, params)
        self.calls.append(key)
        if self.fail_host and self.fail_host[0] in url:
            return self.fail_host[1]
        if key in self.overrides:
            return self.overrides[key]
        if key not in self.index:
            raise AssertionError(f"request was never recorded: {key}")
        saved = json.loads((FIXTURES / "http" / self.index[key]).read_text("utf-8"))
        return Response(saved["status"], saved["body"], saved.get("headers", {}))


class RecordedYF:
    """Stands in for ``_yf.LiveYF``: serves what yfinance returned when recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        #: Multiply recorded prices, to simulate Yahoo restating history after a split.
        self.price_factor = 1.0

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        self.calls.append(("history", symbol, start, end))
        file = FIXTURES / "yahoo" / f"history_{symbol}.json"
        if not file.exists():
            raise TickerNotFound(symbol)
        frame = pd.DataFrame.from_records(json.loads(file.read_text("utf-8")))
        stamps = pd.to_datetime(frame.pop("Date"), utc=True).dt.tz_convert("Asia/Kuala_Lumpur")
        frame.index = pd.DatetimeIndex(stamps, name="Date")
        frame[["Open", "High", "Low", "Close", "Adj Close"]] *= self.price_factor
        if start is not None and end is not None:
            days = frame.index.tz_localize(None).normalize()
            frame = frame[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
        return frame

    def search(self, query: str) -> list[dict[str, Any]]:
        self.calls.append(("search", query))
        file = FIXTURES / "yahoo" / f"search_{query}.json"
        if not file.exists():
            raise AssertionError(f"search was never recorded: {query}")
        return list(json.loads(file.read_text("utf-8")))

    def screen(self, sector: str | None, offset: int, size: int) -> dict[str, Any]:
        self.calls.append(("screen", sector, offset, size))
        recorded = json.loads((FIXTURES / "yahoo" / "screen.json").read_text("utf-8"))
        quotes = recorded[sector or "_all"]
        return {"total": len(quotes), "quotes": quotes[offset : offset + size]}

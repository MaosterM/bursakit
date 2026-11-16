"""Re-record the fixtures in tests/fixtures from the live sources.

    python tests/record_fixtures.py

Needs network access. The tests themselves never do. Responses are stored as
received, with two reductions to keep the repository small: Yahoo screener
quotes keep only the fields the adapter reads, and each screener list is cut
to the first rows (see SCREEN_ROWS).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bursakit import policy
from bursakit.sources import BNM, DataGovMy
from bursakit.sources._yf import LiveYF
from bursakit.sources.yahoo import SECTORS
from tests.replay import FIXTURES, request_key

SCREEN_ROWS = 30
SCREEN_FIELDS = ("symbol", "shortName", "longName", "exchange", "quoteType")
SEARCHES = ("MAYBANK", "TENAGA", "PUBLIC", "NOTAREALCO")
HISTORY = {"1155.KL": (date(2023, 1, 1), date(2024, 12, 31))}


def record_http() -> None:
    folder = FIXTURES / "http"
    folder.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    live = policy.transport

    def recording(
        url: str, params: Mapping[str, str], headers: Mapping[str, str], timeout: float
    ) -> policy.Response:
        reply = live(url, params, headers, timeout)
        key = request_key(url, params)
        slug = re.sub(r"[^A-Za-z0-9]+", "_", key.split("://", 1)[1]).strip("_")[:120]
        (folder / f"{slug}.json").write_text(
            json.dumps({"status": reply.status, "body": reply.body}, indent=1), "utf-8"
        )
        index[key] = f"{slug}.json"
        print("recorded", key)
        return reply

    policy.transport = recording
    try:
        BNM().opr(date(2023, 1, 1), date(2024, 12, 31))
        BNM().fx("USD", date(2024, 1, 1), date(2024, 2, 29))
        BNM().fx("JPY", date(2024, 1, 1), date(2024, 1, 31))
        DataGovMy().fx("USD", date(2024, 1, 1), date(2024, 2, 29))
        DataGovMy().fx("JPY", date(2024, 1, 1), date(2024, 1, 31))
    finally:
        policy.transport = live
    (folder / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True), "utf-8")


def record_yahoo() -> None:
    folder = FIXTURES / "yahoo"
    folder.mkdir(parents=True, exist_ok=True)
    yf = LiveYF()

    for symbol, (start, end) in HISTORY.items():
        frame = policy.call("yahoo", lambda s=symbol, a=start, b=end: yf.history(s, a, b))
        frame = frame.reset_index()
        frame["Date"] = frame["Date"].map(lambda stamp: stamp.isoformat())
        (folder / f"history_{symbol}.json").write_text(
            json.dumps(frame.to_dict("records"), indent=None), "utf-8"
        )
        print("recorded history", symbol, len(frame))

    for query in SEARCHES:
        quotes = policy.call("yahoo", lambda q=query: yf.search(q))
        (folder / f"search_{query}.json").write_text(json.dumps(quotes, indent=1), "utf-8")
        print("recorded search", query, len(quotes))

    screens: dict[str, list[dict[str, object]]] = {}
    for sector in (*SECTORS, None):
        page = policy.call("yahoo", lambda s=sector: yf.screen(s, 0, SCREEN_ROWS))
        screens[sector or "_all"] = [
            {name: quote.get(name) for name in SCREEN_FIELDS} for quote in page["quotes"]
        ]
        print("recorded screen", sector, len(page["quotes"]), "of", page.get("total"))
    (folder / "screen.json").write_text(json.dumps(screens, indent=1), "utf-8")


if __name__ == "__main__":
    record_http()
    record_yahoo()

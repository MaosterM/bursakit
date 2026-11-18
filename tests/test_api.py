from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import bursakit as bk
from bursakit import _util
from bursakit.errors import SourceUnavailable, TickerNotFound
from bursakit.policy import Response
from tests.conftest import TODAY, Offline


def test_prices_by_code_symbol_and_name_are_identical(offline: Offline) -> None:
    by_code = bk.prices(1155, "2024-01-01", "2024-03-31")
    by_symbol = bk.prices("1155.KL", "2024-01-01", "2024-03-31")
    by_name = bk.prices("MAYBANK", "2024-01-01", "2024-03-31")

    pd.testing.assert_frame_equal(by_code, by_symbol)
    pd.testing.assert_frame_equal(by_code, by_name)
    assert [call[0] for call in offline.yf.calls] == ["history", "search"]  # one fetch, one lookup
    assert by_name.attrs == {
        "kind": "prices",
        "ticker": "1155",
        "currency": "MYR",
        "source": "yahoo",
        "attribution": "Yahoo Finance",
        "terms": "https://legal.yahoo.com/xw/en/yahoo/terms/otos/index.html",
    }


def test_prices_schema(offline: Offline) -> None:
    df = bk.prices("1155", date(2024, 1, 1), pd.Timestamp("2024-03-31"))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date" and str(df.index.dtype) == "datetime64[ns]"
    assert df.loc["2024-01-02", "close"] == 8.92
    assert len(df) == 60


def test_a_repeat_call_needs_no_source_at_all(offline: Offline) -> None:
    first = bk.prices("1155", "2024-01-01", "2024-03-31")
    offline.yf.calls.clear()
    again = bk.prices("1155", "2024-01-01", "2024-03-31")
    assert offline.yf.calls == []
    pd.testing.assert_frame_equal(first, again)
    assert again.attrs["source"] == "yahoo"


def test_default_range_is_the_last_year(offline: Offline) -> None:
    df = bk.prices("1155")
    assert offline.yf.calls == [("history", "1155.KL", TODAY - timedelta(days=365), TODAY)]
    assert df.index.min() >= pd.Timestamp(TODAY - timedelta(days=365))


def test_bad_arguments() -> None:
    with pytest.raises(ValueError, match="after end"):
        bk.prices("1155", "2024-03-01", "2024-01-01")
    with pytest.raises(ValueError, match="not a date"):
        bk.prices("1155", "last tuesday")
    with pytest.raises(TypeError):
        bk.prices("1155", 20240101)  # type: ignore[arg-type]
    with pytest.raises(TickerNotFound):
        bk.prices("NOTAREALCO")
    with pytest.raises(TickerNotFound):
        bk.prices("9999", "2024-01-01", "2024-01-31")


def test_dates_accept_common_spellings() -> None:
    assert _util.to_date("2024-01-02") == _util.to_date("2 Jan 2024") == date(2024, 1, 2)
    assert _util.to_date(pd.Timestamp("2024-01-02 15:30")) == date(2024, 1, 2)


def test_a_split_restates_the_cached_history(
    offline: Offline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_util, "today", lambda: date(2024, 6, 3))
    before = bk.prices("1155", "2024-01-01", "2024-06-03")

    offline.yf.price_factor = 0.5
    monkeypatch.setattr(_util, "today", lambda: date(2024, 7, 1))
    after = bk.prices("1155", "2024-01-01", "2024-07-01")

    assert after.loc["2024-01-02", "close"] == pytest.approx(before.loc["2024-01-02", "close"] / 2)
    assert len(after) > len(before)


def test_bad_data_from_the_source_is_not_cached(offline: Offline) -> None:
    offline.yf.price_factor = 0.0  # every price becomes zero: fails the schema check
    with pytest.raises(SourceUnavailable, match="non-positive prices"):
        bk.prices("1155", "2024-01-01", "2024-03-31")
    assert bk.cache.info()["series"] == {}

    offline.yf.price_factor = 1.0
    assert len(bk.prices("1155", "2024-01-01", "2024-03-31")) == 60


def test_one_incomplete_row_does_not_fail_the_range(
    offline: Offline, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = offline.yf.history

    def with_a_hole(symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        frame = recorded(symbol, start, end).astype({"Volume": "float64"})
        frame.iloc[5, frame.columns.get_loc("Volume")] = float("nan")
        return frame

    monkeypatch.setattr(offline.yf, "history", with_a_hole)
    assert len(bk.prices("1155", "2024-01-01", "2024-03-31")) == 59  # 60 trading days, one lost


def test_a_failed_refresh_keeps_the_cached_prices(
    offline: Offline, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = bk.prices("1155", "2024-01-01", "2024-03-31")

    def down(symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        raise SourceUnavailable("yahoo: down", source="yahoo")

    monkeypatch.setattr(offline.yf, "history", down)
    with pytest.raises(SourceUnavailable):
        bk.prices("1155", "2024-01-01", "2024-03-31", refresh=True)

    pd.testing.assert_frame_equal(bk.prices("1155", "2024-01-01", "2024-03-31"), before)


def test_dividends(offline: Offline) -> None:
    df = bk.dividends("MAYBANK")
    again = bk.dividends(1155)

    assert df["amount"].tolist() == [0.30, 0.29, 0.31, 0.29]
    assert df.index.name == "date"
    assert df.attrs["ticker"] == "1155"
    pd.testing.assert_frame_equal(df, again)
    assert [call[0] for call in offline.yf.calls].count("history") == 1


def test_listings(offline: Offline) -> None:
    df = bk.listings()
    calls = len(offline.yf.calls)
    again = bk.listings()

    assert list(df.columns) == ["name", "company", "sector", "market"]
    assert df.index.name == "code" and df.loc["1155", "name"] == "MAYBANK"
    assert len(offline.yf.calls) == calls
    pd.testing.assert_frame_equal(df, again)
    assert again.attrs["kind"] == "listings"


def test_opr(offline: Offline) -> None:
    df = bk.macro.opr("2023-01-01", "2024-12-31")
    calls = len(offline.transport.calls)
    again = bk.macro.opr("2023-06-01", "2024-06-30")

    assert list(df.columns) == ["rate", "change"]
    assert df.loc["2023-05-03", "rate"] == 3.0
    assert df.attrs["source"] == "bnm" and df.attrs["attribution"] == "Source: Bank Negara Malaysia"
    assert df.attrs["terms"] == "https://www.bnm.gov.my/terms-of-use-bnm-datasets"
    assert len(offline.transport.calls) == calls == 2
    assert len(again) == 6


def test_fx(offline: Offline) -> None:
    df = bk.macro.fx("usd", "2024-01-01", "2024-02-29")
    again = bk.macro.fx("USD", "2024-01-15", "2024-02-15")

    assert list(df.columns) == ["buy", "sell", "mid"]
    assert df.loc["2024-01-02", "mid"] == 4.5998
    assert df.attrs["pair"] == "USDMYR" and df.attrs["source"] == "datagovmy"
    assert len(offline.transport.calls) == 1
    assert again.index.min() == pd.Timestamp("2024-01-15")


def test_fx_falls_back_and_says_so(offline: Offline) -> None:
    offline.transport.fail_host = ("api.data.gov.my", Response(503, ""))
    df = bk.macro.fx("USD", "2024-01-01", "2024-02-29")
    assert df.attrs["source"] == "bnm"
    assert df.loc["2024-01-02", "mid"] == 4.5998


def test_fx_rejects_unknown_currencies_before_any_request(offline: Offline) -> None:
    with pytest.raises(ValueError, match="unknown currency 'XYZ'"):
        bk.macro.fx("XYZ")
    assert offline.transport.calls == []


def test_public_surface() -> None:
    assert {"prices", "dividends", "listings", "macro", "cache", "resolve"} <= set(bk.__all__)
    assert issubclass(bk.RateLimited, bk.SourceUnavailable)
    assert issubclass(bk.TickerNotFound, bk.BursakitError)

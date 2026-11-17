"""Checks against the real sources. Run nightly by ``.github/workflows/live.yml``.

    pytest tests_live

Not part of the default suite: plain ``pytest`` stays offline. A failure here
means a source changed what it returns, or is down. Each test asks for little
and goes through the same rate-limit policy as the library.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

import bursakit
from bursakit import _util
from bursakit.errors import TickerNotFound
from bursakit.schema import DIVIDENDS, FX, LISTINGS, OPR, PRICES, validate
from bursakit.sources import BNM, DataGovMy, Yahoo
from bursakit.tickers import Ticker
from tests_live.conftest import ask

TODAY = _util.today()
MONTH_AGO = TODAY - timedelta(days=30)
MAYBANK = Ticker("1155")

#: Daily series must reach at least this close to today. Wide enough for a
#: weekend plus the longest run of Malaysian public holidays.
STALE_AFTER = 10


def assert_recent(df: pd.DataFrame, within: int = STALE_AFTER) -> None:
    age = (pd.Timestamp(TODAY) - df.index.max()).days
    assert age <= within, f"newest row is {age} days old ({df.index.max().date()})"


# --------------------------------------------------------------------- yahoo


def test_yahoo_prices() -> None:
    raw = ask(lambda: Yahoo().prices(MAYBANK, MONTH_AGO, TODAY))
    out = validate(raw, PRICES, source="yahoo")

    assert len(out) >= 10
    assert_recent(out)
    assert out.index.min() >= pd.Timestamp(MONTH_AGO)


def test_yahoo_dividends() -> None:
    out = validate(ask(lambda: Yahoo().dividends(MAYBANK)), DIVIDENDS, source="yahoo")

    assert len(out) >= 10  # Maybank has paid twice a year for decades
    assert (out["amount"] > 0).all()
    assert_recent(out, within=400)


def test_yahoo_lookup() -> None:
    assert ask(lambda: Yahoo().lookup("MAYBANK")) == Ticker("1155", "MAYBANK")


def test_yahoo_unknown_ticker() -> None:
    with pytest.raises(TickerNotFound):
        ask(lambda: Yahoo().prices(Ticker("9999"), MONTH_AGO, TODAY))


def test_yahoo_listings() -> None:
    out = validate(ask(lambda: Yahoo().listings()), LISTINGS, source="yahoo")

    assert len(out) >= 500
    assert out.loc["1155", "sector"] == "Financial Services"


# ------------------------------------------------------------ official APIs


def test_bnm_opr() -> None:
    raw = ask(lambda: BNM().opr(TODAY - timedelta(days=3 * 365), TODAY))
    out = validate(raw, OPR, source="bnm")

    assert not out.empty
    assert out["rate"].between(0, 10).all()


@pytest.fixture(scope="module")
def bnm_usd() -> pd.DataFrame:
    return validate(ask(lambda: BNM().fx("USD", MONTH_AGO, TODAY)), FX, source="bnm")


@pytest.fixture(scope="module")
def datagovmy_usd() -> pd.DataFrame:
    raw = ask(lambda: DataGovMy().fx("USD", MONTH_AGO, TODAY))
    return validate(raw, FX, source="datagovmy")


def test_bnm_fx(bnm_usd: pd.DataFrame) -> None:
    assert len(bnm_usd) >= 10
    assert_recent(bnm_usd)
    assert bnm_usd["mid"].between(2, 8).all()


def test_datagovmy_fx(datagovmy_usd: pd.DataFrame) -> None:
    assert len(datagovmy_usd) >= 10
    assert_recent(datagovmy_usd)
    assert datagovmy_usd["mid"].between(2, 8).all()


def test_both_fx_sources_agree(bnm_usd: pd.DataFrame, datagovmy_usd: pd.DataFrame) -> None:
    shared = bnm_usd.index.intersection(datagovmy_usd.index)
    assert len(shared) >= 10
    gap = (bnm_usd.loc[shared, "mid"] - datagovmy_usd.loc[shared, "mid"]).abs()
    assert gap.max() < 0.005, f"mid rates differ by up to {gap.max():.4f} MYR"


# ------------------------------------------------------- through the library


def test_prices_by_name_through_the_cache() -> None:
    first = ask(lambda: bursakit.prices("MAYBANK", MONTH_AGO))
    again = bursakit.prices("1155", MONTH_AGO)

    assert first.attrs["source"] == "yahoo"
    assert first.attrs["ticker"] == "1155"
    assert_recent(first)
    pd.testing.assert_frame_equal(again, first)

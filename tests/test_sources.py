from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
import pytest

from bursakit import policy
from bursakit.errors import SourceUnavailable, TickerNotFound
from bursakit.policy import Response
from bursakit.schema import DIVIDENDS, FX, LISTINGS, OPR, PRICES, validate
from bursakit.sources import BNM, DataGovMy, Source, Yahoo
from bursakit.tickers import Ticker
from tests.conftest import Offline
from tests.replay import RecordedYF, request_key

D = date.fromisoformat
MAYBANK = Ticker("1155")


@pytest.fixture
def yahoo(offline: Offline) -> Yahoo:
    return Yahoo(offline.yf, page_size=20)


# --------------------------------------------------------------------- yahoo


def test_yahoo_prices_match_the_schema(yahoo: Yahoo) -> None:
    raw = yahoo.prices(MAYBANK, D("2024-01-01"), D("2024-01-31"))
    out = validate(raw, PRICES, source="yahoo")

    assert out.index.min() == pd.Timestamp("2024-01-02")
    assert out.index.max() == pd.Timestamp("2024-01-31")
    assert out.index.tz is None
    assert out.iloc[0].to_dict() == {
        "open": 8.89, "high": 8.92, "low": 8.83, "close": 8.92, "volume": 6414300,
    }  # fmt: skip


def test_yahoo_range_is_inclusive_and_clipped(yahoo: Yahoo) -> None:
    out = yahoo.prices(MAYBANK, D("2024-01-03"), D("2024-01-05"))
    assert [stamp.strftime("%m-%d") for stamp in out.index] == ["01-03", "01-04", "01-05"]


def test_yahoo_weekend_is_an_empty_frame_not_an_error(yahoo: Yahoo) -> None:
    out = validate(yahoo.prices(MAYBANK, D("2024-01-06"), D("2024-01-07")), PRICES)
    assert out.empty


def test_yahoo_unknown_ticker(yahoo: Yahoo) -> None:
    with pytest.raises(TickerNotFound) as caught:
        yahoo.prices(Ticker("9999"), D("2024-01-01"), D("2024-01-31"))
    assert caught.value.ticker == "9999"


def test_yahoo_dividends(yahoo: Yahoo) -> None:
    out = validate(yahoo.dividends(MAYBANK), DIVIDENDS, source="yahoo")
    assert out["amount"].to_dict() == {
        pd.Timestamp("2023-03-13"): 0.30,
        pd.Timestamp("2023-09-14"): 0.29,
        pd.Timestamp("2024-03-13"): 0.31,
        pd.Timestamp("2024-09-11"): 0.29,
    }


def test_yahoo_rejects_a_history_without_the_expected_columns() -> None:
    class Renamed(RecordedYF):
        def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
            return super().history(symbol, start, end).rename(columns={"Close": "Last"})

    with pytest.raises(SourceUnavailable, match="lacks columns"):
        Yahoo(Renamed()).prices(MAYBANK, D("2024-01-01"), D("2024-01-31"))


class Holes(RecordedYF):
    """Recorded history with values blanked out, as Yahoo sometimes serves it."""

    def __init__(self, holes: dict[str, str]) -> None:
        super().__init__()
        self.holes = holes

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        frame = super().history(symbol, start, end).astype({"Volume": "float64"})
        days = frame.index.tz_localize(None).normalize()
        for day, column in self.holes.items():
            frame.loc[days == pd.Timestamp(day), column] = float("nan")
        return frame


def test_yahoo_drops_an_incomplete_row_and_keeps_the_rest(
    yahoo: Yahoo, caplog: pytest.LogCaptureFixture
) -> None:
    whole = yahoo.prices(MAYBANK, D("2024-01-01"), D("2024-01-31"))
    holes = Yahoo(Holes({"2024-01-03": "Volume", "2024-01-10": "Close"}))
    with caplog.at_level("WARNING", logger="bursakit"):
        out = validate(holes.prices(MAYBANK, D("2024-01-01"), D("2024-01-31")), PRICES)

    gone = [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-10")]
    pd.testing.assert_frame_equal(out, validate(whole.drop(index=gone), PRICES))
    assert caplog.messages == [
        "yahoo: dropped 2 incomplete row(s) for 1155.KL: 2024-01-03, 2024-01-10"
    ]


def test_yahoo_complete_history_logs_nothing(
    yahoo: Yahoo, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG", logger="bursakit"):
        yahoo.prices(MAYBANK, D("2024-01-01"), D("2024-01-31"))
    assert caplog.messages == []


def test_yahoo_lookup(yahoo: Yahoo) -> None:
    assert yahoo.lookup("maybank") == Ticker("1155", "MAYBANK")
    assert yahoo.lookup("TENAGA") == Ticker("5347", "TENAGA")
    with pytest.raises(TickerNotFound):
        yahoo.lookup("PUBLIC")  # matches exist, none of them on Bursa


def test_yahoo_listings_page_through_every_sector(yahoo: Yahoo, offline: Offline) -> None:
    out = validate(yahoo.listings(), LISTINGS, source="yahoo")

    maybank = out.loc["1155"]
    assert maybank[["name", "company", "sector"]].tolist() == [
        "MAYBANK", "Malayan Banking Berhad", "Financial Services",
    ]  # fmt: skip
    assert out.index.is_unique and "0001" in out.index
    assert out["sector"].nunique() == 11
    assert out["market"].isna().all()
    screens = [call for call in offline.yf.calls if call[0] == "screen"]
    assert ("screen", "Financial Services", 20, 20) in screens  # second page of a sector
    assert screens[-1][1] is None  # the unfiltered pass comes last


def test_yahoo_listings_keep_unclassified_companies() -> None:
    class Stub:
        def screen(self, sector: str | None, offset: int, size: int) -> dict[str, Any]:
            quotes = [{"symbol": "1155.KL", "shortName": "MAYBANK", "longName": "Malayan Banking"}]
            if sector is None:
                quotes += [{"symbol": "9999.KL"}, {"symbol": "D05.SI", "shortName": "DBS"}]
            elif sector != "Financial Services":
                quotes = []
            return {"total": len(quotes), "quotes": quotes[offset:]}

    out = validate(Yahoo(Stub()).listings(), LISTINGS)  # type: ignore[arg-type]
    assert out.index.tolist() == ["1155", "9999"]
    assert out.loc["9999", "name"] == "9999" and pd.isna(out.loc["9999", "sector"])

    class Empty:
        def screen(self, sector: str | None, offset: int, size: int) -> dict[str, Any]:
            return {"total": 0, "quotes": []}

    with pytest.raises(SourceUnavailable, match="no Bursa listings"):
        Yahoo(Empty()).listings()  # type: ignore[arg-type]


# ----------------------------------------------------------------------- bnm


def test_bnm_opr_is_deduplicated_and_clipped() -> None:
    out = validate(BNM().opr(D("2023-01-01"), D("2024-12-31")), OPR, source="bnm")

    assert out.index.is_unique
    assert out.loc["2023-05-03"].to_dict() == {"rate": 3.0, "change": 0.25}
    assert out.loc["2023-03-09", "rate"] == 2.75
    assert (out.loc["2024", "rate"] == 3.0).all() and len(out.loc["2024"]) == 6

    clipped = BNM().opr(D("2023-05-01"), D("2023-07-31"))
    assert [stamp.strftime("%m-%d") for stamp in clipped.index] == ["05-03", "07-06"]


def test_bnm_fx(offline: Offline) -> None:
    out = validate(BNM().fx("usd", D("2024-01-01"), D("2024-02-29")), FX, source="bnm")

    assert out.iloc[0].to_dict() == {"buy": 4.5975, "sell": 4.602, "mid": 4.5998}
    assert out.index.min() == pd.Timestamp("2024-01-02")
    assert out.index.max() == pd.Timestamp("2024-02-29")
    assert len(offline.transport.calls) == 2  # one request per month


def test_bnm_quotes_per_100_units_are_normalised_to_one() -> None:
    out = BNM().fx("JPY", D("2024-01-01"), D("2024-01-31"))
    assert out.loc["2024-01-02", "buy"] == pytest.approx(0.032477, abs=1e-6)
    assert out["mid"].between(0.03, 0.035).all()


def test_bnm_month_without_records_is_skipped(offline: Offline) -> None:
    key = request_key(
        "https://api.bnm.gov.my/public/exchange-rate/USD/year/2024/month/2",
        {"session": "1700", "quote": "rm"},
    )
    offline.transport.overrides[key] = Response(404, '{"message":"No records found.","code":404}')
    out = BNM().fx("USD", D("2024-01-01"), D("2024-02-29"))
    assert out.index.max() == pd.Timestamp("2024-01-31")


@pytest.mark.parametrize(
    "body",
    [
        '{"rates": []}',
        '{"data": {"unit": 1}}',
        '{"data": {"unit": 0, "rate": [{"date": "2024-01-02", "buying_rate": 1, '
        '"selling_rate": 1, "middle_rate": 1}]}}',
    ],
)
def test_bnm_unexpected_response_is_a_source_failure(body: str, offline: Offline) -> None:
    offline.transport.fail_host = ("api.bnm.gov.my", Response(200, body))
    with pytest.raises(SourceUnavailable, match="bnm"):
        BNM().fx("USD", D("2024-01-01"), D("2024-01-31"))


def test_bnm_unexpected_opr_record(offline: Offline) -> None:
    offline.transport.fail_host = ("api.bnm.gov.my", Response(200, '{"data": [{"rate": 3}]}'))
    with pytest.raises(SourceUnavailable, match="unexpected OPR record"):
        BNM().opr(D("2024-01-01"), D("2024-12-31"))


# ----------------------------------------------------------------- datagovmy


def test_datagovmy_fx_takes_one_request(offline: Offline) -> None:
    out = validate(DataGovMy().fx("USD", D("2024-01-01"), D("2024-02-29")), FX, source="datagovmy")
    assert out.iloc[0].to_dict() == {"buy": 4.5975, "sell": 4.602, "mid": 4.5998}
    assert len(offline.transport.calls) == 1


@pytest.mark.parametrize(("currency", "last"), [("USD", "2024-02-29"), ("JPY", "2024-01-31")])
def test_both_fx_sources_produce_the_same_frame(currency: str, last: str) -> None:
    start, end = D("2024-01-01"), D(last)
    official = validate(BNM().fx(currency, start, end), FX, source="bnm")
    open_data = validate(DataGovMy().fx(currency, start, end), FX, source="datagovmy")
    pd.testing.assert_frame_equal(official, open_data, check_exact=False, rtol=1e-4)


def test_datagovmy_fills_a_missing_middle_rate(offline: Offline) -> None:
    rows = [
        {"date": "2024-01-02", "rate_type": "buying", "usd": 4.0},
        {"date": "2024-01-02", "rate_type": "selling", "usd": 5.0},
        {"date": "2024-01-02", "rate_type": "middle", "usd": None},
        {"date": "2024-01-03", "rate_type": "buying", "usd": None},
    ]
    offline.transport.fail_host = ("api.data.gov.my", Response(200, json.dumps(rows)))
    out = validate(DataGovMy().fx("USD", D("2024-01-01"), D("2024-01-31")), FX)
    assert out.to_dict("index") == {
        pd.Timestamp("2024-01-02"): {"buy": 4.0, "sell": 5.0, "mid": 4.5}
    }


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (Response(200, '{"status_code": 400}'), "expected a list"),
        (Response(200, '[{"date": "2024-01-02", "kind": "buying", "usd": 4.6}]'), "lacks fields"),
        (Response(404, "{}"), "not found"),
    ],
)
def test_datagovmy_unexpected_response_is_a_source_failure(
    reply: Response, message: str, offline: Offline
) -> None:
    offline.transport.fail_host = ("api.data.gov.my", reply)
    with pytest.raises(SourceUnavailable, match=message):
        DataGovMy().fx("USD", D("2024-01-01"), D("2024-01-31"))


def test_datagovmy_no_rows_is_an_empty_frame(offline: Offline) -> None:
    offline.transport.fail_host = ("api.data.gov.my", Response(200, "[]"))
    assert validate(DataGovMy().fx("USD", D("2024-01-06"), D("2024-01-07")), FX).empty


# ---------------------------------------------------------------- interface


def test_adapters_declare_what_they_support() -> None:
    supported = {
        source.name: {kind for kind in ("prices", "dividends", "listings", "lookup", "opr", "fx")
                      if source.supports(kind)}
        for source in (Yahoo(), BNM(), DataGovMy())
    }  # fmt: skip
    assert supported == {
        "yahoo": {"prices", "dividends", "listings", "lookup"},
        "bnm": {"opr", "fx"},
        "datagovmy": {"fx"},
    }
    assert all(source.attribution for source in (Yahoo(), BNM(), DataGovMy()))
    assert all(source.terms.startswith("https://") for source in (Yahoo(), BNM(), DataGovMy()))
    assert policy.POLICIES.keys() >= supported.keys()
    assert not Source().supports("prices")

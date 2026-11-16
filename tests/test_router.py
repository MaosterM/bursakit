from __future__ import annotations

from datetime import date
from typing import ClassVar

import pandas as pd
import pytest

from bursakit import router
from bursakit.errors import RateLimited, SchemaError, SourceUnavailable, TickerNotFound
from bursakit.policy import Response
from bursakit.sources import Source
from bursakit.tickers import Ticker
from tests.conftest import Offline

JAN = (date(2024, 1, 1), date(2024, 1, 31))
#: The exchange-rate range that was recorded from both sources.
FX_RANGE = (date(2024, 1, 1), date(2024, 2, 29))


def test_first_source_in_the_route_answers(offline: Offline) -> None:
    df, source = router.fetch("fx", "USD", *FX_RANGE)
    assert source == "datagovmy" == router.ROUTES["fx"][0]
    assert len(df) > 15
    assert all("data.gov.my" in call for call in offline.transport.calls)


def test_falls_back_when_the_first_source_is_down(offline: Offline) -> None:
    offline.transport.fail_host = ("api.data.gov.my", Response(503, ""))
    df, source = router.fetch("fx", "USD", *FX_RANGE)

    assert source == "bnm"
    assert df.iloc[0]["mid"] == 4.5998
    assert sum("data.gov.my" in call for call in offline.transport.calls) == 4  # retried per policy


def test_falls_back_when_the_first_source_changes_shape() -> None:
    class Drifted(Source):
        name: ClassVar[str] = "datagovmy"

        def fx(self, currency: str, start: date, end: date) -> pd.DataFrame:
            return pd.DataFrame(
                {"bid": [4.6], "ask": [4.7], "middle": [4.65]}, index=pd.to_datetime(["2024-01-02"])
            )

    router.register(Drifted())
    _, source = router.fetch("fx", "USD", *FX_RANGE)
    assert source == "bnm"


def test_every_source_failing_raises_source_unavailable(offline: Offline) -> None:
    offline.transport.fail_host = ("api.", Response(500, ""))
    with pytest.raises(SourceUnavailable, match="no source could provide fx") as caught:
        router.fetch("fx", "USD", *FX_RANGE)
    assert [cause.source for cause in caught.value.causes] == ["datagovmy", "bnm"]  # type: ignore[attr-defined]
    assert not isinstance(caught.value, RateLimited)


def test_every_source_rate_limiting_raises_rate_limited(offline: Offline) -> None:
    offline.transport.fail_host = ("api.", Response(429, "", {"Retry-After": "120"}))
    with pytest.raises(RateLimited) as caught:
        router.fetch("fx", "USD", *FX_RANGE)
    assert caught.value.retry_after == 120.0
    assert len(caught.value.causes) == 2


def test_schema_drift_with_no_fallback_is_reported() -> None:
    class Drifted(Source):
        name: ClassVar[str] = "bnm"

        def opr(self, start: date, end: date) -> pd.DataFrame:
            return pd.DataFrame({"level": [3.0]}, index=pd.to_datetime(["2024-01-24"]))

    router.register(Drifted())
    with pytest.raises(SourceUnavailable, match="missing columns") as caught:
        router.fetch("opr", *JAN)
    assert isinstance(caught.value.causes[0], SchemaError)


def test_ticker_not_found_is_not_disguised_as_an_outage() -> None:
    with pytest.raises(TickerNotFound):
        router.fetch("prices", Ticker("9999"), *JAN)
    with pytest.raises(TickerNotFound):
        router.lookup("NOTAREALCO")


def test_lookup_returns_the_ticker_and_its_source() -> None:
    assert router.lookup("MAYBANK") == (Ticker("1155", "MAYBANK"), "yahoo")


def test_a_source_that_lacks_the_data_type_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(router.ROUTES, "opr", ("yahoo", "bnm"))
    _, source = router.fetch("opr", date(2024, 1, 1), date(2024, 12, 31))
    assert source == "bnm"

    monkeypatch.setitem(router.ROUTES, "opr", ("yahoo",))
    with pytest.raises(SourceUnavailable, match="does not provide the OPR"):
        router.fetch("opr", *JAN)


def test_every_route_names_a_source_that_supports_it() -> None:
    router.reset()
    for kind, names in router.ROUTES.items():
        assert names, kind
        for name in names:
            assert router._source(name).supports(kind), (kind, name)


def test_attribution() -> None:
    assert router.attribution("bnm") == "Bank Negara Malaysia"
    assert router.attribution("yahoo") == "Yahoo Finance"
    assert router.attribution("cache") == "cache"

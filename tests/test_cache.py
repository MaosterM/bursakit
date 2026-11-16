from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from bursakit import _util, cache
from bursakit.cache import Coverage, plan
from bursakit.errors import SchemaError, SourceUnavailable
from tests.conftest import TODAY

D = date.fromisoformat


class FakeSource:
    """A deterministic price source that records which ranges it was asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []
        self.factor = 1.0
        self.broken = False
        #: Calls from this one on (counting from 1) fail, as if the source went down.
        self.down_from: int | None = None

    def __call__(self, start: date, end: date) -> tuple[pd.DataFrame, str]:
        self.calls.append((start, end))
        if self.down_from is not None and len(self.calls) >= self.down_from:
            raise SourceUnavailable("fake: down", source="fake")
        days = pd.bdate_range(start, end)
        price = (5 + (days.day_of_year % 40) / 10) * self.factor
        frame = pd.DataFrame(
            {
                "open": price,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price,
                "volume": 1000,
            },
            index=days,
        )
        if self.broken:
            frame = frame.rename(columns={"close": "last"})
        return frame, "fake"


@pytest.fixture
def source() -> FakeSource:
    return FakeSource()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1_000_000.0]
    monkeypatch.setattr(cache, "_now", lambda: now[0])
    return now


def get(source: FakeSource, start: str, end: str, **options: object) -> pd.DataFrame:
    df, _ = cache.series("prices", "TEST", D(start), D(end), source, **options)  # type: ignore[arg-type]
    return df


# ------------------------------------------------------------------ planning


def test_plan_with_nothing_cached_fetches_everything() -> None:
    assert plan(None, D("2024-01-01"), D("2024-03-31"), now=0, ttl=60) == [
        ("all", D("2024-01-01"), D("2024-03-31"))
    ]


def test_plan_fetches_only_what_is_missing() -> None:
    cov = Coverage(D("2024-01-01"), D("2024-03-31"), D("2024-03-31"), fetched_at=0, source="x")
    inside = plan(cov, D("2024-02-01"), D("2024-02-29"), now=10**9, ttl=60)
    later = plan(cov, D("2024-02-01"), D("2024-04-30"), now=0, ttl=60)
    earlier = plan(cov, D("2023-06-01"), D("2024-02-29"), now=0, ttl=60)
    with_overlap = plan(cov, D("2024-02-01"), D("2024-04-30"), now=0, ttl=60, overlap=7)

    assert inside == []  # settled history never expires
    assert later == [("tail", D("2024-04-01"), D("2024-04-30"))]
    assert earlier == [("head", D("2023-06-01"), D("2023-12-31"))]
    assert with_overlap == [("tail", D("2024-03-25"), D("2024-04-30"))]


def test_plan_refetches_unsettled_rows_only_after_the_ttl() -> None:
    cov = Coverage(D("2024-01-01"), D("2024-03-31"), D("2024-03-30"), fetched_at=1000, source="x")
    assert plan(cov, D("2024-01-01"), D("2024-03-31"), now=1030, ttl=60) == []
    assert plan(cov, D("2024-01-01"), D("2024-03-31"), now=1090, ttl=60) == [
        ("tail", D("2024-03-31"), D("2024-03-31"))
    ]
    assert plan(cov, D("2024-01-01"), D("2024-03-30"), now=1090, ttl=60) == []


# -------------------------------------------------------------------- series


def test_second_call_is_served_from_the_cache(source: FakeSource) -> None:
    first = get(source, "2024-01-01", "2024-03-31")
    second = get(source, "2024-01-01", "2024-03-31")
    part = get(source, "2024-02-01", "2024-02-29")

    assert source.calls == [(D("2024-01-01"), D("2024-03-31"))]
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(part, first.loc["2024-02-01":"2024-02-29"])
    assert len(first) == len(pd.bdate_range("2024-01-01", "2024-03-31"))


def test_only_the_missing_tail_and_head_are_fetched(source: FakeSource) -> None:
    get(source, "2024-02-01", "2024-03-31")
    wider = get(source, "2024-01-01", "2024-04-30")

    assert source.calls == [
        (D("2024-02-01"), D("2024-03-31")),
        (D("2024-04-01"), D("2024-04-30")),
        (D("2024-01-01"), D("2024-01-31")),
    ]
    assert len(wider) == len(pd.bdate_range("2024-01-01", "2024-04-30"))
    cov = cache.coverage("prices", "TEST")
    assert cov is not None
    assert (cov.start, cov.covered_through, cov.settled_through, cov.source) == (
        D("2024-01-01"), D("2024-04-30"), D("2024-04-30"), "fake",
    )  # fmt: skip


def test_a_gap_between_two_requests_is_filled(source: FakeSource) -> None:
    get(source, "2024-01-01", "2024-01-31")
    get(source, "2024-06-01", "2024-06-30")
    whole = get(source, "2024-01-01", "2024-06-30")

    assert source.calls == [
        (D("2024-01-01"), D("2024-01-31")),
        (D("2024-02-01"), D("2024-06-30")),
    ]
    assert len(whole) == len(pd.bdate_range("2024-01-01", "2024-06-30"))


def test_todays_row_expires_but_history_does_not(source: FakeSource, clock: list[float]) -> None:
    start, today = "2025-01-01", TODAY.isoformat()
    get(source, start, today)
    clock[0] += cache.TTL["prices"] - 1
    get(source, start, today)
    assert len(source.calls) == 1

    clock[0] += 2
    get(source, start, today)
    assert source.calls[1:] == [(TODAY, TODAY)]

    clock[0] += 10 * cache.TTL["prices"]
    get(source, start, (TODAY - timedelta(days=1)).isoformat())
    assert len(source.calls) == 2  # yesterday and earlier are settled


def test_the_next_day_fetches_from_the_last_unsettled_day(
    source: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    get(source, "2025-01-01", TODAY.isoformat())
    tomorrow = TODAY + timedelta(days=1)
    monkeypatch.setattr(_util, "today", lambda: tomorrow)

    get(source, "2025-01-01", tomorrow.isoformat())

    assert source.calls[1:] == [(TODAY, tomorrow)]


def test_end_is_capped_at_today_and_future_ranges_are_empty(source: FakeSource) -> None:
    capped = get(source, "2025-01-01", "2030-01-01")
    future = get(source, "2026-01-01", "2026-12-31")

    assert source.calls == [(D("2025-01-01"), TODAY)]
    assert capped.index.max() <= pd.Timestamp(TODAY)
    assert future.empty and list(future.columns) == ["open", "high", "low", "close", "volume"]


def test_restated_history_triggers_a_full_refetch(source: FakeSource) -> None:
    get(source, "2024-01-01", "2024-03-29", verify="close", overlap=7)
    source.factor = 0.5  # a 2-for-1 split: the source now reports halved prices
    after = get(source, "2024-01-01", "2024-04-30", verify="close", overlap=7)

    assert source.calls == [
        (D("2024-01-01"), D("2024-03-29")),
        (D("2024-03-23"), D("2024-04-30")),  # tail, overlapping a week of stored rows
        (D("2024-01-01"), D("2024-04-30")),  # overlap disagreed: everything again
    ]
    assert after["close"].max() < 5


def test_an_unchanged_overlap_keeps_the_stored_history(source: FakeSource) -> None:
    get(source, "2024-01-01", "2024-03-29", verify="close", overlap=7)
    get(source, "2024-01-01", "2024-04-30", verify="close", overlap=7)
    assert len(source.calls) == 2


def test_refresh_discards_what_is_stored(source: FakeSource) -> None:
    get(source, "2024-01-01", "2024-03-31")
    source.factor = 2.0
    refreshed = get(source, "2024-02-01", "2024-02-29", refresh=True)

    assert source.calls[-1] == (D("2024-02-01"), D("2024-02-29"))
    assert refreshed["close"].min() > 9
    assert cache.coverage("prices", "TEST").start == D("2024-02-01")  # type: ignore[union-attr]


def test_a_failed_refresh_keeps_what_is_stored(source: FakeSource) -> None:
    before = get(source, "2024-01-01", "2024-03-29")
    source.down_from = 2
    with pytest.raises(SourceUnavailable):
        get(source, "2024-01-01", "2024-03-29", refresh=True)

    after = get(source, "2024-01-01", "2024-03-29")  # still answered by the cache
    pd.testing.assert_frame_equal(after, before)
    assert len(source.calls) == 2


def test_a_refresh_with_bad_data_keeps_what_is_stored(source: FakeSource) -> None:
    before = get(source, "2024-01-01", "2024-03-29")
    source.broken = True
    with pytest.raises(SchemaError):
        get(source, "2024-01-01", "2024-03-29", refresh=True)

    pd.testing.assert_frame_equal(get(source, "2024-01-01", "2024-03-29"), before)


def test_a_failed_refetch_after_a_restatement_keeps_the_old_history(source: FakeSource) -> None:
    before = get(source, "2024-01-01", "2024-03-29", verify="close", overlap=7)
    source.factor = 0.5
    source.down_from = 3  # the tail arrives and disagrees; the full refetch then fails
    with pytest.raises(SourceUnavailable):
        get(source, "2024-01-01", "2024-04-30", verify="close", overlap=7)

    source.down_from = None
    source.factor = 1.0
    pd.testing.assert_frame_equal(get(source, "2024-01-01", "2024-03-29"), before)
    assert len(source.calls) == 3  # that last read needed no fetch


def test_a_frame_that_fails_the_schema_is_never_stored(source: FakeSource) -> None:
    source.broken = True
    with pytest.raises(SchemaError, match="missing columns"):
        get(source, "2024-01-01", "2024-03-31")
    assert cache.coverage("prices", "TEST") is None
    assert cache.info()["series"] == {}

    source.broken = False
    assert len(get(source, "2024-01-01", "2024-03-31")) > 60


# ------------------------------------------------------------ frames, values


def dividends() -> tuple[pd.DataFrame, str]:
    frame = pd.DataFrame(
        {"amount": [0.3, 0.29]}, index=pd.to_datetime(["2023-03-13", "2023-09-14"])
    )
    return frame, "fake"


def test_frames_are_cached_until_their_ttl(clock: list[float]) -> None:
    calls = []

    def fetch() -> tuple[pd.DataFrame, str]:
        calls.append(1)
        return dividends()

    first, source = cache.frame("dividends", "TEST", fetch)
    second, _ = cache.frame("dividends", "TEST", fetch)
    assert (len(calls), source) == (1, "fake")
    pd.testing.assert_frame_equal(first, second)

    clock[0] += cache.TTL["dividends"] + 1
    cache.frame("dividends", "TEST", fetch)
    cache.frame("dividends", "TEST", fetch, refresh=True)
    assert len(calls) == 3


def test_listing_codes_survive_the_round_trip() -> None:
    def fetch() -> tuple[pd.DataFrame, str]:
        frame = pd.DataFrame(
            {"name": ["INARI"], "company": [None], "sector": ["Technology"], "market": [None]},
            index=["0166"],
        )
        return frame, "fake"

    cache.frame("listings", "all", fetch)
    cached, _ = cache.frame("listings", "all", fetch)
    assert cached.index.tolist() == ["0166"]
    assert pd.isna(cached.loc["0166", "market"])


def test_values_expire(clock: list[float]) -> None:
    cache.put_value("alias", "MAYBANK", {"code": "1155"}, source="fake")
    assert cache.get_value("alias", "MAYBANK") == {"code": "1155"}
    assert cache.get_value("alias", "TENAGA") is None
    clock[0] += cache.TTL["alias"] + 1
    assert cache.get_value("alias", "MAYBANK") is None


def test_clear_and_info(source: FakeSource, monkeypatch: pytest.MonkeyPatch) -> None:
    get(source, "2024-01-01", "2024-01-31")
    cache.frame("dividends", "TEST", dividends)
    info = cache.info()
    assert info["series"] == {"prices": {"keys": 1, "rows": 23}}
    assert info["entries"] == {"dividends": 1}
    assert info["bytes"] > 0 and info["path"].endswith("bursakit.sqlite3")

    cache.clear("prices")
    assert cache.info()["series"] == {} and cache.info()["entries"] == {"dividends": 1}
    cache.clear()
    assert cache.info()["entries"] == {}


def test_cache_location_follows_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BURSAKIT_CACHE_DIR")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/someone/AppData/Local")
    monkeypatch.setenv("XDG_CACHE_HOME", "/home/someone/.cache")
    monkeypatch.setattr(cache.sys, "platform", "win32")
    assert cache.path().parts[-2:] == ("bursakit", "Cache")
    monkeypatch.setattr(cache.sys, "platform", "linux")
    assert cache.path().parts[-2:] == (".cache", "bursakit")

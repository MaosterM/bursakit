from __future__ import annotations

import pytest
import requests

from bursakit import policy
from bursakit.errors import RateLimited, SourceUnavailable
from bursakit.policy import Policy, Response
from tests.conftest import Offline


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, offline: Offline) -> list[float]:
    """A clock that only moves when the policy sleeps."""
    now = [100.0]

    def sleep(seconds: float) -> None:
        offline.slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(policy, "clock", lambda: now[0])
    monkeypatch.setattr(policy, "sleep", sleep)
    monkeypatch.setitem(
        policy.POLICIES, "test", Policy(min_interval=2.0, backoff=1.0, max_wait=10.0)
    )
    return now


class Flaky:
    """Raises each queued error in turn, then returns ``"ok"``."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def down(retryable: bool = True) -> SourceUnavailable:
    return SourceUnavailable("down", source="test", retryable=retryable)


def test_calls_to_one_source_are_spaced(clock: list[float], offline: Offline) -> None:
    for _ in range(3):
        policy.call("test", lambda: None)
    assert offline.slept == [2.0, 2.0]

    clock[0] += 60  # after a quiet minute there is nothing to wait for
    policy.call("test", lambda: None)
    assert offline.slept == [2.0, 2.0]


def test_sources_do_not_wait_for_each_other(clock: list[float], offline: Offline) -> None:
    policy.call("test", lambda: None)
    policy.call("another", lambda: None)
    assert offline.slept == []


def test_transient_failures_are_retried_with_backoff(clock: list[float], offline: Offline) -> None:
    fn = Flaky(down(), down())
    assert policy.call("test", fn) == "ok"
    assert fn.calls == 3
    assert offline.slept == [1.0, 1.0, 2.0]  # backoff 1s, wait out the interval, backoff 2s


def test_retries_stop_at_the_limit(clock: list[float]) -> None:
    fn = Flaky(*[down() for _ in range(10)])
    with pytest.raises(SourceUnavailable):
        policy.call("test", fn)
    assert fn.calls == 4  # one attempt plus max_retries


def test_permanent_failures_are_not_retried(clock: list[float]) -> None:
    fn = Flaky(down(retryable=False))
    with pytest.raises(SourceUnavailable):
        policy.call("test", fn)
    assert fn.calls == 1


def test_retry_after_is_honoured_when_short(clock: list[float], offline: Offline) -> None:
    fn = Flaky(RateLimited("slow down", source="test", retry_after=7.0))
    assert policy.call("test", fn) == "ok"
    assert offline.slept == [7.0]


def test_a_long_retry_after_is_passed_to_the_caller(clock: list[float]) -> None:
    fn = Flaky(RateLimited("slow down", source="test", retry_after=600.0))
    with pytest.raises(RateLimited) as caught:
        policy.call("test", fn)
    assert caught.value.retry_after == 600.0
    assert fn.calls == 1


def respond(monkeypatch: pytest.MonkeyPatch, *replies: Response | Exception) -> list[str]:
    queue = list(replies)
    seen: list[str] = []

    def transport(url: str, params: object, headers: object, timeout: float) -> Response:
        seen.append(url)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(policy, "transport", transport)
    return seen


def test_get_json_decodes_a_good_response(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, Response(200, '{"data": [1, 2]}'))
    assert policy.get_json("test", "https://example.test/x") == {"data": [1, 2]}


def test_get_json_maps_status_codes_to_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, Response(404, "{}"))
    with pytest.raises(policy.HTTPNotFound):
        policy.get_json("test", "https://example.test/x")

    respond(monkeypatch, Response(403, "forbidden"))
    with pytest.raises(SourceUnavailable, match="HTTP 403") as caught:
        policy.get_json("test", "https://example.test/x")
    assert not caught.value.retryable

    respond(monkeypatch, Response(200, "<html>maintenance</html>"))
    with pytest.raises(SourceUnavailable, match="not JSON"):
        policy.get_json("test", "https://example.test/x")


def test_get_json_retries_server_errors_and_dropped_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = respond(
        monkeypatch, Response(503, ""), requests.ConnectionError("reset"), Response(200, "[]")
    )
    assert policy.get_json("test", "https://example.test/x") == []
    assert len(seen) == 3


def test_get_json_reads_retry_after_from_a_429(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, Response(429, "", {"Retry-After": "900"}))
    with pytest.raises(RateLimited) as caught:
        policy.get_json("test", "https://example.test/x")
    assert caught.value.retry_after == 900.0
    assert caught.value.source == "test"

    respond(monkeypatch, Response(429, "", {"retry-after": "soon"}), Response(200, "{}"))
    assert policy.get_json("test", "https://example.test/x") == {}


def test_every_built_in_source_has_a_policy() -> None:
    assert {"yahoo", "bnm", "datagovmy"} <= set(policy.POLICIES)
    assert policy.policy_for("something-new") is policy.DEFAULT
    # data.gov.my publishes 4 requests per minute.
    assert policy.POLICIES["datagovmy"].min_interval >= 15

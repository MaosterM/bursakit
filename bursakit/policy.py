"""Rate limit and retry policy. Defined once, here, for every source.

Every outbound call goes through :func:`call`, which spaces requests to one
source by that source's ``min_interval`` and retries transient failures with
exponential backoff. HTTP sources use :func:`get_json`, which maps status codes
to bursakit errors before :func:`call` decides whether to retry.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

import requests

from .errors import RateLimited, SourceUnavailable

__all__ = ["DEFAULT", "POLICIES", "HTTPNotFound", "Policy", "Response", "call", "get_json"]

T = TypeVar("T")

USER_AGENT = "bursakit (+https://pypi.org/project/bursakit/)"


@dataclass(frozen=True)
class Policy:
    #: Minimum seconds between two calls to the same source.
    min_interval: float
    #: Retries after the first attempt, for retryable failures only.
    max_retries: int = 3
    #: First backoff in seconds; doubles each retry.
    backoff: float = 1.0
    #: Never sleep longer than this for one retry. A longer Retry-After raises.
    max_wait: float = 30.0
    #: Per-request timeout in seconds.
    timeout: float = 30.0


DEFAULT = Policy(min_interval=1.0)

POLICIES: dict[str, Policy] = {
    # Unofficial access: stay well under anything that looks like scraping.
    "yahoo": Policy(min_interval=0.5),
    "bnm": Policy(min_interval=0.5),
    # Published limit for the Data Catalogue API: 4 requests per minute.
    "datagovmy": Policy(min_interval=15.0, max_wait=60.0),
}


class HTTPNotFound(SourceUnavailable):
    """HTTP 404. Adapters decide whether that means "no rows" or "bad request"."""


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[str, Mapping[str, str], Mapping[str, str], float], Response]

_session: requests.Session | None = None


def _requests_transport(
    url: str, params: Mapping[str, str], headers: Mapping[str, str], timeout: float
) -> Response:
    global _session
    if _session is None:
        _session = requests.Session()
    reply = _session.get(url, params=dict(params), headers=dict(headers), timeout=timeout)
    return Response(reply.status_code, reply.text, dict(reply.headers))


#: The function that performs HTTP GETs. Tests replace it with a fixture replayer.
transport: Transport = _requests_transport

# Indirections so tests can run without real waiting.
sleep: Callable[[float], None] = time.sleep
clock: Callable[[], float] = time.monotonic

_lock = threading.Lock()
_next_slot: dict[str, float] = {}


def policy_for(source: str) -> Policy:
    return POLICIES.get(source, DEFAULT)


def reset() -> None:
    """Forget when each source was last called."""
    with _lock:
        _next_slot.clear()


def _wait_turn(source: str, policy: Policy) -> None:
    with _lock:
        now = clock()
        slot = max(now, _next_slot.get(source, now))
        _next_slot[source] = slot + policy.min_interval
    if slot > now:
        sleep(slot - now)


def call(source: str, fn: Callable[[], T]) -> T:
    """Run ``fn`` under ``source``'s rate limit, retrying transient failures."""
    policy = policy_for(source)
    attempt = 0
    while True:
        _wait_turn(source, policy)
        try:
            return fn()
        except RateLimited as exc:
            wait = exc.retry_after if exc.retry_after is not None else policy.backoff * 2**attempt
            if attempt >= policy.max_retries or wait > policy.max_wait:
                raise
        except SourceUnavailable as exc:
            if not exc.retryable or attempt >= policy.max_retries:
                raise
            wait = min(policy.backoff * 2**attempt, policy.max_wait)
        sleep(wait)
        attempt += 1


def get_json(
    source: str,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """GET ``url`` and return the decoded JSON body, under ``source``'s policy."""
    policy = policy_for(source)
    query = dict(params or {})
    send_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}

    def attempt() -> Any:
        try:
            reply = transport(url, query, send_headers, policy.timeout)
        except requests.RequestException as exc:
            raise SourceUnavailable(
                f"{source}: request failed ({type(exc).__name__}: {exc})",
                source=source,
                retryable=True,
                causes=[exc],
            ) from exc
        return _decode(source, url, reply)

    return call(source, attempt)


def _decode(source: str, url: str, reply: Response) -> Any:
    status = reply.status
    if status == 429:
        raise RateLimited(
            f"{source}: rate limited (HTTP 429)",
            source=source,
            retry_after=_retry_after(reply.headers),
        )
    if status == 404:
        raise HTTPNotFound(f"{source}: HTTP 404 for {url}", source=source)
    if status >= 500:
        raise SourceUnavailable(f"{source}: HTTP {status}", source=source, retryable=True)
    if status != 200:
        raise SourceUnavailable(f"{source}: HTTP {status} for {url}", source=source)
    try:
        return json.loads(reply.body)
    except ValueError as exc:
        raise SourceUnavailable(f"{source}: response is not JSON", source=source) from exc


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None

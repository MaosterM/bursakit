"""Setup for the live checks: real sources, throwaway cache.

These tests sit outside ``tests/`` on purpose. Everything under ``tests/`` has
its sockets blocked; nothing here does.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

import pytest

from bursakit import router
from bursakit.errors import RateLimited

T = TypeVar("T")


@pytest.fixture(autouse=True)
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use the built-in adapters and a cache that is thrown away after each test."""
    monkeypatch.setenv("BURSAKIT_CACHE_DIR", str(tmp_path / "cache"))
    router.reset()
    yield
    router.reset()


def ask(call: Callable[[], T]) -> T:
    """Run one call against a source. Rate limiting skips the test instead of failing it.

    A rate limit says nothing about whether the source still answers in the
    shape bursakit expects, so it is reported as "not checked". Every other
    failure, an outage included, fails the test.
    """
    try:
        return call()
    except RateLimited as exc:
        pytest.skip(f"not checked, the source is rate limiting this machine: {exc}")

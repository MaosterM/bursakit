"""Every test runs offline, against recorded responses and a throwaway cache."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from bursakit import _util, policy, router
from bursakit.sources import Yahoo
from tests.replay import FixtureTransport, RecordedYF

#: "Today" for the suite. Later than every recorded row, so all of it is settled.
TODAY = date(2025, 1, 15)


@dataclass
class Offline:
    transport: FixtureTransport
    yf: RecordedYF
    slept: list[float] = field(default_factory=list)


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Offline]:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setenv("BURSAKIT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(_util, "today", lambda: TODAY)

    world = Offline(FixtureTransport(), RecordedYF())
    monkeypatch.setattr(policy, "transport", world.transport)
    monkeypatch.setattr(policy, "sleep", world.slept.append)
    policy.reset()
    router.reset()
    router.register(Yahoo(world.yf, page_size=20))
    yield world
    router.reset()
    policy.reset()

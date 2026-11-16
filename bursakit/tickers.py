"""Ticker resolution: ``1155``, ``"1155.KL"`` and ``"MAYBANK"`` are one ticker."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import TickerNotFound

__all__ = ["Ticker", "parse", "resolve"]

# Bursa stock codes: four digits, optionally two more characters (0820EA, 5235SS).
_CODE = re.compile(r"^(\d{4}[A-Z0-9]{0,2})(?:\.KL)?$")
_SHORT_NUMBER = re.compile(r"^\d{1,3}$")
_NAME = re.compile(r"^[A-Z0-9][A-Z0-9&.\-]{1,14}$")


@dataclass(frozen=True)
class Ticker:
    """A Bursa-listed security, identified by its stock code."""

    code: str
    name: str | None = None

    @property
    def symbol(self) -> str:
        """The Yahoo-style symbol, e.g. ``1155.KL``."""
        return f"{self.code}.KL"

    def __str__(self) -> str:
        return self.code


def parse(raw: object) -> Ticker | None:
    """Resolve the forms that need no lookup: stock codes, with or without ``.KL``.

    Returns ``None`` for anything that looks like a name instead.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Ticker(f"{raw:04d}") if 0 < raw < 10_000 else None
    if not isinstance(raw, str):
        return None
    text = raw.strip().upper()
    if _SHORT_NUMBER.match(text):
        text = text.zfill(4)
    match = _CODE.match(text)
    return Ticker(match.group(1)) if match else None


def resolve(raw: object) -> Ticker:
    """Resolve a stock code, ``.KL`` symbol or stock name to a :class:`Ticker`.

    Codes resolve offline. A name costs one lookup, then is cached.
    """
    if isinstance(raw, Ticker):
        return raw
    ticker = parse(raw)
    if ticker is not None:
        return ticker
    if not isinstance(raw, str):
        raise TickerNotFound(raw)
    name = raw.strip().upper()
    if name.endswith(".KL"):
        name = name[:-3]
    if not _NAME.match(name):
        raise TickerNotFound(raw)

    from . import cache, router  # imported late: both depend on this module

    cached = cache.get_value("alias", name)
    if isinstance(cached, dict) and isinstance(cached.get("code"), str):
        return Ticker(cached["code"], cached.get("name"))
    found, source = router.lookup(name)
    cache.put_value("alias", name, {"code": found.code, "name": found.name}, source=source)
    return found
